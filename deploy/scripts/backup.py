"""SQLite online backup + JSON snapshots. Usage: backup.py {once,schedule,restore NAME}."""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

DATA = Path("/data")
BACKUPS = Path("/backups")
KEEP = 14


@contextmanager
def locked():
    # Shared across manual and scheduled containers. Also serializes restore.
    with (BACKUPS / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def check_database(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError(f"SQLite quick_check failed: {path}")


def snapshot(prune=True):
    # mode=ro fails if missing: never silently back up a newly created empty DB.
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    staging = Path(tempfile.mkdtemp(prefix=".partial-", dir=BACKUPS))
    try:
        with closing(sqlite3.connect((DATA / "powerk.db").as_uri() + "?mode=ro", uri=True,
                                     timeout=30)) as source:
            with closing(sqlite3.connect(staging / "powerk.db")) as target:
                source.backup(target, pages=256, sleep=0.1)
        # The app replaces JSON atomically, so one read sees one complete version.
        raw = (DATA / "powerk.json").read_bytes()
        json.loads(raw)
        (staging / "powerk.json").write_bytes(raw)
        check_database(staging / "powerk.db")
        staging.rename(BACKUPS / name)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if prune:
        snapshots = sorted(p for p in BACKUPS.iterdir()
                           if p.is_dir() and p.name.endswith("Z")
                           and (p / "powerk.db").is_file() and (p / "powerk.json").is_file())
        for old in snapshots[:-KEEP]:
            shutil.rmtree(old)
    print(f"Backup complete: {name}", flush=True)


def restore(name):
    if Path(name).name != name or name in (".", ".."):
        raise ValueError("Use one snapshot directory name, not a path")
    source = BACKUPS / name
    if source.is_symlink():
        raise ValueError("Snapshot must not be a symlink")
    check_database(source / "powerk.db")
    raw = (source / "powerk.json").read_bytes()
    json.loads(raw)
    # Caller MUST stop both services first. Stage on /data for atomic file replaces.
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=DATA))
    try:
        shutil.copyfile(source / "powerk.db", staging / "powerk.db")
        (staging / "powerk.json").write_bytes(raw)
        existing = [(DATA / filename).exists() for filename in ("powerk.db", "powerk.json")]
        if any(existing):
            if not all(existing):
                raise RuntimeError("Partial current data: preserve/repair it before restoring")
            snapshot(prune=False)  # Preserve a rollback snapshot before overwriting.
        for suffix in ("-wal", "-shm", "-journal"):
            (DATA / ("powerk.db" + suffix)).unlink(missing_ok=True)
        for filename in ("powerk.db", "powerk.json"):
            (staging / filename).replace(DATA / filename)
    finally:
        shutil.rmtree(staging)
    print(f"Restored {name}; pre-restore snapshot retained when data existed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "schedule", "restore"))
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    if args.command == "restore" and not args.name:
        parser.error("restore requires NAME")
    if args.command == "schedule":
        while True:
            try:
                with locked():
                    snapshot()
            except Exception as error:
                print(f"BACKUP FAILED: {error}", flush=True)
            # First backup at startup, then daily. Failures retry the following day.
            time.sleep(86400)
    else:
        with locked():
            restore(args.name) if args.command == "restore" else snapshot()


if __name__ == "__main__":
    main()
