import sqlite3

def migrate():
    conn = sqlite3.connect("cafebot.db")
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN payment_link_id TEXT")
        print("Column payment_link_id added successfully.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column payment_link_id already exists.")
        else:
            print("Error:", e)
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
