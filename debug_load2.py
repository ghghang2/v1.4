import sys
sys.path.insert(0, '.')
from nbchat.core.db import load_history
rows = load_history('306844f4-e346-4fa2-82b9-0e40cce2ec3d')
print(f"Rows: {len(rows)}")
if rows:
    print(rows[0])