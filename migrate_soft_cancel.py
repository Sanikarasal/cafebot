import sqlite3
import os

DATABASE = 'cafebot.db'

def migrate_soft_cancel():
    if not os.path.exists(DATABASE):
        print("Database not found. Run init_db.py instead.")
        return

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Check if 'status' column exists
    cursor.execute("PRAGMA table_info(bookings)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'status' not in columns:
        print("Adding 'status' column to 'bookings' table...")
        cursor.execute("ALTER TABLE bookings ADD COLUMN status TEXT DEFAULT 'active'")
        conn.commit()
        print("✅ Migration successful: 'status' column added.")
    else:
        print("ℹ️ 'status' column already exists in 'bookings'. Skipping migration.")

    conn.close()

if __name__ == '__main__':
    migrate_soft_cancel()
