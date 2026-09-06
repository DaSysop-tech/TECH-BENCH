"""SQLite persistence for the bench. Disabled in tests unless TECHBENCH_PERSIST=1."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import defaultdict, deque
from pathlib import Path

from techbench.models import JournalEntry, Machine, MachineSnapshot, ScanDelta, TechNote, TelemetrySample
from techbench.security import ROOT

DB_DEFAULT = ROOT / "data" / "bench.sqlite"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def enabled() -> bool:
    return os.environ.get("TECHBENCH_PERSIST", "1") != "0"


def db_path() -> Path:
    raw = os.environ.get("TECHBENCH_DB", "").strip()
    return Path(raw) if raw else DB_DEFAULT


def init_db() -> None:
    global _conn
    close()
    if not enabled():
        return
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kv (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS remediations (
            machine_id TEXT NOT NULL,
            finding_id TEXT NOT NULL,
            PRIMARY KEY (machine_id, finding_id)
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS remotes (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS overrides (
            machine_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            ts REAL NOT NULL,
            body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            ts REAL NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            ts REAL NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry (
            machine_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        );
        """
    )
    conn.commit()
    _conn = conn


def close() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except sqlite3.Error:
            pass
        _conn = None


def _db() -> sqlite3.Connection | None:
    return _conn if enabled() else None


def save_remediation(machine_id: str, finding_id: str) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT OR IGNORE INTO remediations(machine_id, finding_id) VALUES (?, ?)",
            (machine_id, finding_id),
        )
        conn.commit()


def clear_sim_ticket(machine_id: str) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute("DELETE FROM remediations WHERE machine_id = ?", (machine_id,))
        conn.execute("DELETE FROM overrides WHERE machine_id = ?", (machine_id,))
        conn.commit()


def save_override(machine_id: str, snapshot: MachineSnapshot) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO overrides(machine_id, payload) VALUES (?, ?)",
            (machine_id, snapshot.model_dump_json()),
        )
        conn.commit()


def save_token(token: str, machine_id: str) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO tokens(token, machine_id) VALUES (?, ?)",
            (token, machine_id),
        )
        conn.commit()


def save_remote(machine: Machine) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO remotes(id, payload) VALUES (?, ?)",
            (machine.id, machine.model_dump_json()),
        )
        conn.commit()


def save_note(note: TechNote) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO notes(id, machine_id, ts, body) VALUES (?, ?, ?, ?)",
            (note.id, note.machine_id, note.ts, note.body),
        )
        conn.commit()


def save_journal(entry: JournalEntry) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT INTO journal(machine_id, ts, payload) VALUES (?, ?, ?)",
            (entry.machine_id, entry.ts, entry.model_dump_json()),
        )
        conn.commit()


def save_scan(machine_id: str, delta: ScanDelta) -> None:
    conn = _db()
    if conn is None:
        return
    with _lock:
        conn.execute(
            "INSERT INTO scans(machine_id, ts, payload) VALUES (?, ?, ?)",
            (machine_id, delta.ts, delta.model_dump_json()),
        )
        conn.commit()


def save_telemetry(machine_id: str, samples: list[TelemetrySample]) -> None:
    conn = _db()
    if conn is None:
        return
    tail = [s.model_dump(mode="json") for s in samples[-120:]]
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO telemetry(machine_id, payload) VALUES (?, ?)",
            (machine_id, json.dumps(tail)),
        )
        conn.commit()


def load_all() -> dict:
    empty = {
        "remediations": {},
        "overrides": {},
        "tokens": {},
        "remotes": [],
        "notes": {},
        "journal": {},
        "scans": {},
        "telemetry": {},
    }
    conn = _db()
    if conn is None:
        return empty
    with _lock:
        remediations: dict[str, set[str]] = defaultdict(set)
        for mid, fid in conn.execute("SELECT machine_id, finding_id FROM remediations"):
            remediations[mid].add(fid)
        overrides = {}
        for mid, payload in conn.execute("SELECT machine_id, payload FROM overrides"):
            overrides[mid] = MachineSnapshot.model_validate_json(payload)
        tokens = {t: m for t, m in conn.execute("SELECT token, machine_id FROM tokens")}
        remotes = []
        for _, payload in conn.execute("SELECT id, payload FROM remotes"):
            remotes.append(Machine.model_validate_json(payload))
        notes: dict[str, list[TechNote]] = defaultdict(list)
        for _id, mid, ts, body in conn.execute(
            "SELECT id, machine_id, ts, body FROM notes ORDER BY ts"
        ):
            notes[mid].append(TechNote(id=_id, machine_id=mid, ts=ts, body=body))
        journal: dict[str, deque] = defaultdict(lambda: deque(maxlen=80))
        for mid, _ts, payload in conn.execute(
            "SELECT machine_id, ts, payload FROM journal ORDER BY id"
        ):
            journal[mid].append(JournalEntry.model_validate_json(payload))
        scans: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        for mid, _ts, payload in conn.execute(
            "SELECT machine_id, ts, payload FROM scans ORDER BY id"
        ):
            scans[mid].append(ScanDelta.model_validate_json(payload))
        telemetry: dict[str, list[TelemetrySample]] = {}
        for mid, payload in conn.execute("SELECT machine_id, payload FROM telemetry"):
            telemetry[mid] = [TelemetrySample.model_validate(s) for s in json.loads(payload)]
    return {
        "remediations": dict(remediations),
        "overrides": overrides,
        "tokens": tokens,
        "remotes": remotes,
        "notes": dict(notes),
        "journal": {k: deque(v, maxlen=80) for k, v in journal.items()},
        "scans": {k: deque(v, maxlen=20) for k, v in scans.items()},
        "telemetry": telemetry,
    }
