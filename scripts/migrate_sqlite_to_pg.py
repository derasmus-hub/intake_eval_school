#!/usr/bin/env python3
"""Migrate data from SQLite to PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_pg.py [--sqlite-path PATH] [--pg-url URL]

If not specified, reads DATABASE_PATH and DATABASE_URL from .env file.

This script:
1. Connects to the existing SQLite database
2. Connects to the PostgreSQL database (schema must already exist via Alembic)
3. Copies all rows from each table, preserving IDs
4. Resets PostgreSQL SERIAL sequences to max(id)+1 for each table
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Tables in dependency order (parents before children)
TABLES = [
    "organizations",
    "org_invites",
    "users",
    "learner_profiles",
    "lessons",
    "lesson_skill_tags",
    "progress",
    "assessments",
    "cefr_history",
    "learning_paths",
    "achievements",
    "vocabulary_cards",
    "learning_points",
    "recall_sessions",
    "daily_challenges",
    "xp_log",
    "game_scores",
    "sessions",
    "session_skill_observations",
    "session_students",
    "teacher_availability",
    "teacher_weekly_windows",
    "teacher_availability_overrides",
    "teacher_invites",
    "learning_plans",
    "lesson_artifacts",
    "next_quizzes",
    "quiz_attempts",
    "quiz_attempt_items",
    "writing_submissions",
    "learning_dna",
    "l1_interference_tracking",
    "pre_class_warmups",
]


async def migrate(sqlite_path: str, pg_url: str):
    import aiosqlite
    import asyncpg

    print(f"SQLite source: {sqlite_path}")
    print(f"PostgreSQL target: {pg_url.split('@')[-1]}")
    print()

    # Connect to both databases
    sqlite_db = await aiosqlite.connect(sqlite_path)
    sqlite_db.row_factory = aiosqlite.Row
    pg_pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=5)

    total_rows = 0

    async with pg_pool.acquire() as pg_conn:
        for table in TABLES:
            # Check if table exists in SQLite
            cursor = await sqlite_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not await cursor.fetchone():
                print(f"  SKIP {table} (not in SQLite)")
                continue

            # Get all rows from SQLite
            cursor = await sqlite_db.execute(f"SELECT * FROM {table}")
            rows = await cursor.fetchall()

            if not rows:
                print(f"  {table}: 0 rows (empty)")
                continue

            # Get column names
            columns = [description[0] for description in cursor.description]

            # Delete existing data in Postgres (for idempotent re-runs)
            await pg_conn.execute(f"DELETE FROM {table}")

            # Insert rows in batches
            inserted = 0
            batch_size = 500

            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                # Build parameterized INSERT
                placeholders = ", ".join(
                    f"${j + 1}" for j in range(len(columns))
                )
                col_names = ", ".join(columns)
                insert_sql = (
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
                )

                for row in batch:
                    values = [row[col] for col in columns]
                    try:
                        await pg_conn.execute(insert_sql, *values)
                        inserted += 1
                    except Exception as e:
                        print(f"  ERROR inserting into {table}: {e}")
                        print(f"    Row: {dict(zip(columns, values))}")
                        raise

            # Reset sequence if table has an 'id' column
            if "id" in columns:
                max_id = await pg_conn.fetchval(
                    f"SELECT COALESCE(MAX(id), 0) FROM {table}"
                )
                seq_name = f"{table}_id_seq"
                try:
                    await pg_conn.execute(
                        f"SELECT setval('{seq_name}', $1, true)", max(max_id, 1)
                    )
                except Exception:
                    # Sequence might not exist if table doesn't use SERIAL
                    pass

            total_rows += inserted
            print(f"  {table}: {inserted} rows migrated")

    await sqlite_db.close()
    await pg_pool.close()

    print()
    print(f"Migration complete: {total_rows} total rows across {len(TABLES)} tables")

    # Also migrate alembic_version
    print()
    print("Migrating alembic_version...")
    sqlite_db2 = await aiosqlite.connect(sqlite_path)
    sqlite_db2.row_factory = aiosqlite.Row
    pg_pool2 = await asyncpg.create_pool(pg_url, min_size=1, max_size=2)

    async with pg_pool2.acquire() as pg_conn2:
        cursor = await sqlite_db2.execute("SELECT version_num FROM alembic_version")
        rows = await cursor.fetchall()
        if rows:
            await pg_conn2.execute("DELETE FROM alembic_version")
            for row in rows:
                await pg_conn2.execute(
                    "INSERT INTO alembic_version (version_num) VALUES ($1)",
                    row["version_num"],
                )
            print(f"  alembic_version: {len(rows)} entries migrated")
        else:
            print("  alembic_version: no entries to migrate")

    await sqlite_db2.close()
    await pg_pool2.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate data from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("DATABASE_PATH", "intake_eval.db"),
        help="Path to SQLite database (default: DATABASE_PATH from .env)",
    )
    parser.add_argument(
        "--pg-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL URL (default: DATABASE_URL from .env)",
    )
    args = parser.parse_args()

    if not args.pg_url:
        print("ERROR: PostgreSQL URL not provided.")
        print("Set DATABASE_URL in .env or pass --pg-url")
        sys.exit(1)

    if not Path(args.sqlite_path).exists():
        print(f"ERROR: SQLite database not found: {args.sqlite_path}")
        sys.exit(1)

    asyncio.run(migrate(args.sqlite_path, args.pg_url))


if __name__ == "__main__":
    main()
