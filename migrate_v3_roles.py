import sqlite3
import os
from werkzeug.security import generate_password_hash

DATABASE = 'cafebot.db'

def migrate():
    if not os.path.exists(DATABASE):
        print(f"Database {DATABASE} not found!")
        return

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    try:
        # 1. Create users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # migrating admins to users
        try:
            admins = c.execute("SELECT username, password_hash FROM admins").fetchall()
            for admin in admins:
                # ignore duplicates
                try:
                    c.execute(
                        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                        (admin[0], admin[1], 'admin')
                    )
                except sqlite3.IntegrityError:
                    pass
            # drop admins table
            c.execute("DROP TABLE IF EXISTS admins")
        except sqlite3.OperationalError:
            pass # admins table might not exist

        # seed a default staff user
        try:
            c.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ('staff', generate_password_hash('staff123'), 'staff')
            )
        except sqlite3.IntegrityError:
            pass # staff already exists

        # 2. Update tables table
        # We need to add table_name and status columns
        try:
            c.execute("ALTER TABLE tables ADD COLUMN table_name TEXT")
        except sqlite3.OperationalError:
            pass # column exists
            
        try:
            c.execute("ALTER TABLE tables ADD COLUMN status TEXT DEFAULT 'Vacant'")
        except sqlite3.OperationalError:
            pass # column exists
            
        # Update existing tables to set default names if null
        c.execute("UPDATE tables SET table_name = 'Table ' || table_number WHERE table_name IS NULL")
        c.execute("UPDATE tables SET status = 'Vacant' WHERE status IS NULL")

        # 3. Update bookings status
        c.execute("UPDATE bookings SET status = 'Confirmed' WHERE status = 'active'")
        # For new bookings, default status is now Pending, we will handle this in code.

        conn.commit()
        print("Migration v3 completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
