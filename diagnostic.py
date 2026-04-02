"""
diagnostic.py – Run this to check what's preventing app.py from starting.
"""
import sys
import traceback

print(f"Python: {sys.version}", flush=True)
print(f"Executable: {sys.executable}", flush=True)

print("\n--- Checking imports ---", flush=True)
try:
    import flask
    print(f"  flask {flask.__version__}  OK", flush=True)
except Exception as e:
    print(f"  flask MISSING: {e}", flush=True)

try:
    import flask_session
    print(f"  flask_session OK", flush=True)
except Exception as e:
    print(f"  flask_session MISSING: {e}", flush=True)

try:
    import dotenv
    print(f"  python-dotenv OK", flush=True)
except Exception as e:
    print(f"  python-dotenv MISSING: {e}", flush=True)

try:
    import twilio
    print(f"  twilio {twilio.__version__}  OK", flush=True)
except Exception as e:
    print(f"  twilio MISSING: {e}", flush=True)

print("\n--- Importing project modules ---", flush=True)
try:
    import db
    print("  db.py  OK", flush=True)
except Exception as e:
    print(f"  db.py ERROR: {e}", flush=True)
    traceback.print_exc()

try:
    import bot
    print("  bot.py OK", flush=True)
except Exception as e:
    print(f"  bot.py ERROR: {e}", flush=True)
    traceback.print_exc()

try:
    import admin
    print("  admin.py OK", flush=True)
except Exception as e:
    print(f"  admin.py ERROR: {e}", flush=True)
    traceback.print_exc()

try:
    import app
    print("  app.py OK", flush=True)
except Exception as e:
    print(f"  app.py ERROR: {e}", flush=True)
    traceback.print_exc()

print("\n--- Checking database ---", flush=True)
import os
if os.path.exists("cafebot.db"):
    print(f"  cafebot.db exists ({os.path.getsize('cafebot.db')} bytes)", flush=True)
    import sqlite3
    conn = sqlite3.connect("cafebot.db")
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"  Tables: {tables}", flush=True)
    conn.close()
else:
    print("  cafebot.db NOT FOUND – run python init_db.py first!", flush=True)

print("\n--- Checking port 5000 ---", flush=True)
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1', 5000))
sock.close()
if result == 0:
    print("  Port 5000 is already IN USE (another process is running on it)", flush=True)
else:
    print("  Port 5000 is FREE – Flask can bind to it", flush=True)

print("\nDone.", flush=True)
