"""
migrate_v7_booking_groups.py
Create booking_groups table for combo bookings.

Safe to run multiple times.
"""

import sqlite3
import os

DATABASE = "cafebot.db"

def migrate():
    if not os.path.exists(DATABASE):
        print(f"[!] {DATABASE} not found -- run init_db.py first.")
        return

    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS booking_groups (
                id TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                name TEXT NOT NULL,
                date TEXT NOT NULL,
                slot_time TEXT NOT NULL,
                total_guests INTEGER NOT NULL,
                created_at TEXT
            )
            """
        )
        conn.commit()
        print("[OK] booking_groups table ready.")
    except Exception as e:
        conn.rollback()
        print(f"[X] Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
