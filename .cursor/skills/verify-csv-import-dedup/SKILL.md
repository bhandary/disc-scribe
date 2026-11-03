---
name: verify-csv-import-dedup
description: "Check DiscVault CSV import dedup with TLC. Use when a change touches upload_csv, _upsert_cd, CD inserts, uq_artist_album_lowercase, AsyncSessionLocal, get_db, or the CSV modal line that says duplicates are updated automatically."
---

# Verify CSV import dedup

Two uploads of the same album, or the same album twice in one file, must leave one `cds` row for that lowercased artist and album. A valid row must not disappear because the other upload committed first. `"Abbey Road"` and `"Abbey Road "` are the same album.

**Property:** Every album in a valid upload is stored once, under the same lowercased artist and album the unique index uses, even when another upload of that album is in progress.

**What it prevents:** An upload that overlaps one album can fail at commit and drop every other album in that file, and the client gets a failed request instead of an update.

Exit 0 means that property holds for the protocol in the working tree, and the broken variants still fail. It does not mean some other edit is safe.

## When this applies

Run the check when a diff touches any of these:

- `backend/app/api/routes/cds.py` — `upload_csv`, `_upsert_cd`, and any new `pg_insert(CD)` or `CD(...)` call
- `backend/alembic/versions/001_initial_schema.py` — `upgrade`, index `uq_artist_album_lowercase`
- `backend/app/core/database.py` — `AsyncSessionLocal`, `get_db`
- `frontend/components/csv-upload-modal.tsx` — the line "Duplicates will be updated automatically."

Also run it when a new file constructs `CD(` or inserts into `cds`. A diff that touches none of these does not affect the check.

If the modal sentence changes on purpose, the invariant has to change too. Cite the new sentence. Do not change the invariant because a run failed.

## Run

From the repo root:

```sh
python3 .cursor/skills/verify-csv-import-dedup/check.py
```

Needs `java` on `PATH` (confirmed with OpenJDK 21). The first run downloads `tla2tools` 1.7.4 from GitHub and checks sha256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`. Later runs use `~/.cache/disc-scribe/tla2tools-1.7.4.jar`. TLC is version 2.19 from that jar, one worker, `-Xmx512m`. A run is about 10 seconds. The script writes configs and TLC logs under `.cursor/skills/verify-csv-import-dedup/last-run/` (gitignored).

The same promise has a Postgres test, `backend/tests/test_upload_csv_dedup.py`. It needs a database whose URL is `DATABASE_URL` (default `postgresql+asyncpg://discvault:discvault@127.0.0.1:5432/discvault_dedup_test`) and skips when that server is down. TLC is the concurrency argument. The test checks the end state of two overlapping `upload_csv` calls and the trailing-space key.

## What the result means

The script reads the working tree and sets the model switches from it:

- `Upsert` — `upload_csv` calls `_upsert_cd`, and `_upsert_cd` calls `on_conflict_do_update` with `literal_column("lower(artist)")` and `literal_column("lower(album_name)")`
- `Ordered` — `upload_csv` sorts the valid rows by a key that calls `.lower()` at least twice (the artist and album pair) before that write
- `UniqueIndex` — `upgrade()` creates unique index `uq_artist_album_lowercase` on `LOWER(artist)`, `LOWER(album_name)`
- `album_name` strip — the assignment to `album_name` in `upload_csv` is a `.strip()` call, the same treatment `artist` already had
- `AutoFlush` — `AsyncSessionLocal = async_sessionmaker(...)` does not pass `autoflush=False`. Used only by the check-then-insert variant.

Exit 0: those switches match the recorded shape, `NoDuplicateAlbums`, `ImportKeepsEveryValidRow`, and `NoExclusiveAlbumDropped` pass for one file and for two overlapping uploads, and the three broken variants still fail. The import described by this model keeps every valid album once.

Exit 1, and the output says `"Abbey Road"` and `"Abbey Road "` are different keys: `album_name` is not stripped. `LOWER` does not trim, so the unique index stores both. The model keys are already stripped, so this is not a TLC verdict and not a reason to edit the spec. Strip `album_name`.

Exit 1, with "The model does not describe this code": a step was added or moved in a way the model does not have (a second `await db.commit()`, commit inside `try`, `with_for_update`, an `IntegrityError` handler, another isolation level, a `pg_insert(CD)` outside `upload_csv` / `_upsert_cd`, an `ON CONFLICT` target that is not `lower(artist), lower(album_name)`). That is a modeling gap. Do not call the old proof a pass. Update `CsvImportDedup.tla` so each action is again one indivisible step of the new code, then rerun.

