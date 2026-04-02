"""
migrate_v2.py
Non-destructive migration for CafeBot v2 features.
Adds: admins table, waitlist table, new columns (combo_group, reminder_sent, max_guests).
Safe to run multiple times — uses IF NOT EXISTS / try-except.

"""

import sqlite3
import os

DATABASE = 'cafebot.db'


def migrate():
    if not os.path.exists(DATABASE):
        print("[!] cafebot.db not found -- run init_db.py first.")
        return

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("[*] Starting CafeBot v2 migration...\n")

    # 1. Create admins table
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
    ''')
    print("[OK] admins table ready.")

    # Seed default admin if table is empty
    admin_count = c.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if admin_count == 0:
        from werkzeug.security import generate_password_hash
        c.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ('admin', generate_password_hash('admin123')),
        )
        print("[OK] Seeded default admin (admin / admin123).")
    else:
        print(f"[i] admins table already has {admin_count} admin(s) -- seed skipped.")

    # 2. Create waitlist table
    c.execute('''
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            guests INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("[OK] waitlist table ready.")

    # 3. Add combo_group column to bookings
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN combo_group TEXT")
        print("[OK] Added combo_group column to bookings.")
    except sqlite3.OperationalError:
        print("[i] combo_group column already exists -- skipped.")

    # 4. Add reminder_sent column to bookings
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN reminder_sent INTEGER DEFAULT 0")
        print("[OK] Added reminder_sent column to bookings.")
    except sqlite3.OperationalError:
        print("[i] reminder_sent column already exists -- skipped.")

    # 5. Add max_guests column to time_slots
    try:
        c.execute("ALTER TABLE time_slots ADD COLUMN max_guests INTEGER DEFAULT 30")
        print("[OK] Added max_guests column to time_slots.")
    except sqlite3.OperationalError:
        print("[i] max_guests column already exists -- skipped.")

    # 6. Ensure tables table exists (from previous migration)
    c.execute('''
        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER NOT NULL UNIQUE,
            capacity INTEGER NOT NULL,
            location TEXT NOT NULL,
            image_url TEXT
        )
    ''')

    # Seed tables if empty
    existing_tables = c.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
    if existing_tables == 0:
        seed_tables = [
            (1, 2, 'Window Side', ''),
            (2, 2, 'Near Entrance', ''),
            (3, 4, 'AC Zone', ''),
            (4, 4, 'Balcony', ''),
            (5, 6, 'Family Zone', ''),
            (6, 8, 'Private Hall', ''),
        ]
        c.executemany(
            "INSERT INTO tables (table_number, capacity, location, image_url) VALUES (?, ?, ?, ?)",
            seed_tables,
        )
        print("[OK] Seeded 6 tables.")
    else:
        print(f"[i] tables table already has {existing_tables} row(s) -- seed skipped.")

    # 7. Add table_number to bookings (from v1 migration)
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN table_number INTEGER")
        print("[OK] Added table_number column to bookings.")
    except sqlite3.OperationalError:
        print("[i] table_number column already exists -- skipped.")

    conn.commit()
    conn.close()
    print("\n[OK] Migration v2 complete!")


if __name__ == '__main__':
    migrate()
