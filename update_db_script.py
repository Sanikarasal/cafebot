import os

def update_db_py():
    with open('db.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace active status checks
    content = content.replace("status = 'active'", "status IN ('Pending', 'Confirmed', 'Arrived')")

    # Replace admins with users
    content = content.replace("SELECT * FROM admins WHERE username = ?", "SELECT * FROM users WHERE username = ?")
    content = content.replace("INSERT INTO admins (username, password_hash) VALUES (?, ?)", "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')")
    content = content.replace("def get_admin_by_username", "def get_user_by_username")
    content = content.replace("def create_admin", "def create_user")

    # Add staff functions at the end
    staff_extensions = """
# ---------------------------------------------------------------------------
# Staff / Additional status helpers
# ---------------------------------------------------------------------------

def update_booking_status(booking_id: int, new_status: str):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, booking_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating booking status: {e}")
        return False
    finally:
        conn.close()

def update_table_status(table_id: int, new_status: str):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE tables SET status = ? WHERE id = ?", (new_status, table_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating table status: {e}")
        return False
    finally:
        conn.close()

def get_all_users():
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return users

def get_today_bookings(today_date: str):
    conn = get_db_connection()
    bookings = conn.execute(
        "SELECT * FROM bookings WHERE date = ? ORDER BY slot_time ASC",
        (today_date,)
    ).fetchall()
    conn.close()
    return bookings
"""

    if "update_booking_status" not in content:
        content += staff_extensions

    with open('db.py', 'w', encoding='utf-8') as f:
        f.write(content)
        print("Successfully updated db.py")

if __name__ == '__main__':
    update_db_py()
