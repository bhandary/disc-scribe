#!/usr/bin/env python3
"""Check DiscVault CSV import dedup.

Reads upload_csv, the unique index, and the session factory, sets the
booleans in CsvImportDedup.tla from that code, and runs TLC.

Exit 0 means the working tree still matches the recorded finding at the
sync commit: uniqueness holds in the model, and the overlapping-import
bug is still there. It does not mean the import is safe.

Exit 1 means a new violation, a missing guard, a TLC error, or code the
model does not describe. Read the verdict before changing the model.
"""

from __future__ import annotations

import ast
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

TLC_VERSION = "1.7.4"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TLC_URL = (
    "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
)
SYNC_COMMIT = "61674d92faa9b17c62f2e946a499cafe03cba9b1"

SKILL_DIR = Path(__file__).resolve().parent
REPO = SKILL_DIR.parents[2]
SPEC = SKILL_DIR / "CsvImportDedup.tla"
LAST_RUN = SKILL_DIR / "last-run"

# These are the results for the code at SYNC_COMMIT. Do not edit them to
# make a run exit 0. If a result changes, the code or the model changed.
RECORDED_SHAPE = {
    "unique_index": True,
    "autoflush": True,
    "lookup_before_add": True,
}
RECORDED = {
    ("concurrent", "NoDuplicateAlbums"): "pass",
    ("concurrent", "ImportKeepsEveryValidRow"): "fail",
    ("concurrent", "NoExclusiveAlbumDropped"): "fail",
    ("infile", "NoDuplicateAlbums"): "pass",
    ("infile", "ImportKeepsEveryValidRow"): "pass",
    ("infile", "NoExclusiveAlbumDropped"): "pass",
}

PROPERTY_SENTENCE = (
    "Every album in a valid upload is stored once, under the same "
    "lowercased artist and album the unique index uses, even when another "
    "upload of that album is in progress."
)
HARM_SENTENCE = (
    "An upload that overlaps one album can fail at commit and drop every "
    "other album in that file, and the client gets a failed request instead "
    "of an update."
)


@dataclass
class Anchors:
    unique_index: bool | None = None
    autoflush: bool | None = None
    lookup_before_add: bool | None = None
    casefold: bool = False
    runnable: bool = False
    gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _is_db_method(node: ast.AST, method: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
    )


