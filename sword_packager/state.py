"""Persistent state for sword-packager deposits.

Keeps a SQLite-backed mapping from (csv_path, row_number) to the IRIs
returned in the deposit receipt. Required for any CRUD command, since
the IRIs aren't recoverable from the CSV alone.

Default location is ``~/.sword-packager/state.db``. Override with
``--state-file`` on the CLI or by passing a path to ``StateStore``.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sword_packager.receipt import DepositReceipt

DEFAULT_STATE_PATH = Path.home() / ".sword-packager" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS deposits (
    csv_path        TEXT NOT NULL,
    row_number      INTEGER NOT NULL,
    collection_url  TEXT NOT NULL,
    package_format  TEXT NOT NULL,
    se_iri          TEXT,
    em_iri          TEXT,
    stmt_iri        TEXT,
    atom_id         TEXT,
    title           TEXT,
    treatment       TEXT,
    last_status     INTEGER,
    last_updated    TEXT NOT NULL,
    PRIMARY KEY (csv_path, row_number)
);
"""


@dataclass
class DepositRecord:
    """A row from the ``deposits`` table."""

    csv_path: str
    row_number: int
    collection_url: str
    package_format: str
    se_iri: str | None
    em_iri: str | None
    stmt_iri: str | None
    atom_id: str | None
    title: str | None
    treatment: str | None
    last_status: int | None
    last_updated: str


class StateStore:
    """Thin wrapper around SQLite with the deposits schema."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_STATE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert(
        self,
        *,
        csv_path: Path,
        row_number: int,
        collection_url: str,
        package_format: str,
        receipt: DepositReceipt | None,
        status_code: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        # ``str(Path(...))`` would keep the user's exact spelling; resolving
        # makes equality stable across cwd differences when re-running.
        csv_key = str(Path(csv_path).resolve())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deposits (
                    csv_path, row_number, collection_url, package_format,
                    se_iri, em_iri, stmt_iri, atom_id, title, treatment,
                    last_status, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(csv_path, row_number) DO UPDATE SET
                    collection_url = excluded.collection_url,
                    package_format = excluded.package_format,
                    se_iri         = COALESCE(excluded.se_iri, deposits.se_iri),
                    em_iri         = COALESCE(excluded.em_iri, deposits.em_iri),
                    stmt_iri       = COALESCE(excluded.stmt_iri, deposits.stmt_iri),
                    atom_id        = COALESCE(excluded.atom_id, deposits.atom_id),
                    title          = COALESCE(excluded.title, deposits.title),
                    treatment      = COALESCE(excluded.treatment, deposits.treatment),
                    last_status    = excluded.last_status,
                    last_updated   = excluded.last_updated
                """,
                (
                    csv_key,
                    row_number,
                    collection_url,
                    package_format,
                    receipt.se_iri if receipt else None,
                    receipt.em_iri if receipt else None,
                    receipt.stmt_iri if receipt else None,
                    receipt.atom_id if receipt else None,
                    receipt.title if receipt else None,
                    receipt.treatment if receipt else None,
                    status_code,
                    now,
                ),
            )

    def get(self, csv_path: Path, row_number: int) -> DepositRecord | None:
        csv_key = str(Path(csv_path).resolve())
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM deposits WHERE csv_path = ? AND row_number = ?",
                (csv_key, row_number),
            )
            row = cur.fetchone()
        return _row_to_record(row) if row else None

    def list_for_csv(self, csv_path: Path) -> list[DepositRecord]:
        csv_key = str(Path(csv_path).resolve())
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM deposits WHERE csv_path = ? ORDER BY row_number",
                (csv_key,),
            )
            return [_row_to_record(r) for r in cur.fetchall()]

    def list_all(self) -> list[DepositRecord]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM deposits ORDER BY csv_path, row_number"
            )
            return [_row_to_record(r) for r in cur.fetchall()]


def _row_to_record(row: sqlite3.Row) -> DepositRecord:
    return DepositRecord(
        csv_path=row["csv_path"],
        row_number=row["row_number"],
        collection_url=row["collection_url"],
        package_format=row["package_format"],
        se_iri=row["se_iri"],
        em_iri=row["em_iri"],
        stmt_iri=row["stmt_iri"],
        atom_id=row["atom_id"],
        title=row["title"],
        treatment=row["treatment"],
        last_status=row["last_status"],
        last_updated=row["last_updated"],
    )
