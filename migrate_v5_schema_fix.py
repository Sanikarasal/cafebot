"""
migrate_v5_schema_fix.py
Hotfix migration to stabilize CafeBot schema drift without data loss.

Safe to run multiple times.
"""

import sqlite3
import os
from typing import Optional

DATABASE = "cafebot.db"

def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

def get_status_default(conn) -> Optional[str]:
    rows = conn.execute("PRAGMA table_info(bookings)").fetchall()
    for r in rows:
        if r[1] == "status":
            return r[4]
    return None

def migrate():
    if not os.path.exists(DATABASE):
        print(f"[!] {DATABASE} not found -- run init_db.py first.")
        return

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        print("[*] Starting v5 schema hotfix migration...")

        # Add missing columns safely
        if not column_exists(conn, "bookings", "source"):
            cur.execute("ALTER TABLE bookings ADD COLUMN source TEXT DEFAULT 'bot'")
            print("[OK] Added bookings.source")
        else:
            print("[i] bookings.source already exists")

        if not column_exists(conn, "bookings", "twilio_last_response"):
            cur.execute("ALTER TABLE bookings ADD COLUMN twilio_last_response TEXT")
            print("[OK] Added bookings.twilio_last_response")
        else:
            print("[i] bookings.twilio_last_response already exists")

        if not column_exists(conn, "bookings", "created_at"):
            cur.execute("ALTER TABLE bookings ADD COLUMN created_at TEXT")
            print("[OK] Added bookings.created_at")
        else:
            print("[i] bookings.created_at already exists")

        if not column_exists(conn, "bookings", "updated_at"):
            cur.execute("ALTER TABLE bookings ADD COLUMN updated_at TEXT")
            print("[OK] Added bookings.updated_at")
        else:
            print("[i] bookings.updated_at already exists")

        # Inspect status default
        status_default = get_status_default(conn)
        print(f"[i] bookings.status default: {status_default}")

        # Migrate legacy status values
        active_count = cur.execute(
            "SELECT COUNT(*) FROM bookings WHERE status = 'active'"
        ).fetchone()[0]
        if active_count > 0:
            cur.execute(
                "UPDATE bookings SET status = 'Confirmed' WHERE status = 'active'"
            )
            print(f"[OK] Migrated {active_count} bookings from status 'active' to 'Confirmed'")
        else:
            print("[i] No bookings with status 'active' found")

        null_count = cur.execute(
            "SELECT COUNT(*) FROM bookings WHERE status IS NULL OR TRIM(status) = ''"
        ).fetchone()[0]
        if null_count > 0:
            cur.execute(
                "UPDATE bookings SET status = 'Pending' WHERE status IS NULL OR TRIM(status) = ''"
            )
            print(f"[OK] Migrated {null_count} bookings with empty status to 'Pending'")
        else:
            print("[i] No bookings with empty status found")

        # Backfill timestamps if columns exist and values are NULL
        if column_exists(conn, "bookings", "created_at"):
            cur.execute(
                "UPDATE bookings SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL OR TRIM(created_at) = ''"
            )
        if column_exists(conn, "bookings", "updated_at"):
            cur.execute(
                "UPDATE bookings SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL OR TRIM(updated_at) = ''"
            )

        conn.commit()
        print("[OK] v5 migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"[X] Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