Exit 1, with a TLC status that is not the recorded one: read the trace. Replay it against `upload_csv` and `_upsert_cd`.

- `UpsertRow` is one call to `_upsert_cd`: one `INSERT ... ON CONFLICT DO UPDATE`. Another request runs only before or after that statement. The statement waits while another transaction holds `uq_artist_album_lowercase` for that key.
- `UpsertCommit` is `await db.commit()` after the loop. On failure the exception leaves `upload_csv` and `get_db` rolls the session back.
- `ProcessRow` and `CommitImport` are the old loop (`SELECT` then `db.add`). They run only when `Upsert` is false.
- If every step can happen in that code, it is a bug. Say so. Do not edit an invariant or a switch to force exit 0.
- If a step cannot happen, the model is wrong. Fix the model. Do not weaken the property.

A removed guard is a bug, not a gap, when the script still understands the shape. Deleting `on_conflict_do_update` sets `Upsert` false and TLC runs the old race. Deleting the `.sort(...)` sets `Ordered` false. Deleting `uq_artist_album_lowercase` sets `UniqueIndex` false. Deleting `.strip()` on `album_name` is the counterexample above.

Exit 1, with "a broken variant did not fail": the variant section of `check.py` is how the invariants prove they can still fail. A pass there means someone weakened the property or the broken protocol. Do not change a variant's expected status to exit 0.

Read every TLC result with the pstack `/statechart` skill. The spec is `.cursor/skills/verify-csv-import-dedup/CsvImportDedup.tla`. The configs and logs are the files the command just wrote in `.cursor/skills/verify-csv-import-dedup/last-run/`. Read `/statechart` and follow it. Do not copy its commands or paths from this skill.

## The protocol TLC checks

`_upsert_cd` inserts a row or updates the row that shares its lowercased artist and album. `lyricist`, `genre`, `num_discs`, and `updated_at` move on conflict. `ai_summary`, cover art, and the stored names stay. `upload_csv` sorts by `(artist.lower(), album_name.lower())` first, so two requests take `uq_artist_album_lowercase` locks in one order. The same album twice in one file is an insert and then an update. `await db.commit()` then publishes that transaction.

On that shape the three invariants pass. The concurrent graph is the sorted overlap: `i1` carries Abbey, `i2` carries Abbey then Revolver (10 distinct states). The one-file graph is Abbey twice (4 distinct states). Nothing is committed at the start.

## Showing the properties fail

These variants are part of every run. The script forces the switches; it does not need the working tree to be broken. Restore any scratch in the product code after trying one. Do not commit the break.

- Remove `on_conflict_do_update` from `_upsert_cd`. `Upsert` is false. TLC runs the old loop: both sessions `SELECT` Abbey, both miss, both `db.add`, the first commit wins, and the second file dies at autoflush or at `await db.commit()`. `ImportKeepsEveryValidRow` and `NoExclusiveAlbumDropped` fail. Revolver, the album only the second file had, is gone, or the request fails after the rows were the other session's problem.
- Also delete `op.create_index('uq_artist_album_lowercase', ...)` in `upgrade()`, still without the upsert. `NoDuplicateAlbums` fails: both commits succeed and the catalog has two Abbey rows.
- Remove `pending.sort(...)` and keep the upsert. `Ordered` is false. The files are Abbey then Revolver against Revolver then Abbey. Each session holds one key and waits for the other. TLC reports deadlock. This check counts that deadlock as a failed run of `ImportKeepsEveryValidRow`: the uploads never reach `committed`. While both are still in `row`, the invariant formula is true; the failure is the missing next step. Postgres would abort one of those transactions, and `get_db` would roll that file back.
- Leave the upsert in place and delete `op.create_index('uq_artist_album_lowercase', ...)` (or pass `unique=False`). `ON CONFLICT (lower(artist), lower(album_name))` is then a statement error (`there is no unique or exclusion constraint matching the ON CONFLICT specification`). The per-row `except` records it, `await db.commit()` rolls the file back, and `ImportKeepsEveryValidRow` fails. That case is the code-shaped run, not a separate variant.
- Assign `album_name` without `.strip()` (the old `row.get('album_name') or row.get('album', '').strip()`). The command exits 1 with the `"Abbey Road "` counterexample and does not claim a TLC pass.

