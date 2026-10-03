"""
Verify the Alembic migration chain - safely.

How it is safe: PostgreSQL supports transactional DDL, so this script opens ONE
transaction, runs ``downgrade base`` and then ``upgrade head`` inside it, checks
the results, and finally ROLLS BACK. Nothing is ever committed: the database is
byte-for-byte unchanged afterwards, including any data in the tables.

This proves both directions:
  * a fresh (empty) database can be initialised by ``alembic upgrade head``
  * the downgrade path drops everything it created

Usage:
    python scripts/verify_migrations.py

DANGER NOTE: never run ``alembic downgrade`` against the configured database
without wrapping it in a transaction like this. Alembic connects with its own
connection, and a committed downgrade drops real tables.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED_TABLES = {
    # migration 001
    "users",
    "roles",
    "user_roles",
    "audit_logs",
    # migration 002
    "products",
    "product_versions",
    "ingredients",
    "formulations",
    "claims",
    "evidence_documents",
    "target_markets",
    "analyses",
    # migration 003
    "source_documents",
    "source_chunks",
    "chat_sessions",
    "chat_messages",
    # migration 005
    "patent_records",
    "patent_features",
    # migration 006
    "change_impacts",
    # migration 007
    "disclosures",
    # migration 008
    "reports",
    # migration 009
    "expert_reviews",
    "review_comments",
}

_failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -> {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _tables(conn) -> set:
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    ).all()
    return {row[0] for row in rows}


def main() -> int:
    settings = get_settings()

    # Engine created here (not imported from app.database) so we fully control
    # the transaction we are about to roll back.
    from sqlalchemy import create_engine

    engine = create_engine(settings.database_url, pool_pre_ping=True)

    print(f"Verifying migrations on {engine.url.host}/{engine.url.database}")
    print("All changes run inside one transaction that is rolled back.\n")

    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))

    # Read the head revision from the migration scripts themselves rather than
    # hard-coding it, so this check cannot rot every time a phase adds one.
    head_revision = ScriptDirectory.from_config(config).get_current_head()

    connection = engine.connect()
    transaction = connection.begin()

    try:
        # Snapshot what exists BEFORE we touch anything.
        before = _tables(connection)
        missing_before = EXPECTED_TABLES - before
        check(
            "configured database already has the migrated tables",
            not missing_before,
            f"missing: {sorted(missing_before)}"
            if missing_before
            else f"{len(EXPECTED_TABLES)} tables",
        )

        config.attributes["connection"] = connection

        command.downgrade(config, "base")
        after_downgrade = _tables(connection)
        check(
            "alembic downgrade base removes every migrated table",
            not (after_downgrade & EXPECTED_TABLES),
            f"left behind: {sorted(after_downgrade & EXPECTED_TABLES)}"
            if after_downgrade & EXPECTED_TABLES
            else "clean",
        )

        command.upgrade(config, "head")
        after_upgrade = _tables(connection)
        missing_after = EXPECTED_TABLES - after_upgrade
        check(
            "alembic upgrade head initialises a fresh database",
            not missing_after,
            f"missing: {sorted(missing_after)}"
            if missing_after
            else f"{len(EXPECTED_TABLES)} tables",
        )

        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all()
        check(
            f"alembic_version reports the head revision ({head_revision})",
            version == [head_revision],
            str(version),
        )

    except Exception as exc:  # noqa: BLE001 - report, then always roll back
        print(f"\nVERIFICATION FAILED: {exc}")
        return 1

    finally:
        transaction.rollback()
        after_rollback = _tables(connection)
        check(
            "rollback restored the database exactly as it was",
            after_rollback == before,
            f"before={len(before)} after={len(after_rollback)} tables",
        )
        connection.close()
        engine.dispose()
        print("\nTransaction rolled back - no changes were committed.")

    if _failures:
        print(f"\n{len(_failures)} migration check(s) failed: {_failures}")
        return 1

    print("Migration chain verified (fresh init + full downgrade + rollback).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
