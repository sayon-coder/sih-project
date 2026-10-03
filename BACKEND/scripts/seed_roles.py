"""
Script to seed initial roles into the database.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Role, RoleName


def seed_roles():
    """Seed default roles into the database."""
    db: Session = SessionLocal()

    try:
        # Check if roles already exist
        existing_roles = db.query(Role).count()
        if existing_roles > 0:
            print("Roles already seeded. Skipping...")
            return

        # Create default roles
        roles = [
            Role(
                name=RoleName.ADMIN,
                description="Administrator with full access to all features"
            ),
            Role(
                name=RoleName.RESEARCHER,
                description="Can create and manage products, run analyses, and generate reports"
            ),
            Role(
                name=RoleName.EXPERT,
                description="Can review and validate analyses, provide expert feedback"
            ),
            Role(
                name=RoleName.VIEWER,
                description="Can view products and reports but cannot make changes"
            ),
        ]

        for role in roles:
            db.add(role)

        db.commit()
        print(f"Successfully seeded {len(roles)} roles:")
        for role in roles:
            print(f"  - {role.name.value}: {role.description}")

    except Exception as e:
        print(f"Error seeding roles: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding roles...")
    seed_roles()
    print("Done!")
