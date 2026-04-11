"""
migrate_v11_user_phone_otp.py

Adds `phone`, `reset_otp`, and `reset_otp_expiry` columns to the `users` table.
Safe to run multiple times (checks before altering).
"""
import sqlite3

DATABASE = "cafebot.db"


def run():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}

    added = []
    for col, definition in [
        ("phone",            "TEXT"),
        ("reset_otp",        "TEXT"),
        ("reset_otp_expiry", "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            added.append(col)

    if added:
        conn.commit()
        print(f"✅  Migration v11: added columns to users → {', '.join(added)}")
    else:
        print("ℹ️   Migration v11: columns already exist — nothing to do.")

    conn.close()


if __name__ == "__main__":
    run()
