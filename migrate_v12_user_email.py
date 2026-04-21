"""
migrate_v12_user_email.py

Adds `email` column to the `users` table for email-based OTP password reset.
Safe to run multiple times.
"""
import sqlite3

DATABASE = "cafebot.db"


def run():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}

        added = []
        if "email" not in existing:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            added.append("email")

        if added:
            conn.commit()
            print(f"✅  Migration v12: added columns to users → {', '.join(added)}")
        else:
            print("ℹ️   Migration v12: email column already exists — nothing to do.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
