"""
DESTRUCTIVE: drops the application tables and enum types, and deletes the
'002' row from alembic_version so migrations can be re-run from scratch.

Run it only against a disposable development database - it commits, so the
deleted tables are gone. Use `scripts/verify_migrations.py` instead when you
just want to check that the migrations work.

Usage:
    CLEAN_DB_CONFIRM=yes python scripts/clean_db.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Safety gate: this script drops real tables, so require an explicit opt-in.
if os.getenv("CLEAN_DB_CONFIRM") != "yes":
    print("Refusing to run: this script DROPS all application tables.")
    print("Re-run with: CLEAN_DB_CONFIRM=yes python scripts/clean_db.py")
    sys.exit(1)

# Get database URL from environment
database_url = os.getenv('DATABASE_URL')
if not database_url:
    print("Error: DATABASE_URL not found in environment")
    sys.exit(1)

# Connect to database
engine = create_engine(database_url)

# Drop all tables and types in correct order
drop_commands = [
    "DROP TABLE IF EXISTS analyses CASCADE",
    "DROP TABLE IF EXISTS target_markets CASCADE",
    "DROP TABLE IF EXISTS evidence_documents CASCADE",
    "DROP TABLE IF EXISTS claims CASCADE",
    "DROP TABLE IF EXISTS formulations CASCADE",
    "DROP TABLE IF EXISTS ingredients CASCADE",
    "DROP TABLE IF EXISTS product_versions CASCADE",
    "DROP TABLE IF EXISTS products CASCADE",
    "DROP TYPE IF EXISTS analysisstatus CASCADE",
    "DROP TYPE IF EXISTS analysistype CASCADE",
    "DROP TYPE IF EXISTS verificationstatus CASCADE",
    "DROP TYPE IF EXISTS evidencetype CASCADE",
    "DROP TYPE IF EXISTS evidencestatus CASCADE",
    "DROP TYPE IF EXISTS claimtype CASCADE",
    "DROP TYPE IF EXISTS sourcetype CASCADE",
    "DROP TYPE IF EXISTS productcategory CASCADE",
    # Reset alembic version
    "DELETE FROM alembic_version WHERE version_num = '002'"
]

print("Cleaning database...")
with engine.connect() as conn:
    for cmd in drop_commands:
        try:
            conn.execute(text(cmd))
            print(f"✓ Executed: {cmd.split()[0]} {cmd.split()[2] if len(cmd.split()) > 2 else ''}")
        except Exception as e:
            print(f"Note: {cmd.split()[0]} - {str(e)[:50]}")

    conn.commit()
    print("\n✓ Database cleaned successfully!")
    print("\nNow run: alembic upgrade head")