## Updating the check after an intended change

1. Read the new `upload_csv`, `_upsert_cd`, `upgrade`, and `AsyncSessionLocal`.
2. Edit `CsvImportDedup.tla` so each action is still one indivisible step of that code. Keep the names from this repo (`upload_csv`, `_upsert_cd`, `uq_artist_album_lowercase`, `get_db`).
3. Change an invariant only if the promise changed on purpose. Quote the old sentence, the new sentence, and where the new promise is written (the modal, a comment, or the commit message).
4. Rerun the command. Then break the new guard the way the invariant describes, confirm the command exits 1, and restore the break. The variant section must still fail on its own.
5. Move `SYNC_COMMIT` in `check.py` and the sync commit below only after that rerun describes the code at the new commit. Do not move it because the command exited 0 on a stale model.

If merges landed on this code without a rerun, use `/maintain-formal-verification-skill`.

## Coverage

Sync commit: `d83ade882370659e38d706c190926719c02d88b8`

Product files at that commit are what this model was read against. Move the sync commit forward only after a rerun that still describes the covered functions at the new commit.

| What the model uses | Where |
| --- | --- |
| Strip `artist` and `album_name`, sort by the lowercased pair, one upsert per valid row, per-row `except`, one `await db.commit()` | `upload_csv` in `backend/app/api/routes/cds.py` |
| `pg_insert(CD).on_conflict_do_update` on `lower(artist)`, `lower(album_name)`; update `lyricist`, `genre`, `num_discs`, `updated_at` | `_upsert_cd` in the same file |
| Rollback when that commit raises | `get_db` in `backend/app/core/database.py` |
| Autoflush left at the library default (the old loop only) | `AsyncSessionLocal` in `backend/app/core/database.py` |
| Unique index on `LOWER(artist)`, `LOWER(album_name)` | `upgrade` in `backend/alembic/versions/001_initial_schema.py` (`uq_artist_album_lowercase`) |
| The only `pg_insert(CD)` | `_upsert_cd` |
| The promise the invariant states | "Duplicates will be updated automatically." in `frontend/components/csv-upload-modal.tsx` |
| End state of two overlapping uploads, and `"Abbey Road "` against `"Abbey Road"` | `backend/tests/test_upload_csv_dedup.py` |

## Bounds and assumptions

- Two concurrent `upload_csv` sessions, or one session. Files are length 1 and 2 in the concurrent scenario (Abbey; Abbey then Revolver) and two identical Abbeys in the one-file scenario. Two album keys. The unsorted variant swaps the two-row file to Revolver then Abbey against Abbey then Revolver.
- Postgres READ COMMITTED, which is the server default. The code never sets an isolation level. An upsert holds `uq_artist_album_lowercase` for that key until the session commits or rolls back. The other session's upsert of the same key waits.
- The sort is the lock order. Python's sort is stable, so two rows with the same key keep file order and the later row is the update. The model counts rows; it does not track `genre` or `lyricist`. Which concurrent upload's fields win is the later commit.
- `str.lower()` in the sort and `LOWER()` in the index and in the `ON CONFLICT` target agree. The model keys are already that pair, and already stripped.
- One upsert is one step. A commit that lands inside `await db.execute` of that single statement is not a separate step.
- With the unique index removed, `ON CONFLICT (lower(artist), lower(album_name))` is a statement error, not a silent second insert. Two rows appear only when the upsert and the index are both gone.

## What this does not cover

- More than two concurrent uploads, files longer than two rows, or a catalog that already contains duplicate keys.
- Rows rejected for missing artist, album, or genre. A whitespace-only album becomes empty because of `.strip()` and is an error row; the model starts from valid keys.
- Which overlapping upload's `genre`, `lyricist`, or `num_discs` remains. The test does not assert that either. `ai_summary` and the stored names are not in the model; the test checks that one later upsert leaves `ai_summary` in place and does not rename the row.
- Cover art (`fetch_missing_cover_art` uses the request session after the response). Enrichment (`enrich_cd_stream` writing `ai_summary`). API key order in `get_runtime_keys`.
- Non-ASCII case folding, where Python `str.lower` and Postgres `LOWER` can disagree.
- The frontend parser in `csv-upload-modal.tsx` (Papa Parse). Only the server loop is modeled.
