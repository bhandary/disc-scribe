---------------------------- MODULE CsvImportDedup ----------------------------
(***************************************************************************)
(* DiscVault CSV import, the dedup protocol in upload_csv.                 *)
(*                                                                          *)
(* Property: an upload of valid rows stores each of its albums once,       *)
(* matched on the same lowercased artist and album the unique index uses,  *)
(* even when another upload of that album is in progress.                  *)
(*                                                                          *)
(* Harm: an upload that overlaps one album can fail at commit and drop     *)
(* every other album in that file.                                          *)
(*                                                                          *)
(* One importer is one request in upload_csv                               *)
(* (backend/app/api/routes/cds.py): one AsyncSession from get_db            *)
(* (backend/app/core/database.py).                                          *)
(*                                                                          *)
(* ProcessRow is one iteration of the for-loop. The only yield in that     *)
(* iteration is `await db.execute` of the SELECT on                        *)
(* func.lower(CD.artist) and func.lower(CD.album_name). SQLAlchemy         *)
(* autoflush (AsyncSessionLocal does not set autoflush=False, so the       *)
(* library default True is in force) sends this session's pending          *)
(* db.add inserts before that SELECT. The branch after the SELECT,         *)
(* existing_cd update or db.add, is synchronous, so it is part of this     *)
(* same step. Another request runs only before or after the step.          *)
(*                                                                          *)
(* CommitImport is `await db.commit()` after the loop. On IntegrityError   *)
(* the exception is not caught in upload_csv; get_db rolls the session     *)
(* back. A conflict is uq_artist_album_lowercase, created unique in        *)
(* upgrade() (backend/alembic/versions/001_initial_schema.py).              *)
(*                                                                          *)
(* Keys are already the lookup key: LOWER(artist), LOWER(album_name),      *)
(* with artist stripped the way upload_csv strips it. album_name is not    *)
(* stripped on the album_name column; this model does not explore that.    *)
(*                                                                          *)
(* Other sessions see only committed rows (Postgres READ COMMITTED, the    *)
(* default; the code never sets an isolation level).                        *)
(*                                                                          *)
(* A flushed insert holds uq_artist_album_lowercase until that session      *)
(* commits or rolls back. Another session's INSERT of the same key waits.  *)
(* The model disables that insert until the holder finishes. db.add alone  *)
(* is still pending and holds no lock.                                     *)
(***************************************************************************)

EXTENDS Integers, Sequences, FiniteSets

CONSTANTS InFileScenario, UniqueIndex, AutoFlush, LookupBeforeAdd

ASSUME InFileScenario \in BOOLEAN
ASSUME UniqueIndex \in BOOLEAN
ASSUME AutoFlush \in BOOLEAN
ASSUME LookupBeforeAdd \in BOOLEAN

I1 == "i1"
I2 == "i2"
\* Abbey and Revolver stand for two (LOWER(artist), LOWER(album_name)) pairs.
Abbey == "abbey"
Revolver == "revolver"

Importers == IF InFileScenario THEN {I1} ELSE {I1, I2}
Keys == {Abbey, Revolver}

\* concurrent: i1's file is Abbey; i2's file is Abbey then Revolver.
\* infile: one file contains Abbey twice, the repeated-row case in one CSV.
File(i) ==
  IF InFileScenario
  THEN <<Abbey, Abbey>>
  ELSE IF i = I1 THEN <<Abbey>> ELSE <<Abbey, Revolver>>

Blank == [k \in Keys |-> 0]

VARIABLES
  catalog, \* committed row count per key. The table cds after commits.
  phase,   \* "row" | "commit" | "committed" | "failed" per importer
  idx,     \* next 1-based row of File(i)
  pending, \* db.add not yet flushed, per session
  flushed, \* inserts flushed in this transaction, not committed
  aborted  \* per-row except already caught an IntegrityError

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

\* The row this session's SELECT can see: committed rows, plus its own
\* flushed inserts. Pending db.add rows are visible only after autoflush.
\* Other sessions' uncommitted rows are invisible.
Sees(cat, flu, k) == cat[k] + flu[k] > 0

\* Someone else's flushed insert of this key holds the unique index.
OtherHolds(i, k) ==
  \E j \in Importers \ {i} : flushed[j][k] > 0

\* Autoflush would INSERT a pending key that another session already
\* inserted and has not committed. `await db.execute` waits there.
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
        THEN \* later rows: execute raises, the per-row except swallows it
          /\ Advance(i)
          /\ UNCHANGED <<catalog, pending, flushed, aborted>>
        ELSE IF AutoFlush /\ UniqueIndex
                /\ \E p \in Keys : pending[i][p] > 0 /\ catalog[p] > 0
        THEN \* autoflush INSERT hits uq_artist_album_lowercase
          /\ aborted' = [aborted EXCEPT ![i] = TRUE]
          /\ Advance(i)
          /\ UNCHANGED <<catalog, pending, flushed>>
        ELSE LET flushed2 == [p \in Keys |->
                   flushed[i][p] + (IF AutoFlush THEN pending[i][p] ELSE 0)]
                 pendingLeft == IF AutoFlush THEN Blank ELSE pending[i]
             IN /\ IF LookupBeforeAdd /\ Sees(catalog, flushed2, k)
                   THEN \* existing_cd: assign fields, no second insert
                     /\ pending' = [pending EXCEPT ![i] = pendingLeft]
                     /\ flushed' = [flushed EXCEPT ![i] = flushed2]
                   ELSE \* CD(...); db.add(new_cd)
                     /\ pending' = [pending EXCEPT ![i] =
                          [pendingLeft EXCEPT ![k] = pendingLeft[k] + 1]]
                     /\ flushed' = [flushed EXCEPT ![i] = flushed2]
                /\ UNCHANGED <<catalog, aborted>>
                /\ Advance(i)

Inserts(i, pend, flu) == [k \in Keys |-> pend[i][k] + flu[i][k]]

\* Commit's INSERT waits on another session's uncommitted unique key.
CommitBlocked(i) ==
  /\ ~aborted[i]
  /\ UniqueIndex
  /\ LET ins == Inserts(i, pending, flushed)
     IN \E k \in Keys : ins[k] > 0 /\ OtherHolds(i, k)

CommitImport(i) ==
  /\ phase[i] = "commit"
  /\ ~CommitBlocked(i)
  /\ LET ins == Inserts(i, pending, flushed)
         \* The unique index rejects a second committed row and two inserts
         \* of one key in this same transaction.
         conflict ==
           UniqueIndex /\ \E k \in Keys :
             ins[k] > 1 \/ (ins[k] > 0 /\ catalog[k] > 0)
     IN IF aborted[i] \/ conflict
        THEN \* commit raises, get_db rolls back, catalog unchanged
          /\ phase' = [phase EXCEPT ![i] = "failed"]
          /\ pending' = [pending EXCEPT ![i] = Blank]
          /\ flushed' = [flushed EXCEPT ![i] = Blank]
          /\ UNCHANGED <<catalog, idx, aborted>>
        ELSE
          /\ catalog' = [k \in Keys |-> catalog[k] + ins[k]]
          /\ phase' = [phase EXCEPT ![i] = "committed"]
          /\ pending' = [pending EXCEPT ![i] = Blank]
          /\ flushed' = [flushed EXCEPT ![i] = Blank]
          /\ UNCHANGED <<idx, aborted>>

Done ==
  /\ \A i \in Importers : phase[i] \in {"committed", "failed"}
  /\ UNCHANGED vars

Next ==
  \/ \E i \in Importers : ProcessRow(i)
  \/ \E i \in Importers : CommitImport(i)
  \/ Done

Spec == Init /\ [][Next]_vars

\* Guarded by uq_artist_album_lowercase in upgrade().
NoDuplicateAlbums ==
  \A k \in Keys : catalog[k] <= 1

\* Guarded by the SELECT-then-update branch in upload_csv. A finished
\* file of valid rows must have committed, with every album it carried
\* present in cds. "failed" drops the whole transaction, including rows
\* that were not duplicates.
ImportKeepsEveryValidRow ==
  \A i \in Importers :
    phase[i] \in {"committed", "failed"} =>
      /\ phase[i] = "committed"
      /\ \A n \in 1..Len(File(i)) : catalog[File(i)[n]] >= 1

\* Revolver is only on i2's file. i2 finishing without it means that album
\* was rolled back with the overlapping Abbey row. Vacuous for the
\* single-file scenario, which has no Revolver row.
NoExclusiveAlbumDropped ==
  \/ InFileScenario
  \/ phase[I2] \notin {"committed", "failed"}
  \/ catalog[Revolver] >= 1

=============================================================================
