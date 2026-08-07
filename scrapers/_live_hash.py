"""Print CHANGED if odds.json's meaningful content changed since the last run,
else SAME — ignoring meta timestamps (last_updated / book_updated), which bump
every write. Used by refresh_live.ps1 to avoid pushing (and redeploying the
Streamlit app) on a no-op timestamp-only change.
"""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
doc = json.load(open(os.path.join(ROOT, "data", "odds.json"), encoding="utf-8"))
meta = doc.get("meta", {}) or {}
for k in ("last_updated", "book_updated"):
    meta.pop(k, None)
digest = hashlib.md5(
    json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

state = os.path.join(ROOT, ".live_hash")
prev = open(state).read().strip() if os.path.exists(state) else ""
with open(state, "w") as f:
    f.write(digest)
print("CHANGED" if digest != prev else "SAME")
