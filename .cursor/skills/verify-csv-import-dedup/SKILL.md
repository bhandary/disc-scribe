---
name: verify-csv-import-dedup
description: "Check DiscVault CSV import dedup with TLC. Use when a change touches upload_csv, CD inserts, uq_artist_album_lowercase, AsyncSessionLocal, get_db, or the CSV modal line that says duplicates are updated automatically."
---

# Verify CSV import dedup

Two uploads of the same album, or the same album twice in one file, must leave one `cds` row for that lowercased artist and album, and a valid row must not disappear because the other upload committed first.

**Property:** Every album in a valid upload is stored once, under the same lowercased artist and album the unique index uses, even when another upload of that album is in progress.

**Harm:** An upload that overlaps one album can fail at commit and drop every other album in that file, and the client gets a failed request instead of an update.

The current code breaks the second half of that promise. The check records the break. It does not paper over it. Exit 0 means the recorded break is still the one TLC finds, and the uniqueness half still holds in the model.

## When this applies

Run the check when a diff touches any of these:

- `backend/app/api/routes/cds.py` — `upload_csv`, and any new `CD(...)` call
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

Needs `java` on `PATH` (confirmed with OpenJDK 21). The first run downloads `tla2tools` 1.7.4 from GitHub and checks sha256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`. Later runs use `~/.cache/disc-scribe/tla2tools-1.7.4.jar`. TLC is version 2.19 from that jar, one worker, `-Xmx512m`. A run is about 5 seconds. The script writes configs and TLC logs under `.cursor/skills/verify-csv-import-dedup/last-run/` (gitignored).

## What the result means

The script reads the working tree and sets three model switches from it:

- `LookupBeforeAdd` — in `upload_csv`, `db.execute` of the `func.lower` SELECT comes before `db.add`, and `db.add` sits in only one branch of `if existing_cd`
- `UniqueIndex` — `upgrade()` creates unique index `uq_artist_album_lowercase` on `LOWER(artist)`, `LOWER(album_name)`
- `AutoFlush` — `AsyncSessionLocal = async_sessionmaker(...)` does not pass `autoflush=False` (SQLAlchemy's default is True; `db.execute` therefore flushes pending `db.add`s first)

Exit 0: those three switches match the recorded shape, `NoDuplicateAlbums` passes, and both `ImportKeepsEveryValidRow` and `NoExclusiveAlbumDropped` fail on the concurrent scenario. The one-file scenario (Abbey twice) passes. **Exit 0 does not mean the import is safe.** It means the bug below is still the bug.

Exit 1, with "The model does not describe this code": a step was added or moved in a way the model does not have (commit inside the loop, `with_for_update`, `ON CONFLICT`, another `CD(...)` writer, the casefold removed from the SELECT). That is a modeling gap. Do not call the old proof a pass. Update `CsvImportDedup.tla` so each action is again one indivisible step of the new code, then rerun.

Exit 1, with a TLC status that is not the recorded one: read the trace. Replay it against `upload_csv`.

- `ProcessRow` is one iteration of the `for` loop: `await db.execute` (autoflush, then the SELECT) and the synchronous update-or-`db.add` after it. Another request runs only before or after that step.
- `CommitImport` is `await db.commit()` after the loop. On failure the exception leaves `upload_csv` and `get_db` rolls the session back.
- If every step can happen in that code, it is a bug. Say so. Do not edit an invariant or a switch to force exit 0.
- If a step cannot happen, the model is wrong. Fix the model. Do not weaken the property.

A removed guard is a bug, not a gap, when the script still understands the shape: deleting `uq_artist_album_lowercase` sets `UniqueIndex` false; `db.add` outside `if existing_cd` sets `LookupBeforeAdd` false; `autoflush=False` sets `AutoFlush` false. TLC then runs the broken protocol.

Read every TLC result with the pstack `/statechart` skill. The spec is `.cursor/skills/verify-csv-import-dedup/CsvImportDedup.tla`. The configs and logs are the files the command just wrote in `.cursor/skills/verify-csv-import-dedup/last-run/`. Read `/statechart` and follow it. Do not copy its commands or paths from this skill.

## The bug TLC finds

`i1`'s file is one album, called Abbey here (one `LOWER(artist)`, `LOWER(album_name)` pair). `i2`'s file is Abbey, then a second album, Revolver. Nothing is committed at the start. This is the shortest trace of `NoExclusiveAlbumDropped` (TLC, 16 distinct states before it stopped):

1. `i1` in `upload_csv` runs the SELECT, finds no row, and `db.add`s Abbey. The insert is pending. The request is ready for `await db.commit()`.
2. `i2` runs the SELECT for Abbey. `i1` has not committed, so under READ COMMITTED the SELECT misses. `i2` `db.add`s Abbey, still pending.
3. `i1` reaches `await db.commit()`. The INSERT succeeds. `cds` has Abbey.
4. `i2` reads Revolver. `await db.execute` autoflushes `i2`'s pending Abbey insert. `uq_artist_album_lowercase` rejects it. The `except` around the row records the error and does not `db.add` Revolver.
5. `i2` reaches `await db.commit()`. The transaction is already aborted, so the commit raises. `get_db` rolls the session back. Revolver is not in `cds`. The HTTP request fails. `frontend/lib/api.ts` `uploadCSV` throws, and `csv-upload-modal.tsx` only `console.error`s.

The same model also fails `ImportKeepsEveryValidRow` on a same-length trace where `i2` commits both albums first (its autoflush of Abbey happens before `i1` commits, so `i1`'s commit waits on the unique index and then raises). Abbey and Revolver are stored, but `i1`'s upload still errors instead of updating.

`NoDuplicateAlbums` passes on this code: the index keeps `catalog[k] <= 1` for both keys. The full concurrent graph is 17 distinct states, depth 6. One file that lists Abbey twice also passes (4 distinct states): the second iteration autoflushes the first `db.add`, the SELECT sees it, and the branch updates instead of inserting.

## Showing the properties fail

These are the broken variants the invariants were checked against. Restore the code after trying one. Do not commit the break.

- Delete the `op.create_index('uq_artist_album_lowercase', ...)` call in `upgrade()`. `NoDuplicateAlbums` fails: both sessions `db.add` Abbey before either commits, both commits succeed, and the catalog has two Abbey rows.
- `db.add` even when `existing_cd` is set (or drop the `if existing_cd` branch). On one file that contains Abbey twice, `ImportKeepsEveryValidRow` fails: the second insert makes the unique index reject the commit, and the file is rolled back.
- Pass `autoflush=False` to `async_sessionmaker`. The second SELECT does not see the pending `db.add`. The file of two Abbeys fails at commit the same way.

## Updating the check after an intended change

1. Read the new `upload_csv`, `upgrade`, and `AsyncSessionLocal`.
2. Edit `CsvImportDedup.tla` so each action is still one indivisible step of that code. Keep the names from this repo (`upload_csv`, `db.add`, `uq_artist_album_lowercase`, `get_db`).
3. Change an invariant only if the promise changed on purpose. Quote the old sentence, the new sentence, and where the new promise is written (the modal, a comment, or the commit message).
4. Rerun the command. Then break the new guard the way the invariant describes (remove the new check, or reorder the new step), confirm the command exits 1, and restore the break.
5. Move `SYNC_COMMIT` in `check.py` and the sync commit below only after that rerun describes the code at the new commit. Do not move it because the command exited 0 on a stale model.

If merges landed on this code without a rerun, use `/maintain-formal-verification-skill`.

## Coverage

Sync commit: `61674d92faa9b17c62f2e946a499cafe03cba9b1`

Product files at that commit are what this model was read against. This skill does not change them. Move the sync commit forward only after a rerun that still describes the covered functions at the new commit.

| What the model uses | Where |
| --- | --- |
| One request, one session, the row loop, the SELECT, the update branch, `db.add`, the per-row `except`, `await db.commit()` | `upload_csv` in `backend/app/api/routes/cds.py` |
| Rollback when that commit raises | `get_db` in `backend/app/core/database.py` |
| Autoflush left at the library default | `AsyncSessionLocal` in `backend/app/core/database.py` |
| Unique index on `LOWER(artist)`, `LOWER(album_name)` | `upgrade` in `backend/alembic/versions/001_initial_schema.py` (`uq_artist_album_lowercase`) |
| The only `CD(...)` construction | `upload_csv` (the model class is `CD` in `backend/app/models/cd.py`; the model does not declare the unique index) |
| The promise the invariant states | "Duplicates will be updated automatically." in `frontend/components/csv-upload-modal.tsx` |

There is no test suite in the repo that hits two overlapping `upload_csv` calls.

## Bounds and assumptions

- Two concurrent `upload_csv` sessions, or one session. Files are length 1 and 2 in the concurrent scenario (Abbey; Abbey then Revolver) and two identical Abbeys in the one-file scenario. Two album keys.
- Postgres READ COMMITTED, which is the server default. The code never sets an isolation level. A flushed insert holds `uq_artist_album_lowercase` until that session commits or rolls back; the other session's INSERT waits. A `db.add` that has not been flushed holds no lock.
- `str.lower()` in the SELECT and `LOWER()` in the index agree. The model keys are already that pair. The anchor check requires `func.lower` on both `CD.artist` and `CD.album_name`.
- `artist` is stripped before that comparison, as `upload_csv` does. The model starts from an empty `cds` table.
- One loop iteration is one step. A commit that lands between the autoflush INSERT and the SELECT inside a single `await db.execute` is not a separate step. That window only adds more ways for the same commit failure to happen.

## What this does not cover

- `album_name` is not stripped when the column is `album_name` (`album_name = row.get('album_name') or row.get('album', '').strip()` in `upload_csv`). `"Abbey Road"` and `"Abbey Road "` are different keys for both the SELECT and the index, so both rows are stored. This check does not prove uniqueness for real CSV strings.
- More than two concurrent uploads, files longer than two rows, or a catalog that already contains duplicates (`scalar_one_or_none` would raise `MultipleResultsFound`, which the per-row `except` swallows).
- Rows rejected for missing artist, album, or genre. Cover art (`fetch_missing_cover_art` uses the request session after the response). Enrichment (`enrich_cd_stream` writing `ai_summary`). API key order in `get_runtime_keys`.
- Non-ASCII case folding, where Python `str.lower` and Postgres `LOWER` can disagree.
- The frontend parser in `csv-upload-modal.tsx` (Papa Parse). Only the server loop is modeled.
