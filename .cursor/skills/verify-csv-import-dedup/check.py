#!/usr/bin/env python3
"""Check DiscVault CSV import dedup.

Reads upload_csv, _upsert_cd, the unique index, and the session factory,
sets the booleans in CsvImportDedup.tla from that code, and runs TLC.

Exit 0 means the working tree matches the recorded shape at the sync
commit: every album in a valid upload is stored once under the lowercased
key, including when another upload of that album is in progress, and the
broken variants below still fail.

Exit 1 means a violation, a missing strip, a missing guard, a TLC error,
or code the model does not describe. Read the verdict before changing
the model.
"""

from __future__ import annotations

import ast
import hashlib
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

TLC_VERSION = "1.7.4"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TLC_URL = (
    "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
)
SYNC_COMMIT = "d83ade882370659e38d706c190926719c02d88b8"

SKILL_DIR = Path(__file__).resolve().parent
REPO = SKILL_DIR.parents[2]
SPEC = SKILL_DIR / "CsvImportDedup.tla"
LAST_RUN = SKILL_DIR / "last-run"

# The code at SYNC_COMMIT. Do not edit these to make a run exit 0.
RECORDED_SHAPE = {
    "unique_index": True,
    "autoflush": True,
    "upsert": True,
    "ordered": True,
    "album_strip": True,
}
RECORDED = {
    ("concurrent", "NoDuplicateAlbums"): "pass",
    ("concurrent", "ImportKeepsEveryValidRow"): "pass",
    ("concurrent", "NoExclusiveAlbumDropped"): "pass",
    ("infile", "NoDuplicateAlbums"): "pass",
    ("infile", "ImportKeepsEveryValidRow"): "pass",
    ("infile", "NoExclusiveAlbumDropped"): "pass",
}

# Forced shapes. Each one must fail the way the invariant says, including
# on the fixed code. A pass here means the invariant was weakened.
VARIANTS = [
    {
        "name": "no ON CONFLICT (check-then-insert)",
        "upsert": False,
        "unique_index": True,
        "autoflush": True,
        "lookup_before_add": True,
        "ordered": True,
        "expect": {
            ("concurrent", "NoDuplicateAlbums"): "pass",
            ("concurrent", "ImportKeepsEveryValidRow"): "fail",
            ("concurrent", "NoExclusiveAlbumDropped"): "fail",
        },
    },
    {
        "name": "no ON CONFLICT and no unique index",
        "upsert": False,
        "unique_index": False,
        "autoflush": True,
        "lookup_before_add": True,
        "ordered": True,
        "expect": {
            ("concurrent", "NoDuplicateAlbums"): "fail",
        },
    },
    {
        "name": "upsert without the sort (opposite lock order)",
        "upsert": True,
        "unique_index": True,
        "autoflush": True,
        "lookup_before_add": True,
        "ordered": False,
        "expect": {
            ("concurrent", "ImportKeepsEveryValidRow"): "fail",
        },
    },
]

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
    upsert: bool | None = None
    ordered: bool = False
    album_strip: bool = False
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


def _calls_attr(fn: ast.AST, attr: str) -> bool:
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ):
            return True
    return False


def _calls_name(fn: ast.AST, name: str) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def _is_strip_call(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "strip"
    )