def _find_function(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _enclosing(tree: ast.AST, target: ast.AST, kinds: tuple[type, ...]) -> bool:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    cur = target
    while id(cur) in parents:
        cur = parents[id(cur)]
        if isinstance(cur, kinds):
            return True
    return False


def _node_contains(nodes: list[ast.AST], target: ast.AST) -> bool:
    return any(inner is target for node in nodes for inner in ast.walk(node))


def _add_guarded_by_existing(loop: ast.AST, add: ast.AST) -> bool:
    """True when db.add sits in exactly one branch of `if existing_cd`."""
    for node in ast.walk(loop):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "existing_cd" not in names:
            continue
        in_body = _node_contains(node.body, add)
        in_else = _node_contains(node.orelse, add)
        if in_body != in_else:
            return True
    return False


def _func_lower_fields(loop: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(loop):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "lower"
            and isinstance(func.value, ast.Name)
            and func.value.id == "func"
        ):
            continue
        if node.args and isinstance(node.args[0], ast.Attribute):
            found.add(node.args[0].attr)
    return found


def analyze(repo: Path) -> Anchors:
    anchors = Anchors()
    cds_path = repo / "backend/app/api/routes/cds.py"
    mig_path = repo / "backend/alembic/versions/001_initial_schema.py"
    db_path = repo / "backend/app/core/database.py"
    for path in (cds_path, mig_path, db_path):
        if not path.is_file():
            anchors.gaps.append(f"missing file {path.relative_to(repo)}")
    if anchors.gaps:
        return anchors

    cds_src = cds_path.read_text()
    cds = ast.parse(cds_src)
    upload = _find_function(cds, "upload_csv")
    if not isinstance(upload, ast.AsyncFunctionDef):
        anchors.gaps.append("upload_csv is missing from backend/app/api/routes/cds.py")
        return anchors

    loops = [n for n in ast.walk(upload) if isinstance(n, ast.For)]
    dedup_loop = None
    for loop in loops:
        has_execute = any(_is_db_method(n, "execute") for n in ast.walk(loop))
        has_add = any(_is_db_method(n, "add") for n in ast.walk(loop))
        if has_execute and has_add:
            dedup_loop = loop
            break
    if dedup_loop is None:
        anchors.gaps.append(
            "upload_csv no longer has a loop that both db.execute's a lookup "
            "and db.add's a CD. The model does not describe this shape."
        )
    else:
        executes = [n for n in ast.walk(dedup_loop) if _is_db_method(n, "execute")]
        adds = [n for n in ast.walk(dedup_loop) if _is_db_method(n, "add")]
        first_execute = min(n.lineno for n in executes)
        first_add = min(n.lineno for n in adds)
        guarded = all(_add_guarded_by_existing(dedup_loop, add) for add in adds)
        anchors.lookup_before_add = first_execute < first_add and guarded
        if not guarded:
            anchors.notes.append(
                "db.add is not confined to the missing-row branch of "
                "`if existing_cd`, so the model treats the loop as always inserting"
            )
        fields = _func_lower_fields(dedup_loop)
        anchors.casefold = {"artist", "album_name"} <= fields
        if not anchors.casefold:
            anchors.gaps.append(
                "the SELECT in upload_csv no longer calls func.lower on both "
                "CD.artist and CD.album_name, so it is not the same key as "
                "uq_artist_album_lowercase"
            )

    commits = []
    for node in ast.walk(upload):
        if isinstance(node, ast.Await) and _is_db_method(node.value, "commit"):
            commits.append(node)
    if len(commits) != 1:
        anchors.gaps.append(
            f"upload_csv has {len(commits)} `await db.commit()` calls; the model "
            "describes exactly one, after the row loop"
        )
    else:
        commit = commits[0]
        if dedup_loop is not None and commit.lineno <= dedup_loop.end_lineno:
            anchors.gaps.append(
                "await db.commit() is inside the row loop; a per-row commit "
                "is a different protocol than the one the model checks"
            )
        if _enclosing(upload, commit, (ast.Try, ast.ExceptHandler)):
            anchors.gaps.append(
                "await db.commit() is inside try/except, so a unique-index "
                "error may no longer roll the whole file back. Update the model "
                "before treating a TLC result as a verdict on this code."
            )

    segment = ast.get_source_segment(cds_src, upload) or ""
    for token, why in (
        ("with_for_update", "SELECT ... FOR UPDATE"),
        ("on_conflict", "INSERT ... ON CONFLICT"),
        ("IntegrityError", "an IntegrityError handler"),
        ("isolation", "a non-default isolation level"),
    ):
        if token in segment:
            anchors.gaps.append(
                f"upload_csv now mentions {token} ({why}). That step is not "
                "in the model."
            )

    mig = ast.parse(mig_path.read_text())
    upgrade = _find_function(mig, "upgrade")
    if upgrade is None:
        anchors.gaps.append("upgrade() is missing from 001_initial_schema.py")
    else:
        found = False
        mismatched = False
        for node in ast.walk(upgrade):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_index"
            ):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value != "uq_artist_album_lowercase":
                continue
            found = True
            unique = None
            for kw in node.keywords:
                if kw.arg == "unique" and isinstance(kw.value, ast.Constant):
                    unique = kw.value.value
            blob = ast.get_source_segment(mig_path.read_text(), node) or ""
            columns_ok = "LOWER(artist)" in blob and "LOWER(album_name)" in blob
            if unique is True and columns_ok:
                anchors.unique_index = True
            elif unique is False:
                anchors.unique_index = False
            else:
                mismatched = True
        if not found:
            anchors.unique_index = False
            anchors.notes.append(
                "upgrade() does not create uq_artist_album_lowercase"
            )
        elif mismatched:
            anchors.unique_index = None
            anchors.gaps.append(
                "uq_artist_album_lowercase is not a unique index on "
                "LOWER(artist), LOWER(album_name). The model does not describe it."
            )

    db_tree = ast.parse(db_path.read_text())
    saw_factory = False
    for node in ast.walk(db_tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "AsyncSessionLocal" for t in node.targets):
            continue
        if not (isinstance(node.value, ast.Call) and _call_name(node.value.func) == "async_sessionmaker"):
            continue
        saw_factory = True
        flag = True
        for kw in node.value.keywords:
            if kw.arg == "autoflush" and isinstance(kw.value, ast.Constant):
                flag = bool(kw.value.value)
        anchors.autoflush = flag
    if not saw_factory:
        anchors.gaps.append(
            "AsyncSessionLocal is no longer async_sessionmaker(...). "
            "The autoflush assumption is unchecked."
        )

    writers: list[str] = []
    app = repo / "backend/app"
    for path in sorted(app.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "CD"
                    ):
                        rel = path.relative_to(repo)
                        writers.append(f"{rel}:{node.name}")
    allowed = {"backend/app/api/routes/cds.py:upload_csv"}
    extra = [w for w in writers if w not in allowed]
    if extra:
        anchors.gaps.append(
            "a CD row is constructed outside upload_csv, which this model "
            "does not cover: " + ", ".join(extra)
        )
    if not writers:
        anchors.gaps.append("no CD(...) construction found; upload_csv no longer inserts")

    anchors.runnable = (
        not anchors.gaps
        and anchors.unique_index is not None
        and anchors.autoflush is not None
        and anchors.lookup_before_add is not None
        and anchors.casefold
    )
    return anchors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_jar() -> Path:
    cache = Path.home() / ".cache" / "disc-scribe"
    cache.mkdir(parents=True, exist_ok=True)
    jar = cache / f"tla2tools-{TLC_VERSION}.jar"
    if jar.is_file() and _sha256(jar) == TLC_SHA256:
        return jar
    print(f"Downloading tla2tools {TLC_VERSION}")
    urllib.request.urlretrieve(TLC_URL, jar)
    got = _sha256(jar)
    if got != TLC_SHA256:
        jar.unlink(missing_ok=True)
        raise SystemExit(
            f"tla2tools {TLC_VERSION} sha256 mismatch: {got} != {TLC_SHA256}"
        )
    return jar


