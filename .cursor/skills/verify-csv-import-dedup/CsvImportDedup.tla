---------------------------- MODULE CsvImportDedup ----------------------------
(***************************************************************************)
(* Liner Notes CSV import, the dedup protocol in upload_csv.               *)
(*                                                                          *)
(* Property: an upload of valid rows stores each album once for that user, *)
(* under the same user and lowercased artist and album the unique index    *)
(* uses, even when another upload of that album by the same user is in     *)
(* progress.                                                                *)
(*                                                                          *)
(* What that prevents: an upload that overlaps one album failing at commit *)
(* and dropping every other album in that file.                            *)
(*                                                                          *)
(* One importer is one request in upload_csv                               *)
(* (backend/app/api/routes/cds.py): one AsyncSession from get_db            *)
(* (backend/app/core/database.py).                                          *)
(*                                                                          *)
(* Upsert = TRUE is the code now. upload_csv strips album_name the same    *)
(* way it strips artist, collects the valid rows, and stable-sorts them    *)
(* by (artist.lower(), album_name.lower()) before the write loop. Each     *)
(* write is _upsert_cd: pg_insert(CD).on_conflict_do_update on             *)
(* user_id, lower(artist), lower(album_name). That is the expression       *)
(* unique index uq_artist_album_lowercase after upgrade() in               *)
(* backend/alembic/versions/002_user_accounts.py. 001 created the index    *)
(* without user_id; 002 drops it and recreates it. Both modeled uploads    *)
(* are one user, so TLC's key is the album pair. check.py will not run    *)
(* TLC if user_id is missing from the index or the conflict target.       *)
(* One statement inserts                                                    *)
(* or updates. It does not SELECT and then db.add. The per-row except      *)
(* still surrounds that statement. await db.commit() is once, after the    *)
(* loop. On an exception, get_db rolls the session back.                   *)
(*                                                                          *)
(* Ordered = TRUE is that sort. Every request locks keys in the same       *)
(* order, so two uploads cannot deadlock on the unique index. Ordered =    *)
(* FALSE is the crossing pair the sort removes: i1 writes Abbey then       *)
(* Revolver, i2 writes Revolver then Abbey.                                 *)
(*                                                                          *)
(* Keys are already stripped and lowercased, the key the index uses.       *)
(* The checker refuses to run TLC when album_name is not stripped,         *)
(* because this spec does not contain the unstripped string.               *)
(*                                                                          *)
(* Upsert = FALSE is the protocol this fix replaced, kept so a removed     *)
(* ON CONFLICT is still a failing check. ProcessRow is one iteration of    *)
(* that older loop: await db.execute of the func.lower SELECT (autoflush   *)
(* first; AsyncSessionLocal does not set autoflush=False) and the          *)
(* synchronous existing_cd update or db.add. CommitImport is the same      *)
(* await db.commit(). A flushed insert holds the unique index until that   *)
(* session commits or rolls back. A db.add that has not been flushed       *)
(* holds no lock.                                                           *)
(*                                                                          *)
(* Other sessions see only committed rows (Postgres READ COMMITTED, the    *)
(* default; the code never sets an isolation level).                       *)
(***************************************************************************)

EXTENDS Integers, Sequences, FiniteSets

CONSTANTS InFileScenario, UniqueIndex, AutoFlush, LookupBeforeAdd, Upsert, Ordered

ASSUME InFileScenario \in BOOLEAN
ASSUME UniqueIndex \in BOOLEAN
ASSUME AutoFlush \in BOOLEAN
ASSUME LookupBeforeAdd \in BOOLEAN
ASSUME Upsert \in BOOLEAN
ASSUME Ordered \in BOOLEAN

I1 == "i1"
I2 == "i2"
\* Abbey and Revolver stand for two (LOWER(artist), LOWER(album_name)) pairs.
Abbey == "abbey"
Revolver == "revolver"

Importers == IF InFileScenario THEN {I1} ELSE {I1, I2}
Keys == {Abbey, Revolver}

\* infile: one file contains Abbey twice.
\* upsert, sorted: i1's file is Abbey; i2's file is Abbey then Revolver.
\* upsert, not sorted: the two files take opposite lock orders.
\* no upsert: the older overlap, Abbey against Abbey then Revolver.
File(i) ==
  IF InFileScenario THEN <<Abbey, Abbey>>
  ELSE IF Upsert /\ ~Ordered THEN
    IF i = I1 THEN <<Abbey, Revolver>> ELSE <<Revolver, Abbey>>
  ELSE IF i = I1 THEN <<Abbey>>
  ELSE <<Abbey, Revolver>>

Blank == [k \in Keys |-> 0]

VARIABLES
  catalog, \* committed row count per key. The table cds after commits.
  phase,   \* "row" | "commit" | "committed" | "failed" per importer
  idx,     \* next 1-based row of File(i)
  pending, \* row this transaction will insert at commit, per key
  flushed, \* unique-index lock held by this transaction, per key
  aborted  \* this transaction can no longer commit

vars == <<catalog, phase, idx, pending, flushed, aborted>>

TypeOK ==
  /\ catalog \in [Keys -> Nat]
  /\ phase \in [Importers -> {"row", "commit", "committed", "failed"}]
  /\ idx \in [Importers -> Nat]
  /\ pending \in [Importers -> [Keys -> Nat]]
  /\ flushed \in [Importers -> [Keys -> Nat]]
  /\ aborted \in [Importers -> BOOLEAN]

Init ==
  /\ catalog = Blank
  /\ phase = [i \in Importers |-> "row"]
  /\ idx = [i \in Importers |-> 1]
  /\ pending = [i \in Importers |-> Blank]
  /\ flushed = [i \in Importers |-> Blank]
  /\ aborted = [i \in Importers |-> FALSE]

Advance(i) ==
  /\ idx' = [idx EXCEPT ![i] = idx[i] + 1]
  /\ phase' = [phase EXCEPT ![i] =
       IF idx[i] + 1 > Len(File(i)) THEN "commit" ELSE "row"]

