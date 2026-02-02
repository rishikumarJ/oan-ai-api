#!/usr/bin/env python3
"""
Setup Users Script

Creates the users table and inserts test users for authentication.

Usage:
    python scripts/setup_users.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import bcrypt
from sqlalchemy import text

from dotenv import load_dotenv
load_dotenv()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


async def setup_users():
    """Create users table and insert test users"""
    from app.database import engine

    # Test users - email and password
    test_users = [
        ("test1@ati.com", "ati@123"),
        ("test2@ati.com", "ati@123"),
        ("test3@ati.com", "ati@123"),
        ("test4@ati.com", "ati@123"),
        ("test5@ati.com", "ati@123"),
    ]

    async with engine.begin() as conn:
        # Create users table if not exists
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                hashed_password VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("✅ Users table created (or already exists)")

        # Create index on email
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
        """))
        print("✅ Index on email created")

        # Insert test users
        for email, password in test_users:
            hashed_pw = hash_password(password)
            try:
                await conn.execute(
                    text("""
                        INSERT INTO users (email, hashed_password, is_active)
                        VALUES (:email, :hashed_password, TRUE)
                        ON CONFLICT (email) DO UPDATE SET
                            hashed_password = :hashed_password,
                            updated_at = NOW()
                    """),
                    {"email": email, "hashed_password": hashed_pw}
                )
                print(f"✅ User created/updated: {email}")
            except Exception as e:
                print(f"❌ Error creating user {email}: {e}")

        await conn.commit()

    print("\n✅ Setup complete!")
    print("\nTest users:")
    for email, password in test_users:
        print(f"  Email: {email}, Password: {password}")


if __name__ == "__main__":
    asyncio.run(setup_users())
