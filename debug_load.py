import sys
sys.path.insert(0, '.')
from nbchat.core.db import load_history
import sqlite3
DB_PATH = '/content/chat_history.db'
conn = sqlite3.connect(DB_PATH)
cur = conn.execute("SELECT role, content, COALESCE(tool_id, ''), COALESCE(tool_name, ''), COALESCE(tool_args, '') FROM chat_log WHERE session_id = ? ORDER BY id ASC", ('306844f4-e346-4fa2-82b9-0e40cce2ec3d',))
rows = cur.fetchall()
print(f"Direct query rows: {len(rows)}")
for i in range(min(5, len(rows))):
    print(rows[i])
print("Now using load_history:")
rows2 = load_history('306844f4-e346-4fa2-82b9-0e40cce2ec3d')
print(f"Load history rows: {len(rows2)}")
for i in range(min(5, len(rows2))):
    print(rows2[i])
# Compare
print("First row diff:", rows[0] == rows2[0] if rows2 else "none")