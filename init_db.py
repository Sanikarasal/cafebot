import sqlite3
import os

DATABASE = 'cafebot.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if os.path.exists(DATABASE):
        os.remove(DATABASE)

    conn = get_db_connection()
    c = conn.cursor()

    # Create users table
    c.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Seed default admin (admin / admin123) and staff (staff / staff123)
    from werkzeug.security import generate_password_hash
    c.executemany(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        [
            ('admin', generate_password_hash('admin123'), 'admin'),
            ('staff', generate_password_hash('staff123'), 'staff')
        ]
    )

    # Create bookings table
    c.execute('''
        CREATE TABLE bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            seats INTEGER NOT NULL,
            table_number INTEGER,
            status TEXT DEFAULT 'Pending',
            combo_group TEXT,
            reminder_sent INTEGER DEFAULT 0,
            seated_at TEXT,
            is_auto_allocated BOOLEAN DEFAULT 0,
            payment_link_id TEXT
        )
    ''')

    # Create booking_groups table for combo bookings
    c.execute('''
        CREATE TABLE booking_groups (
            id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            total_guests INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create time_slots table
    c.execute('''
        CREATE TABLE time_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            total_capacity INTEGER NOT NULL,
            available_seats INTEGER NOT NULL,
            max_guests INTEGER DEFAULT 30
        )
    ''')

    # Create tables table
    c.execute('''
        CREATE TABLE tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number INTEGER NOT NULL UNIQUE,
            table_name TEXT,
            capacity INTEGER NOT NULL,
            location TEXT NOT NULL,
            status TEXT DEFAULT 'Vacant',
            image_url TEXT
        )
    ''')

    # Create waitlist table
    c.execute('''
        CREATE TABLE waitlist (
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

    # Seed table data
    seed_tables = [
        (1, 2, 'Window Side', ''),
        (2, 2, 'Near Entrance', ''),
        (3, 4, 'AC Zone', ''),
        (4, 4, 'Balcony', ''),
        (5, 6, 'Family Zone', ''),
        (6, 8, 'Private Hall', ''),
    ]
    c.executemany('''
        INSERT INTO tables (table_number, capacity, location, image_url)
        VALUES (?, ?, ?, ?)
    ''', seed_tables)

    # Insert some initial dummy time slots for today
    from datetime import date
    today = str(date.today())

    initial_slots = [
        (today, '10AM-11AM', 20, 20, 30),
        (today, '11:10AM-12:10PM', 30, 30, 30),
        (today, '4:10PM-5:10PM', 25, 25, 30)
    ]

    c.executemany('''
        INSERT INTO time_slots (date, slot_time, total_capacity, available_seats, max_guests)
        VALUES (?, ?, ?, ?, ?)
    ''', initial_slots)

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully.")
    print("   Default admin: admin / admin123")

if __name__ == '__main__':
    init_db()
