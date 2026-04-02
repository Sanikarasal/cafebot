import sqlite3
import os

DATABASE = 'cafebot.db'

def migrate():
    if not os.path.exists(DATABASE):
        print("Database not found, skipping migration.")
        return

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    try:
        c.execute("ALTER TABLE bookings ADD COLUMN is_auto_allocated BOOLEAN DEFAULT 0")
        conn.commit()
        print("✅ Added is_auto_allocated to bookings table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("✅ Column is_auto_allocated already exists.")
        else:
            print(f"⚠️ Error migrating database: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
