r"""Generic HAR inspector — find where a book's odds live and their JSON shape.

For books whose API we don't know yet, capture the futures page as a HAR
(Chrome F12 -> Network -> reload/click tabs -> right-click -> "Save all as HAR
with content"), then:

    python scrapers/inspect_har.py scrapers/.cache/betonline.har

It ranks every JSON response by how much odds-like content it holds, prints the
top-level keys + a couple of sample odds objects for each, and lists any
WebSocket connections (odds sometimes stream over WS, which HAR won't fully
capture). Paste the output to Claude to build the book's parser.
"""
import base64
import json
import re
import sys
from collections import Counter

# PowerShell's default cp1252 console can't encode some unicode -> crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ODDS_KEYS = {"odds", "american", "americanodds", "oddsamerican", "moneyline",
             "price", "line", "handicap", "displayodds"}
NAME_KEYS = {"label", "name", "runnername", "participant", "shortname", "description",
             "team", "competitor", "selectionname"}
_AM = re.compile(r"^[+-]\d{2,5}$")


def is_odds_str(v):
    return isinstance(v, str) and bool(_AM.match(v.strip().replace("+", "+")))


def looks_like_odds_obj(d):
    if not isinstance(d, dict):
        return False
    for k, v in d.items():
        if k.lower() in ODDS_KEYS:
            return True
        if is_odds_str(v):
            return True
    return False


def scan(node, score, samples, keyhits):
    if isinstance(node, dict):
        if looks_like_odds_obj(node):
            score[0] += 1
            for k in node:
                if k.lower() in ODDS_KEYS or k.lower() in NAME_KEYS:
                    keyhits[k] += 1
            if len(samples) < 4:
                samples.append(node)
        for v in node.values():
            scan(v, score, samples, keyhits)
    elif isinstance(node, list):
        for it in node:
            scan(it, score, samples, keyhits)


def body_of(entry):
    resp = entry.get("response", {}) or {}
    content = resp.get("content", {}) or {}
    text = content.get("text")
    if not text:
        return None
    if content.get("encoding") == "base64":
        try:
            text = base64.b64decode(text).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
    return text


def compact(d, limit=280):
    s = json.dumps(d, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + " ...}"


def main():
    if len(sys.argv) < 2:
        print("usage: python scrapers/inspect_har.py <file.har>")
        return
    with open(sys.argv[1], encoding="utf-8") as f:
        har = json.load(f)
    entries = (har.get("log", {}) or {}).get("entries", []) or []
    print(f"=== HAR inspection: {len(entries)} entries ===\n")

    scored, ws, other_json = [], [], []
    for e in entries:
        url = e.get("request", {}).get("url", "")
        rtype = (e.get("_resourceType") or "").lower()
        if rtype == "websocket" or url.startswith("ws"):
            ws.append(url)
            continue
        text = body_of(e)
        if not text:
            continue
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            continue
        score, samples, keyhits = [0], [], Counter()
        scan(obj, score, samples, keyhits)
        top_keys = list(obj.keys())[:12] if isinstance(obj, dict) else f"<list len {len(obj)}>"
        if score[0]:
            scored.append((score[0], url, top_keys, keyhits, samples, len(text)))
        else:
            other_json.append((url, top_keys, len(text)))

    scored.sort(key=lambda x: -x[0])
    print(f"--- JSON responses WITH odds-like content ({len(scored)}) ---")
    for score, url, keys, keyhits, samples, size in scored[:12]:
        print(f"\n[odds objs~{score}]  {url[:130]}")
        print(f"   size={size//1024}KB  top-level keys: {keys}")
        print(f"   odds/name keys seen: {dict(keyhits.most_common(10))}")
        for s in samples[:2]:
            print(f"   sample: {compact(s)}")

    if ws:
        print(f"\n--- WebSocket connections ({len(ws)}) — odds may stream here ---")
        for u in ws[:10]:
            print(f"   {u[:130]}")

    print(f"\n--- other JSON responses without odds ({len(other_json)}) ---")
    for url, keys, size in other_json[:15]:
        print(f"   {url[:110]}  keys={keys}")

    print("\nPaste the section above (esp. the top odds responses + samples) to Claude.")


if __name__ == "__main__":
    main()