\* Someone else's flushed insert of this key holds uq_artist_album_lowercase.
OtherHolds(i, k) ==
  \E j \in Importers \ {i} : flushed[j][k] > 0

\* ---- the upsert protocol (_upsert_cd) ------------------------------------

\* INSERT ... ON CONFLICT (user_id, lower(artist), lower(album_name)) DO UPDATE.
\* The statement waits while another transaction holds that index entry.
\* With the index gone, Postgres rejects the ON CONFLICT clause, the
\* per-row except records it, and the transaction is aborted.
UpsertRow(i) ==
  /\ phase[i] = "row"
  /\ idx[i] <= Len(File(i))
  /\ LET k == File(i)[idx[i]]
         already == catalog[k] > 0 \/ pending[i][k] > 0
     IN /\ aborted[i] \/ ~OtherHolds(i, k)
        /\ IF aborted[i]
           THEN /\ Advance(i)
                /\ UNCHANGED <<catalog, pending, flushed, aborted>>
           ELSE IF ~UniqueIndex
           THEN /\ aborted' = [aborted EXCEPT ![i] = TRUE]
                /\ Advance(i)
                /\ UNCHANGED <<catalog, pending, flushed>>
           ELSE /\ flushed' = [flushed EXCEPT ![i][k] = 1]
                /\ IF already
                   THEN UNCHANGED pending
                   ELSE pending' = [pending EXCEPT ![i][k] = 1]
                /\ UNCHANGED <<catalog, aborted>>
                /\ Advance(i)

UpsertCommit(i) ==
  /\ phase[i] = "commit"
  /\ IF aborted[i]
     THEN \* commit raises, get_db rolls back
       /\ phase' = [phase EXCEPT ![i] = "failed"]
       /\ pending' = [pending EXCEPT ![i] = Blank]
       /\ flushed' = [flushed EXCEPT ![i] = Blank]
       /\ UNCHANGED <<catalog, idx, aborted>>
     ELSE \* inserts become rows; an update leaves the count unchanged
       /\ catalog' = [k \in Keys |-> catalog[k] + pending[i][k]]
       /\ phase' = [phase EXCEPT ![i] = "committed"]
       /\ pending' = [pending EXCEPT ![i] = Blank]
       /\ flushed' = [flushed EXCEPT ![i] = Blank]
       /\ UNCHANGED <<idx, aborted>>

\* ---- the check-then-insert protocol ON CONFLICT replaced -----------------

Sees(cat, flu, k) == cat[k] + flu[k] > 0

FlushBlocked(i) ==
  /\ ~aborted[i]
  /\ AutoFlush /\ UniqueIndex
  /\ \E p \in Keys : pending[i][p] > 0 /\ OtherHolds(i, p)

