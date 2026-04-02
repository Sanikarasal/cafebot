"""
migrate_v6_conversations.py
Create conversations table for persistent WhatsApp state.

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
            CREATE TABLE IF NOT EXISTS conversations (
                phone TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                data_json TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
        print("[OK] conversations table ready.")
    except Exception as e:
        conn.rollback()
        print(f"[X] Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
