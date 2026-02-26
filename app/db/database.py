"""Database abstraction layer supporting both SQLite (aiosqlite) and PostgreSQL (asyncpg).

Backend is selected via the DATABASE_URL setting:
  - starts with "postgresql://" → asyncpg
  - absent / empty             → aiosqlite (uses DATABASE_PATH)

The PostgreSQL wrapper transparently converts:
  - ? placeholders → $1, $2, … (positional)
  - cursor.lastrowid → RETURNING id
  - Row access by column name (dict-like)
"""

import re
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, date
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _is_postgres() -> bool:
    return settings.database_url.startswith("postgresql://")


# ── SQLite helpers (original behaviour) ───────────────────────────────

async def _connect_sqlite():
    import aiosqlite
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db


# ── PostgreSQL wrapper ────────────────────────────────────────────────

_pg_pool = None


async def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        import asyncpg
        _pg_pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
        )
    return _pg_pool


def _sqlite_compat(value):
    """Convert asyncpg-native types to SQLite-compatible Python types.

    SQLite always returns timestamps as strings; asyncpg returns datetime
    objects.  Converting here keeps every route working unchanged.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


class PgRow:
    """Wraps an asyncpg Record to support dict-style access by column name.

    Supports dict(row), row["col"], row.keys(), row.items(), etc.
    Mimics sqlite3.Row interface: keys() + __getitem__ enable dict(row).
    Automatically converts datetime → ISO string to match SQLite behaviour.
    """

    __slots__ = ("_record",)

    def __init__(self, record):
        self._record = record

    def __getitem__(self, key):
        return _sqlite_compat(self._record[key])

    def __contains__(self, key):
        return key in self._record.keys()

    def __len__(self):
        return len(self._record)

    def keys(self):
        return self._record.keys()

    def values(self):
        return [_sqlite_compat(v) for v in self._record.values()]

    def items(self):
        return {k: _sqlite_compat(self._record[k]) for k in self._record.keys()}.items()

    def get(self, key, default=None):
        try:
            return _sqlite_compat(self._record[key])
        except (KeyError, IndexError):
            return default


def _to_pg_row(record):
    """Convert asyncpg Record to PgRow, or None."""
    if record is None:
        return None
    return PgRow(record)


# Regex to replace ? placeholders with $1, $2, … while skipping quoted strings
_PARAM_RE = re.compile(r"'[^']*'|(\?)")


def _convert_placeholders(sql: str) -> str:
    """Replace ? with $1, $2, … for asyncpg, skipping ?s inside string literals."""
    counter = [0]

    def _replacer(match):
        if match.group(1) is None:
            # Matched a quoted string — leave unchanged
            return match.group(0)
        counter[0] += 1
        return f"${counter[0]}"

    return _PARAM_RE.sub(_replacer, sql)


# Regex to rewrite SQLite datetime() calls to PostgreSQL equivalents
# Matches: datetime('now'), datetime('now', '-7 days'), datetime('now', '+1 day'), etc.
_DATETIME_NOW_RE = re.compile(
    r"datetime\(\s*'now'\s*\)",
    re.IGNORECASE,
)
_DATETIME_OFFSET_RE = re.compile(
    r"datetime\(\s*'now'\s*,\s*'([+-]?\d+)\s+(day|days|hour|hours|minute|minutes|second|seconds|month|months|year|years)'\s*\)",
    re.IGNORECASE,
)


def _convert_datetime_funcs(sql: str) -> str:
    """Rewrite SQLite datetime('now', ...) to PostgreSQL NOW() + INTERVAL."""
    # Handle datetime('now', 'offset') first (more specific)
    def _offset_replacer(match):
        amount = match.group(1)
        unit = match.group(2).lower()
        # Normalize plural
        if not unit.endswith("s"):
            unit += "s"
        return f"(NOW() + INTERVAL '{amount} {unit}')"

    sql = _DATETIME_OFFSET_RE.sub(_offset_replacer, sql)
    # Handle simple datetime('now')
    sql = _DATETIME_NOW_RE.sub("NOW()", sql)
    return sql

_ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _coerce_arg_to_datetime(arg):
    """Try converting an ISO datetime string to a naive datetime for asyncpg."""
    if isinstance(arg, str) and _ISO_DT_RE.match(arg):
        try:
            dt = datetime.fromisoformat(arg)
            return dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            pass
    return arg


def _is_insert(sql: str) -> bool:
    """Check if an SQL statement is an INSERT (for RETURNING id)."""
    return sql.lstrip().upper().startswith("INSERT")


class PgCursor:
    """Mimics aiosqlite cursor for the result of execute()."""

    __slots__ = ("_rows", "_lastrowid", "_idx")

    def __init__(self, rows=None, lastrowid=None):
        self._rows = rows or []
        self._lastrowid = lastrowid
        self._idx = 0

    @property
    def lastrowid(self):
        return self._lastrowid

    async def fetchone(self):
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return _to_pg_row(row)
        return None

    async def fetchall(self):
        remaining = self._rows[self._idx:]
        self._idx = len(self._rows)
        return [PgRow(r) for r in remaining]


class PgConnection:
    """Wraps an asyncpg connection to present an aiosqlite-compatible interface.

    Supports:
      - execute(sql, params) with ? placeholders
      - cursor.lastrowid via RETURNING id
      - commit() / close()
      - fetchone() / fetchall() on returned cursor
    """

    def __init__(self, conn):
        self._conn = conn
        self._tx = None

    async def execute(self, sql: str, params=None):
        pg_sql = _convert_placeholders(sql)
        pg_sql = _convert_datetime_funcs(pg_sql)
        args = tuple(params) if params else ()

        try:
            return await self._execute_inner(pg_sql, args)
        except Exception as exc:
            # asyncpg raises DataError when a string is passed for a timestamp
            # column.  Retry once with ISO-datetime strings coerced to datetime.
            if "DataError" in type(exc).__name__ and args:
                coerced = tuple(_coerce_arg_to_datetime(a) for a in args)
                if coerced != args:
                    return await self._execute_inner(pg_sql, coerced)
            raise

    async def _execute_inner(self, pg_sql: str, args: tuple):
        if _is_insert(pg_sql):
            # Append RETURNING id if not already present
            if "RETURNING" not in pg_sql.upper():
                pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
            row = await self._conn.fetchrow(pg_sql, *args)
            lastrowid = row["id"] if row else None
            return PgCursor(rows=[row] if row else [], lastrowid=lastrowid)
        else:
            # SELECT or UPDATE/DELETE
            stripped = pg_sql.lstrip().upper()
            if stripped.startswith("SELECT") or "RETURNING" in stripped:
                rows = await self._conn.fetch(pg_sql, *args)
                return PgCursor(rows=rows)
            else:
                await self._conn.execute(pg_sql, *args)
                return PgCursor()

    async def commit(self):
        # asyncpg uses explicit transactions; with autocommit semantics,
        # each statement is auto-committed. No-op here.
        pass

    async def close(self):
        # No-op: pool release is handled by get_db() dependency
        pass


# ── Public API ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator:
    """FastAPI dependency that yields a database connection and closes it after the request."""
    if _is_postgres():
        pool = await _get_pg_pool()
        conn = await pool.acquire()
        pg_conn = PgConnection(conn)
        try:
            yield pg_conn
        finally:
            await pool.release(conn)
    else:
        db = await _connect_sqlite()
        try:
            yield db
        finally:
            await db.close()


def _run_alembic_upgrade():
    """Run Alembic migrations to head (synchronous — called once at startup)."""
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    if _is_postgres():
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    else:
        alembic_cfg.set_main_option(
            "sqlalchemy.url", f"sqlite:///{settings.database_path}"
        )

    command.upgrade(alembic_cfg, "head")


async def init_db():
    if _is_postgres():
        logger.info("Using PostgreSQL backend: %s", settings.database_url.split("@")[-1])
    else:
        # Ensure parent directory exists (for Docker volume mounts)
        db_path = Path(settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Using SQLite backend: %s", settings.database_path)

    # Alembic handles all schema creation and migrations
    _run_alembic_upgrade()


async def close_db():
    """Shutdown hook — close the connection pool if using PostgreSQL."""
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None