def _album_stripped(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if any(isinstance(t, ast.Name) and t.id == "album_name" for t in targets):
            return _is_strip_call(value)
    return False


def _sorted_by_lower(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sort"
        ):
            continue
        for kw in node.keywords:
            if kw.arg != "key":
                continue
            lowers = [
                n
                for n in ast.walk(kw.value)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "lower"
            ]
            if len(lowers) >= 2:
                return True
    return False


def _literal_lowers(fn: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(fn):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "literal_column"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        text = node.args[0].value.replace(" ", "").lower()
        if text == "lower(artist)":
            found.add("artist")
        elif text == "lower(album_name)":
            found.add("album_name")
    return found


def _add_guarded_by_existing(loop: ast.AST, add: ast.AST) -> bool:
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


def _pg_insert_sites(repo: Path) -> list[str]:
    sites: list[str] = []
    app = repo / "backend/app"
    for path in sorted(app.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                is_pg = (
                    isinstance(func, ast.Name) and func.id == "pg_insert"
                ) or (
                    isinstance(func, ast.Attribute) and func.attr == "pg_insert"
                )
                is_cd = (
                    isinstance(func, ast.Name)
                    and func.id == "CD"
                )
                if not is_pg and not is_cd:
                    continue
                if is_pg and not (
                    inner.args and isinstance(inner.args[0], ast.Name) and inner.args[0].id == "CD"
                ):
                    continue
                sites.append(f"{path.relative_to(repo)}:{node.name}")
    return sites


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

    anchors.album_strip = _album_stripped(upload)
    anchors.ordered = _sorted_by_lower(upload)
    if not anchors.ordered:
        anchors.notes.append(
            "upload_csv does not sort rows by the lowercased artist and album "
            "before writing, so two files can lock uq_artist_album_lowercase "
            "in opposite orders"
        )

    upsert_fn = _find_function(cds, "_upsert_cd")
    conflict_home: ast.AST | None = None
    if (
        isinstance(upsert_fn, ast.AsyncFunctionDef)
        and _calls_name(upload, "_upsert_cd")
        and _calls_attr(upsert_fn, "on_conflict_do_update")
    ):
        anchors.upsert = True
        conflict_home = upsert_fn
    elif _calls_attr(upload, "on_conflict_do_update"):
        anchors.upsert = True
        conflict_home = upload
    else:
        anchors.upsert = False
        anchors.notes.append(
            "upload_csv does not upsert on uq_artist_album_lowercase. "
            "TLC runs the check-then-insert protocol that ON CONFLICT replaced."
        )

    if anchors.upsert and conflict_home is not None:
        lowers = _literal_lowers(conflict_home)
        anchors.casefold = {"artist", "album_name"} <= lowers
        if not anchors.casefold:
            anchors.gaps.append(
                "the ON CONFLICT target is not lower(artist), lower(album_name), "
                "so it is not the same key as uq_artist_album_lowercase"
            )
        if not _calls_name(conflict_home, "pg_insert"):
            anchors.gaps.append(
                "the upsert does not call pg_insert(CD); the model does not describe it"
            )
    else:
        loops = [n for n in ast.walk(upload) if isinstance(n, ast.For)]
        dedup_loop = None
        for loop in loops:
            has_execute = any(_is_db_method(n, "execute") for n in ast.walk(loop))
            has_add = any(_is_db_method(n, "add") for n in ast.walk(loop))
            if has_execute and has_add:
                dedup_loop = loop
                break
        if dedup_loop is None:
            anchors.lookup_before_add = True
            anchors.casefold = True
            anchors.notes.append(
                "no SELECT-then-db.add loop either; LookupBeforeAdd stays true, "
                "which is the overlapping-upload failure this fix closed"
            )
        else:
            executes = [n for n in ast.walk(dedup_loop) if _is_db_method(n, "execute")]
            adds = [n for n in ast.walk(dedup_loop) if _is_db_method(n, "add")]
            first_execute = min(n.lineno for n in executes)
            first_add = min(n.lineno for n in adds)
            guarded = all(_add_guarded_by_existing(dedup_loop, add) for add in adds)
            anchors.lookup_before_add = first_execute < first_add and guarded
            fields = _func_lower_fields(dedup_loop)
            anchors.casefold = {"artist", "album_name"} <= fields
            if not anchors.casefold:
                anchors.gaps.append(
                    "the SELECT in upload_csv no longer calls func.lower on both "
                    "CD.artist and CD.album_name, so it is not the same key as "
                    "uq_artist_album_lowercase"
                )

    commits = [
        node
        for node in ast.walk(upload)
        if isinstance(node, ast.Await) and _is_db_method(node.value, "commit")
    ]
    if len(commits) != 1:
        anchors.gaps.append(
            f"upload_csv has {len(commits)} `await db.commit()` calls; the model "
            "describes exactly one, after the row loop"
        )
    else:
        commit = commits[0]
        if _enclosing(upload, commit, (ast.Try, ast.ExceptHandler)):
            anchors.gaps.append(
                "await db.commit() is inside try/except. A failed commit may no "
                "longer roll the whole file back. Update the model before treating "
                "a TLC result as a verdict on this code."
            )

    for fn in (upload, upsert_fn):
        if fn is None:
            continue
        segment = ast.get_source_segment(cds_src, fn) or ""
        for token, why in (
            ("with_for_update", "SELECT ... FOR UPDATE"),
            ("IntegrityError", "an IntegrityError handler"),
            ("isolation", "a non-default isolation level"),
        ):
            if token in segment:
                anchors.gaps.append(
                    f"{fn.name} mentions {token} ({why}). That step is not in the model."
                )

    mig_src = mig_path.read_text()
    mig = ast.parse(mig_src)
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
            blob = ast.get_source_segment(mig_src, node) or ""
            columns_ok = "LOWER(artist)" in blob and "LOWER(album_name)" in blob
            if unique is True and columns_ok:
                anchors.unique_index = True
            elif unique is False:
                anchors.unique_index = False
            else:
                mismatched = True
        if not found:
            anchors.unique_index = False
            anchors.notes.append("upgrade() does not create uq_artist_album_lowercase")
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
        if not (
            isinstance(node.value, ast.Call)
            and _call_name(node.value.func) == "async_sessionmaker"
        ):
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

    sites = _pg_insert_sites(repo)
    allowed = {
        "backend/app/api/routes/cds.py:_upsert_cd",
        "backend/app/api/routes/cds.py:upload_csv",
    }
    extra = [site for site in sites if site not in allowed]
    if extra:
        anchors.gaps.append(
            "a CD row is inserted outside upload_csv / _upsert_cd, which this "
            "model does not cover: " + ", ".join(extra)
        )
    if anchors.upsert and not any(site.endswith("_upsert_cd") or site.endswith("upload_csv") for site in sites):
        anchors.gaps.append("no pg_insert(CD) found; upload_csv no longer inserts")

    if anchors.lookup_before_add is None:
        anchors.lookup_before_add = True

    anchors.runnable = (
        not anchors.gaps
        and anchors.unique_index is not None
        and anchors.autoflush is not None
        and anchors.upsert is not None
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


def _cfg(flags: dict[str, bool], scenario: str, invariant: str) -> str:
    infile = "TRUE" if scenario == "infile" else "FALSE"
    return textwrap.dedent(
        f"""\
        SPECIFICATION Spec
        CONSTANT InFileScenario = {infile}
        CONSTANT UniqueIndex = {"TRUE" if flags["unique_index"] else "FALSE"}
        CONSTANT AutoFlush = {"TRUE" if flags["autoflush"] else "FALSE"}
        CONSTANT LookupBeforeAdd = {"TRUE" if flags["lookup_before_add"] else "FALSE"}
        CONSTANT Upsert = {"TRUE" if flags["upsert"] else "FALSE"}
        CONSTANT Ordered = {"TRUE" if flags["ordered"] else "FALSE"}
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
    label: str


def run_tlc(jar: Path, flags: dict[str, bool], scenario: str, invariant: str, label: str) -> TlcResult:
    LAST_RUN.mkdir(parents=True, exist_ok=True)
    cfg_name = f"{label}-{scenario}-{invariant}.cfg"
    cfg_path = LAST_RUN / cfg_name
    cfg_path.write_text(_cfg(flags, scenario, invariant))
    local_cfg = SPEC.with_name(cfg_name)
    local_cfg.write_text(cfg_path.read_text())
    meta = LAST_RUN / f"states-{label}-{scenario}-{invariant}"
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
    (LAST_RUN / f"{label}-{scenario}-{invariant}.out").write_text(output)
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
    return TlcResult(scenario, invariant, status, states, output, trace, label)


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
        for name in ("UpsertRow", "UpsertCommit", "ProcessRow", "CommitImport"):
            if name in label:
                action = name
                break
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
        who = next(
            (
                name
                for name in cur["idx"]
                if prev["idx"].get(name) != cur["idx"].get(name)
                or prev["phase"].get(name) != cur["phase"].get(name)
            ),
            "a session",
        )
        if action == "UpsertRow":
            if prev["aborted"].get(who) == "FALSE" and cur["aborted"].get(who) == "TRUE":
                lines.append(
                    f"{who}: _upsert_cd's INSERT ... ON CONFLICT has no matching "
                    "unique index, so the statement errors. The per-row except "
                    "records it and does not store the row. The transaction is aborted."
                )
            else:
                lines.append(
                    f"{who}: _upsert_cd inserts the next album, or updates it when "
                    "that lowercased key is already in this transaction or in cds. "
                    "The statement holds uq_artist_album_lowercase until commit."
                )
        elif action == "UpsertCommit":
            if cur["phase"].get(who) == "failed":
                lines.append(
                    f"{who}: await db.commit() raises. get_db rolls the session back, "
                    "and every uncommitted album in that file is dropped."
                )
            else:
                albums = ", ".join(
                    f"{key}={value}" for key, value in sorted(cur["catalog"].items())
                )
                lines.append(
                    f"{who}: await db.commit() publishes this session's inserts "
                    f"(catalog {albums})."
                )
        elif action == "ProcessRow":
            if prev["aborted"].get(who) == "FALSE" and cur["aborted"].get(who) == "TRUE":
                lines.append(
                    f"{who}: the next row's await db.execute autoflushes a pending "
                    "insert, uq_artist_album_lowercase rejects it, and the per-row "
                    "except records the error. That row is not db.add'd."
                )
            else:
                lines.append(
                    f"{who}: upload_csv reads the next row and runs the SELECT on "
                    "lower(artist), lower(album_name). A miss takes the db.add branch."
                )
        elif action == "CommitImport":
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
    print(f"--- TLC {result.label} {result.scenario} / {result.invariant} ({result.status}) ---")
    if "Deadlock" in result.output or "deadlock" in result.output:
        print(
            "TLC reached a deadlock: each upload holds one key of "
            "uq_artist_album_lowercase and is waiting for the other's key. "
            "That is the opposite lock order the sort in upload_csv removes."
        )
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
        and anchors.upsert is RECORDED_SHAPE["upsert"]
        and anchors.ordered is RECORDED_SHAPE["ordered"]
        and anchors.album_strip is RECORDED_SHAPE["album_strip"]
    )


def _flags_from(anchors: Anchors) -> dict[str, bool]:
    return {
        "unique_index": bool(anchors.unique_index),
        "autoflush": bool(anchors.autoflush),
        "lookup_before_add": bool(anchors.lookup_before_add),
        "upsert": bool(anchors.upsert),
        "ordered": bool(anchors.ordered),
    }


def _strip_counterexample() -> None:
    print()
    print("album_name is not stripped the way artist is.")
    print('Counterexample: "Abbey Road" and "Abbey Road " are different keys.')
    print(
        "uq_artist_album_lowercase is LOWER(artist), LOWER(album_name), and "
        "LOWER does not trim, so both rows would be stored."
    )
    print(
        "The model keys are already stripped, so TLC is not a verdict on this "
        "code. Strip album_name in upload_csv the same way artist is stripped."
    )


def main() -> int:
    print("CSV import dedup")
    print(f"Property: {PROPERTY_SENTENCE}")
    print(f"What it prevents: {HARM_SENTENCE}")
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
    print(f"  upsert on lower(artist), lower(album_name): {anchors.upsert}")
    print(f"  conflict target matches the index: {anchors.casefold}")
    print(f"  rows sorted by the lowercased key: {anchors.ordered}")
    print(f"  album_name is stripped: {anchors.album_strip}")
    print(f"  uq_artist_album_lowercase is unique: {anchors.unique_index}")
    print(f"  AsyncSessionLocal autoflush is not False: {anchors.autoflush}")
    for note in anchors.notes:
        print(f"  note: {note}")
    if not anchors.album_strip and not any("upload_csv is missing" in gap for gap in anchors.gaps):
        _strip_counterexample()
    if anchors.gaps or not anchors.album_strip:
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

    flags = _flags_from(anchors)
    results: list[TlcResult] = []
    for scenario, invariant in RECORDED:
        results.append(run_tlc(jar, flags, scenario, invariant, "code"))

    print()
    print("Code as it is:")
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
        if result.status == "fail":
            print()
            _print_trace(result)

    print()
    print("Broken variants (these must still fail):")
    variant_bad: list[str] = []
    for variant in VARIANTS:
        variant_flags = {
            "unique_index": variant["unique_index"],
            "autoflush": variant["autoflush"],
            "lookup_before_add": variant["lookup_before_add"],
            "upsert": variant["upsert"],
            "ordered": variant["ordered"],
        }
        print(f"  {variant['name']}:")
        for (scenario, invariant), expected in variant["expect"].items():
            result = run_tlc(
                jar,
                variant_flags,
                scenario,
                invariant,
                "variant-" + re.sub(r"[^a-z0-9]+", "-", variant["name"].lower()).strip("-"),
            )
            mark = "ok" if result.status == expected else "DIFFERENT"
            print(
                f"    {scenario:12} {invariant:28} "
                f"{result.status:5} (must {expected}) [{mark}] {result.states}"
            )
            if result.status == "error":
                variant_bad.append(
                    f"{variant['name']} / {invariant} did not finish (TLC error)"
                )
                _print_trace(result)
            elif result.status != expected:
                variant_bad.append(
                    f"{variant['name']} / {invariant} is {result.status}, "
                    f"and it must {expected}. The invariant was weakened, or the "
                    "broken protocol no longer matches the spec."
                )
                _print_trace(result)

    print()
    if variant_bad:
        print("Verdict: a broken variant did not fail the way it must.")
        for item in variant_bad:
            print(f"  - {item}")
        print("Do not weaken an invariant, and do not drop a variant, to make this exit 0.")
        return 1

    if not shape_matches(anchors):
        print(
            "The anchors are not the recorded shape "
            "(upsert on the lowercased key, rows sorted, album_name stripped, "
            "unique index on, autoflush left on)."
        )
        print(
            "A TLC failure above is the break those anchors describe. "
            "Do not weaken an invariant so this exits 0."
        )
        return 1

    if mismatches:
        print("Verdict: the result is not the recorded one for this code.")
        for item in mismatches:
            print(f"  - {item}")
        print(
            "If you can replay every step in upload_csv and _upsert_cd, it is a bug. "
            "If a step cannot happen in the code, the model is wrong. Fix the model. "
            "Do not edit an invariant until it passes."
        )
        return 1

    print(
        "Verdict: matches the code at "
        f"{SYNC_COMMIT}. Every valid album is stored once under the lowercased "
        "key, including while another upload of that album is in progress. "
        "The broken variants still fail."
    )
    print(f"Logs and configs: {LAST_RUN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
