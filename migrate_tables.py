"""
migrate_tables.py
Run once to patch an existing cafebot.db without wiping data.
  python migrate_tables.py
"""
import sqlite3
import os

DATABASE = 'cafebot.db'


def migrate():
    if not os.path.exists(DATABASE):
        print("⚠️  cafebot.db not found – run init_db.py first.")
        return

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. Add table_number column to bookings (safe – ignores if already exists)
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN table_number INTEGER")
        print("✅ Added table_number column to bookings.")
    except sqlite3.OperationalError:
        print("ℹ️  table_number column already exists in bookings – skipped.")

    # 2. Create tables table if it doesn't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER NOT NULL UNIQUE,
            capacity INTEGER NOT NULL,
            location TEXT NOT NULL,
            image_url TEXT
        )
    ''')

    # 3. Seed tables only if the table is empty
    existing = c.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
    if existing == 0:
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
            seed_tables
        )
        print("✅ Seeded 6 tables into the tables table.")
    else:
        print(f"ℹ️  tables table already has {existing} row(s) – seed skipped.")

    conn.commit()
    conn.close()
    print("✅ Migration complete.")


if __name__ == '__main__':
    migrate()
