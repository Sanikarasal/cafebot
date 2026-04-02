import sqlite3
DATABASE = "cafebot.db"
conn = sqlite3.connect(DATABASE)
conn.execute("CREATE TABLE IF NOT EXISTS customers (phone TEXT PRIMARY KEY, last_message_timestamp TEXT)")
conn.commit()
conn.close()
print("Migration successful.")