ProcessRow(i) ==
  /\ phase[i] = "row"
  /\ idx[i] <= Len(File(i))
  /\ ~FlushBlocked(i)
  /\ LET k == File(i)[idx[i]]
     IN IF aborted[i]
        THEN /\ Advance(i)
             /\ UNCHANGED <<catalog, pending, flushed, aborted>>
        ELSE IF AutoFlush /\ UniqueIndex
                /\ \E p \in Keys : pending[i][p] > 0 /\ catalog[p] > 0
        THEN /\ aborted' = [aborted EXCEPT ![i] = TRUE]
             /\ Advance(i)
             /\ UNCHANGED <<catalog, pending, flushed>>
        ELSE LET flushed2 == [p \in Keys |->
                   flushed[i][p] + (IF AutoFlush THEN pending[i][p] ELSE 0)]
                 pendingLeft == IF AutoFlush THEN Blank ELSE pending[i]
             IN /\ IF LookupBeforeAdd /\ Sees(catalog, flushed2, k)
                   THEN /\ pending' = [pending EXCEPT ![i] = pendingLeft]
                        /\ flushed' = [flushed EXCEPT ![i] = flushed2]
                   ELSE /\ pending' = [pending EXCEPT ![i] =
                             [pendingLeft EXCEPT ![k] = pendingLeft[k] + 1]]
                        /\ flushed' = [flushed EXCEPT ![i] = flushed2]
                /\ UNCHANGED <<catalog, aborted>>
                /\ Advance(i)

Inserts(i, pend, flu) == [k \in Keys |-> pend[i][k] + flu[i][k]]

CommitBlocked(i) ==
  /\ ~aborted[i]
  /\ UniqueIndex
  /\ LET ins == Inserts(i, pending, flushed)
     IN \E k \in Keys : ins[k] > 0 /\ OtherHolds(i, k)

CommitImport(i) ==
  /\ phase[i] = "commit"
  /\ ~CommitBlocked(i)
  /\ LET ins == Inserts(i, pending, flushed)
         conflict ==
           UniqueIndex /\ \E k \in Keys :
             ins[k] > 1 \/ (ins[k] > 0 /\ catalog[k] > 0)
     IN IF aborted[i] \/ conflict
        THEN /\ phase' = [phase EXCEPT ![i] = "failed"]
             /\ pending' = [pending EXCEPT ![i] = Blank]
             /\ flushed' = [flushed EXCEPT ![i] = Blank]
             /\ UNCHANGED <<catalog, idx, aborted>>
        ELSE /\ catalog' = [k \in Keys |-> catalog[k] + ins[k]]
             /\ phase' = [phase EXCEPT ![i] = "committed"]
             /\ pending' = [pending EXCEPT ![i] = Blank]
             /\ flushed' = [flushed EXCEPT ![i] = Blank]
             /\ UNCHANGED <<idx, aborted>>

Done ==
  /\ \A i \in Importers : phase[i] \in {"committed", "failed"}
  /\ UNCHANGED vars

UpsertRowStep == /\ Upsert /\ \E i \in Importers : UpsertRow(i)
UpsertCommitStep == /\ Upsert /\ \E i \in Importers : UpsertCommit(i)
ProcessRowStep == /\ ~Upsert /\ \E i \in Importers : ProcessRow(i)
CommitImportStep == /\ ~Upsert /\ \E i \in Importers : CommitImport(i)

Next ==
  \/ UpsertRowStep
  \/ UpsertCommitStep
  \/ ProcessRowStep
  \/ CommitImportStep
  \/ Done

Spec == Init /\ [][Next]_vars

\* Guarded by uq_artist_album_lowercase in upgrade(), and by the
\* ON CONFLICT target in _upsert_cd using that same index.
NoDuplicateAlbums ==
  \A k \in Keys : catalog[k] <= 1

\* A finished file of valid rows must have committed, with every album it
\* carried present in cds. "failed" drops the whole transaction.
ImportKeepsEveryValidRow ==
  \A i \in Importers :
    phase[i] \in {"committed", "failed"} =>
      /\ phase[i] = "committed"
      /\ \A n \in 1..Len(File(i)) : catalog[File(i)[n]] >= 1

\* Revolver is only on i2's file when the files are the sorted overlap.
\* In the crossing pair both files contain it, so the interesting failure
\* there is deadlock (TLC), not a missing key.
NoExclusiveAlbumDropped ==
  \/ InFileScenario
  \/ Upsert /\ ~Ordered
  \/ phase[I2] \notin {"committed", "failed"}
  \/ catalog[Revolver] >= 1

=============================================================================