def _cfg(scenario: str, anchors: Anchors, invariant: str) -> str:
    infile = "TRUE" if scenario == "infile" else "FALSE"
    return textwrap.dedent(
        f"""\
        SPECIFICATION Spec
        CONSTANT InFileScenario = {infile}
        CONSTANT UniqueIndex = {"TRUE" if anchors.unique_index else "FALSE"}
        CONSTANT AutoFlush = {"TRUE" if anchors.autoflush else "FALSE"}
        CONSTANT LookupBeforeAdd = {"TRUE" if anchors.lookup_before_add else "FALSE"}
        INVARIANT {invariant}
        """
    )


@dataclass
class TlcResult:
    scenario: str
    invariant: str
    status: str  # pass, fail, error
    states: str
    output: str
    trace: str


def run_tlc(jar: Path, anchors: Anchors, scenario: str, invariant: str) -> TlcResult:
    LAST_RUN.mkdir(parents=True, exist_ok=True)
    cfg_name = f"{scenario}-{invariant}.cfg"
    cfg_path = LAST_RUN / cfg_name
    cfg_path.write_text(_cfg(scenario, anchors, invariant))
    # TLC resolves a config path from the spec directory. A copy with a
    # relative name next to the spec is the invocation that works.
    local_cfg = SPEC.with_name(cfg_name)
    local_cfg.write_text(cfg_path.read_text())
    meta = LAST_RUN / f"states-{scenario}-{invariant}"
    if meta.exists():
        shutil.rmtree(meta)
    cmd = [
        "java",
        "-Xmx512m",
        "-XX:+UseParallelGC",
        "-cp",
        str(jar),
        "tlc2.TLC",
        "-workers",
        "1",
        "-nowarning",
        "-config",
        cfg_name,
        "-metadir",
        str(meta),
        SPEC.name,
    ]
    proc = subprocess.run(
        cmd,
        cwd=SPEC.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    local_cfg.unlink(missing_ok=True)
    output = proc.stdout
    (LAST_RUN / f"{scenario}-{invariant}.out").write_text(output)
    trace = ""
    if "The behavior up to this point is:" in output:
        trace = output.split("The behavior up to this point is:", 1)[1].strip()
    states = ""
    match = re.search(r"(\d+) states generated, (\d+) distinct states found", output)
    if match:
        states = f"{match.group(2)} distinct states ({match.group(1)} generated)"
    if proc.returncode == 0 and "No error has been found" in output:
        status = "pass"
    elif "is violated" in output or "Deadlock" in output or "deadlock" in output:
        status = "fail"
    else:
        status = "error"
    return TlcResult(scenario, invariant, status, states, output, trace)


def _parse_map(line: str) -> dict[str, str]:
    body = line.split("=", 1)[1]
    found = re.findall(r'([A-Za-z0-9_]+)\s*\|->\s*("([^"]*)"|[A-Za-z0-9_]+)', body)
    return {name: (quoted or raw) for name, raw, quoted in found}


def explain_trace(trace: str) -> list[str]:
    """Turn a TLC state dump into upload_csv steps."""
    chunks = re.split(r"\n(?=State \d+:)", "\n" + trace)
    states = []
    for chunk in chunks:
        header = re.search(r"State \d+:\s*<([^>]+)>", chunk)
        if not header:
            continue
        label = header.group(1)
        action = "Init"
        if label.startswith("ProcessRow"):
            action = "ProcessRow"
        elif label.startswith("CommitImport"):
            action = "CommitImport"
        data: dict[str, dict[str, str]] = {}
        for key in ("phase", "idx", "aborted", "catalog"):
            found = re.search(rf"/\\ {key} = (\[[^\n]*\])", chunk)
            data[key] = _parse_map(found.group(0)) if found else {}
        states.append((action, data))
    if len(states) < 2:
        return []
    lines = []
    for index in range(1, len(states)):
        action, cur = states[index]
        _, prev = states[index - 1]
        if action == "ProcessRow":
            who = next(
                (
                    name
                    for name in cur["idx"]
                    if prev["idx"].get(name) != cur["idx"].get(name)
                ),
                "a session",
            )
            if prev["aborted"].get(who) == "FALSE" and cur["aborted"].get(who) == "TRUE":
                lines.append(
                    f"{who}: the next row's await db.execute autoflushes a pending "
                    "insert, uq_artist_album_lowercase rejects it, and the per-row "
                    "except records the error. That row is not db.add'd."
                )
            else:
                lines.append(
                    f"{who}: upload_csv reads the next row and runs the SELECT on "
                    "lower(artist), lower(album_name). The row is not committed yet, "
                    "so the other session cannot see it. Misses take the db.add branch."
                )
        elif action == "CommitImport":
            who = next(
                (
                    name
                    for name in cur["phase"]
                    if prev["phase"].get(name) != cur["phase"].get(name)
                ),
                "a session",
            )
            if cur["phase"].get(who) == "failed":
                lines.append(
                    f"{who}: await db.commit() raises. upload_csv does not catch it, "
                    "get_db rolls the session back, and every uncommitted album in "
                    "that file is dropped."
                )
            else:
                albums = ", ".join(
                    f"{key}={value}" for key, value in sorted(cur["catalog"].items())
                )
                lines.append(
                    f"{who}: await db.commit() stores this session's inserts "
                    f"(catalog {albums})."
                )
    return lines


def _print_trace(result: TlcResult) -> None:
    print(f"--- TLC {result.scenario} / {result.invariant} ({result.status}) ---")
    steps = explain_trace(result.trace)
    if steps:
        print("In upload_csv's words:")
        for number, step in enumerate(steps, 1):
            print(f"  {number}. {step}")
    if result.trace:
        print("TLC trace:")
        print(result.trace)
    elif result.status == "error":
        print(result.output[-2000:])


def shape_matches(anchors: Anchors) -> bool:
    return (
        anchors.unique_index is RECORDED_SHAPE["unique_index"]
        and anchors.autoflush is RECORDED_SHAPE["autoflush"]
        and anchors.lookup_before_add is RECORDED_SHAPE["lookup_before_add"]
    )


def main() -> int:
    print("CSV import dedup")
    print(f"Property: {PROPERTY_SENTENCE}")
    print(f"Harm: {HARM_SENTENCE}")
    print(f"Sync commit: {SYNC_COMMIT}")
    print(f"Tool: TLC from tla2tools {TLC_VERSION} (sha256 {TLC_SHA256})")
    print()

    if shutil.which("java") is None:
        print("Java is not on PATH. Install a JDK (this was run on OpenJDK 21) and rerun.")
        return 1
    if not SPEC.is_file():
        print(f"Missing spec {SPEC}")
        return 1

    anchors = analyze(REPO)
    print("Anchors read from the working tree:")
    print(f"  lookup before db.add in upload_csv: {anchors.lookup_before_add}")
    print(f"  func.lower on artist and album_name: {anchors.casefold}")
    print(f"  uq_artist_album_lowercase is unique: {anchors.unique_index}")
    print(f"  AsyncSessionLocal autoflush is not False: {anchors.autoflush}")
    for note in anchors.notes:
        print(f"  note: {note}")
    if anchors.gaps:
        print()
        print("The model does not describe this code. This is not a passing proof.")
        for gap in anchors.gaps:
            print(f"  - {gap}")
        print(
            "Update CsvImportDedup.tla from the new steps, then rerun. "
            "Move the sync commit only after the model matches the new code."
        )
        return 1

    jar = ensure_jar()
    if LAST_RUN.exists():
        shutil.rmtree(LAST_RUN)
    LAST_RUN.mkdir(parents=True)
    results: list[TlcResult] = []
    for scenario, invariant in RECORDED:
        results.append(run_tlc(jar, anchors, scenario, invariant))

    print()
    mismatches: list[str] = []
    for result in results:
        expected = RECORDED[(result.scenario, result.invariant)]
        mark = "ok" if result.status == expected else "DIFFERENT"
        print(
            f"  {result.scenario:12} {result.invariant:28} "
            f"{result.status:5} (recorded {expected}) [{mark}] {result.states}"
        )
        if result.status == "error":
            mismatches.append(
                f"{result.scenario}/{result.invariant} did not finish "
                "(TLC error — treat as a modeling or tool failure, not as a product pass)"
            )
        elif result.status != expected:
            mismatches.append(
                f"{result.scenario}/{result.invariant} is {result.status}, "
                f"recorded result is {expected}"
            )

    interesting = [
        r
        for r in results
        if r.status == "fail"
        and (r.scenario, r.invariant)
        in {
            ("concurrent", "NoExclusiveAlbumDropped"),
            ("concurrent", "ImportKeepsEveryValidRow"),
            ("concurrent", "NoDuplicateAlbums"),
            ("infile", "ImportKeepsEveryValidRow"),
        }
    ]
    for result in interesting:
        print()
        _print_trace(result)

    print()
    if not shape_matches(anchors):
        print(
            "The anchors are not the recorded shape "
            "(lookup before add, unique index on, autoflush left on). "
            "A TLC failure below is a bug in the code the model was built to catch. "
            "Do not weaken an invariant so this exits 0."
        )
        if mismatches or any(r.status == "fail" for r in results):
            print("Verdict: the check caught a break. Recorded finding no longer describes the result.")
            return 1
        print("Verdict: shape changed but every recorded invariant still has its old result. Read the diff. Do not move the sync commit until the model is updated to the new steps.")
        return 1

    if mismatches:
        print("Verdict: the result is not the recorded finding.")
        for item in mismatches:
            print(f"  - {item}")
        print(
            "If you can replay every step in upload_csv, it is a bug. "
            "If a step cannot happen in the code, the model is wrong. Fix the model, "
            "do not edit the invariant until it passes."
        )
        return 1

    print(
        "Verdict: matches the recorded finding at "
        f"{SYNC_COMMIT}. Uniqueness holds in this model. "
        "The overlapping upload still fails and can drop the rest of its file. "
        "Exit 0 means that finding is unchanged, not that the import is safe."
    )
    print(f"Logs and configs: {LAST_RUN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
