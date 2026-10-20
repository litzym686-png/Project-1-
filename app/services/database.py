"""Local SQLite storage for customers, appointments, service visits, and messages."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable

from app.models.customer import Customer
from app.models.service_history import ServiceHistoryEntry

SCHEMA_VERSION = 2
MAX_BACKUPS = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    vin TEXT NOT NULL UNIQUE,
    dealership TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    dealership TEXT NOT NULL,
    service_date TEXT NOT NULL,
    mileage INTEGER NOT NULL,
    service_type TEXT NOT NULL,
    reason TEXT,
    description TEXT,
    technician TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    dealership TEXT NOT NULL,
    assigned_agent TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0,
    UNIQUE (customer_id, scheduled_date, scheduled_time)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    dealership TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('outgoing', 'incoming')),
    sender TEXT NOT NULL,
    body TEXT NOT NULL,
    event TEXT NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""


class DatabaseError(RuntimeError):
    """Raised when the local database cannot be safely used."""


def default_database_path() -> Path:
    """Return the user-local database path outside the source tree."""
    return Path.home() / ".service-center" / "dashboard.db"


class Database:
    """Small sqlite3 wrapper; every operation commits before returning."""

    def __init__(self, path: str | Path | None = None, backup_dir: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_database_path()
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        if existed:
            self._verify_and_backup()
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Add newer columns to existing tables without touching existing rows."""
        additions = {
            "customers": (("current_mileage", "INTEGER"),),
            "appointments": (
                ("status", "TEXT NOT NULL DEFAULT 'scheduled'"),
                ("service_type", "TEXT"),
                ("reason", "TEXT"),
                ("mileage", "INTEGER"),
            ),
            "service_visits": (("appointment_id", "INTEGER"),),
        }
        for table, columns in additions.items():
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns:
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _connect(self) -> "_Connection":
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return _Connection(connection)

    def _verify_and_backup(self) -> None:
        """Refuse to touch an unreadable database and back up a healthy one."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            with closing(sqlite3.connect(self.path)) as source:
                result = source.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise sqlite3.DatabaseError("integrity check failed")
                target = self.backup_dir / f"dashboard-{stamp}.db"
                with closing(sqlite3.connect(target)) as destination:
                    source.backup(destination)
        except sqlite3.DatabaseError as error:
            preserved = self.backup_dir / f"dashboard-corrupt-{stamp}.db"
            shutil.copy2(self.path, preserved)
            raise DatabaseError(
                f"The database at {self.path} could not be read ({error}). "
                f"It was NOT changed; a copy was saved to {preserved}."
            ) from error
        backups = sorted(self.backup_dir.glob("dashboard-2*.db"))
        for old in backups[:-MAX_BACKUPS]:
            old.unlink()

    def seed_customers(self, customers: Iterable[Customer]) -> None:
        """Insert missing customers with stable IDs; never overwrite existing rows."""
        with self._connect() as connection:
            for customer in customers:
                exists = connection.execute(
                    "SELECT id, current_mileage FROM customers WHERE vin = ?",
                    (customer.vehicle.vin,),
                ).fetchone()
                if exists:
                    if exists["current_mileage"] is None:
                        # Only fill a missing value; prefer real recorded visit mileage.
                        latest = connection.execute(
                            "SELECT MAX(mileage) FROM service_visits WHERE customer_id = ?",
                            (exists["id"],),
                        ).fetchone()[0]
                        connection.execute(
                            "UPDATE customers SET current_mileage = ? WHERE id = ?",
                            (latest if latest is not None else customer.vehicle.current_mileage,
                             exists["id"]),
                        )
                    continue
                count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                connection.execute(
                    "INSERT INTO customers (id, name, vin, dealership, current_mileage)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (f"CUST-{count + 1:04d}", customer.customer_name,
                     customer.vehicle.vin, customer.dealership,
                     customer.vehicle.current_mileage),
                )

    def current_mileage_by_vin(self) -> dict[str, int]:
        """Return each vehicle's saved current mileage."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT vin, current_mileage FROM customers WHERE current_mileage IS NOT NULL"
            ).fetchall()
        return {row["vin"]: row["current_mileage"] for row in rows}

    def customer_id(self, vin: str) -> str:
        """Return the stable customer ID for a vehicle VIN."""
        with self._connect() as connection:
            row = connection.execute("SELECT id FROM customers WHERE vin = ?", (vin,)).fetchone()
        if row is None:
            raise DatabaseError(f"No customer record for VIN {vin}")
        return row["id"]

    def customers(self) -> tuple[dict[str, str], ...]:
        """Return stored customer identities ordered by ID."""
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM customers ORDER BY id").fetchall()
        return tuple(dict(row) for row in rows)

    def get_meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def save_visit(self, vin: str, dealership: str, entry: ServiceHistoryEntry, reason: str | None = None) -> None:
        """Save one completed visit for a customer's vehicle."""
        customer_id = self.customer_id(vin)
        with self._connect() as connection:
            # Link to the customer's open appointment on that date, never creating a new one.
            match = connection.execute(
                "SELECT id FROM appointments WHERE customer_id = ? AND scheduled_date = ?"
                " AND status = 'scheduled' ORDER BY scheduled_time LIMIT 1",
                (customer_id, entry.service_date.isoformat()),
            ).fetchone()
            appointment_id = match["id"] if match else None
            connection.execute(
                "INSERT INTO service_visits (customer_id, dealership, service_date, mileage,"
                " service_type, reason, description, technician, notes, created_at,"
                " appointment_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (customer_id, dealership, entry.service_date.isoformat(), entry.mileage,
                 entry.service_type, reason or entry.reason, entry.description,
                 entry.technician, entry.notes, datetime.now().isoformat(timespec="seconds"),
                 appointment_id),
            )
            if appointment_id is not None:
                connection.execute(
                    "UPDATE appointments SET status = 'completed' WHERE id = ?", (appointment_id,)
                )
            # Current mileage only ever moves up, so an older visit cannot lower it.
            connection.execute(
                "UPDATE customers SET current_mileage = ? WHERE id = ?"
                " AND (current_mileage IS NULL OR current_mileage < ?)",
                (entry.mileage, customer_id, entry.mileage),
            )

    def raise_mileage(self, vin: str, mileage: int) -> None:
        """Persist a higher current mileage on the customer's own record; never lower it."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE customers SET current_mileage = ? WHERE vin = ?"
                " AND (current_mileage IS NULL OR current_mileage < ?)",
                (mileage, vin, mileage),
            )

    def visits_by_vin(self) -> dict[str, tuple[ServiceHistoryEntry, ...]]:
        """Return saved visits per VIN in the order they were recorded."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT c.vin, v.* FROM service_visits v JOIN customers c ON c.id = v.customer_id"
                " ORDER BY v.id"
            ).fetchall()
        result: dict[str, list[ServiceHistoryEntry]] = {}
        for row in rows:
            result.setdefault(row["vin"], []).append(
                ServiceHistoryEntry(
                    date.fromisoformat(row["service_date"]), row["mileage"], row["service_type"],
                    row["notes"], row["description"], row["technician"], row["reason"],
                )
            )
        return {vin: tuple(entries) for vin, entries in result.items()}

    def save_appointment(self, vin: str, dealership: str, agent: str,
                         scheduled_date: date, scheduled_time: time, is_demo: bool = False,
                         service_type: str | None = None, reason: str | None = None,
                         mileage: int | None = None) -> None:
        customer_id = self.customer_id(vin)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO appointments (customer_id, dealership, assigned_agent,"
                " scheduled_date, scheduled_time, is_demo, service_type, reason, mileage)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(customer_id, scheduled_date, scheduled_time) DO UPDATE SET"
                " assigned_agent = excluded.assigned_agent, service_type = excluded.service_type,"
                " reason = excluded.reason, mileage = excluded.mileage",
                (customer_id, dealership, agent, scheduled_date.isoformat(),
                 scheduled_time.strftime("%H:%M"), int(is_demo), service_type, reason, mileage),
            )

    def appointment_rows(self) -> tuple[dict[str, object], ...]:
        """Return appointments joined to their customer identity."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT a.id, a.customer_id, c.name, c.vin, a.dealership, a.assigned_agent,"
                " a.scheduled_date, a.scheduled_time, a.is_demo, a.status, a.service_type,"
                " a.reason, a.mileage FROM appointments a"
                " JOIN customers c ON c.id = a.customer_id"
                " ORDER BY a.scheduled_date, a.scheduled_time"
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def save_message(self, vin: str, dealership: str, direction: str, sender: str,
                     body: str, event: str, simulated: bool = True) -> None:
        customer_id = self.customer_id(vin)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages (customer_id, dealership, direction, sender, body, event,"
                " simulated, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (customer_id, dealership, direction, sender, body, event, int(simulated),
                 datetime.now().isoformat(timespec="seconds")),
            )

    def message_rows(self, vin: str) -> tuple[dict[str, object], ...]:
        """Return one vehicle owner's messages, oldest first."""
        customer_id = self.customer_id(vin)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE customer_id = ? ORDER BY id", (customer_id,)
            ).fetchall()
        return tuple(dict(row) for row in rows)


class _Connection:
    """Context manager that commits on success, rolls back on error, and always closes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
