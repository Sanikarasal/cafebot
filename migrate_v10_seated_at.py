"""
migrate_v10_seated_at.py
Add bookings.seated_at and backfill active arrived rows for live service timers.

Safe to run multiple times.
"""

import os
import sqlite3

DATABASE = "cafebot.db"


def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def migrate():
    if not os.path.exists(DATABASE):
        print(f"[!] {DATABASE} not found -- run init_db.py first.")
        return

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    try:
        print("[*] Starting v10 seated_at migration...")

        if not column_exists(conn, "bookings", "seated_at"):
            cur.execute("ALTER TABLE bookings ADD COLUMN seated_at TEXT")
            print("[OK] Added bookings.seated_at")
        else:
            print("[i] bookings.seated_at already exists")

        cur.execute(
            """
            UPDATE bookings
            SET seated_at = COALESCE(NULLIF(seated_at, ''), NULLIF(updated_at, ''), NULLIF(created_at, ''))
            WHERE LOWER(TRIM(status)) = 'arrived' AND (seated_at IS NULL OR TRIM(seated_at) = '')
            """
        )
        print(f"[OK] Backfilled seated_at for {cur.rowcount} arrived booking(s)")

        conn.commit()
        print("[OK] v10 migration complete.")
    except Exception as exc:
        conn.rollback()
        print(f"[X] Migration failed: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
