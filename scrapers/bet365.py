r"""bet365 NHL futures — DISCOVERY pass (LOCAL).

bet365 doesn't serve clean JSON. Futures prices arrive over a WebSocket in a
proprietary delimited encoding (fields split by ASCII control characters, with
short key codes). Chrome's "Save all as HAR with content" captures those frames
under each entry's `_webSocketMessages`.

This is the discovery phase: point it at the HAR and it dumps the raw frames
(plus any bet365 HTTP bodies) so we can reverse the encoding and build routing.
Once the field codes are known, a `--write` router gets added like every other
book.

Capture steps:
  1) Chrome > open the NHL 2026/27 futures page. Open DevTools (F12) > Network.
  2) Tick "Preserve log". Then RELOAD the page (Ctrl+R) with Network recording
     so the initial snapshot frame is captured.
  3) Click through every futures tab (To Win Outright / Conference / Division /
     Make Playoffs / Presidents' / awards) and hit every "Show more" so all the
     prices stream in.
  4) Right-click anywhere in the Network request list > "Save all as HAR with
     content".
  5) Save it here:  scrapers\.cache\bet365.har
  6) Run:  python scrapers\bet365.py
     Then paste the previews it prints (or send scrapers\.cache\bet365_frames.txt).
"""
import base64
import glob
import json
import os
import sys

from common import CACHE_DIR

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# ASCII control chars bet365 is known to use as record/field separators
DELIMS = {f"\\x{c:02x}": chr(c) for c in range(1, 9)}


def har_entries(fp):
    with open(fp, encoding="utf-8") as f:
        raw = json.load(f)
    return (raw.get("log", {}) or {}).get("entries", []) or []


def decode_body(content):
    body = (content or {}).get("text")
    if not body:
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(body).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
    return body


def delims_present(s):
    return [name for name, ch in DELIMS.items() if ch in s]


def main():
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "bet365*.har")))
    if not files:
        print(f"No capture found. Save the HAR as {CACHE_DIR}\\bet365.har (see header).")
        return

    ws_frames, http_bodies, saw_ws_key = [], [], False
    for fp in files:
        for e in har_entries(fp):
            url = e.get("request", {}).get("url", "")
            msgs = e.get("_webSocketMessages")
            if msgs is not None:
                saw_ws_key = True
            for msg in msgs or []:
                data = msg.get("data")
                if data:
                    ws_frames.append((msg.get("type", ""), data))
            # bet365 pushes odds as big XHR "Blob/www-sports" bodies. Grab any
            # response that's either on a bet365 host OR carries the tell-tale
            # control-char delimiters — so we don't miss it on an edge/CDN host.
            b = decode_body((e.get("response", {}) or {}).get("content", {}))
            if b and len(b) > 200 and (("bet365" in url or "365" in url) or delims_present(b)):
                http_bodies.append((url, b))

    print(f"HAR files: {[os.path.basename(f) for f in files]}")
    print(f"WebSocket frames: {len(ws_frames)}   bet365 HTTP bodies >200B: {len(http_bodies)}")
    if not ws_frames and not saw_ws_key:
        print("\n  !! No `_webSocketMessages` in this HAR. Your Chrome's HAR export")
        print("     didn't include WS frame content. Options:")
        print("       - Update Chrome and re-export with 'Save all as HAR with content', or")
        print("       - In Network, click the WS (wss://) connection > Messages tab,")
        print("         then tell me and I'll give you a way to copy the frames directly.")

    # incoming frames ('receive') carry the pushed odds; biggest first
    recv = sorted((d for t, d in ws_frames if t in ("receive", "")), key=len, reverse=True)
    out = os.path.join(CACHE_DIR, "bet365_frames.txt")
    with open(out, "w", encoding="utf-8") as f:
        for i, d in enumerate(recv[:300]):
            f.write(f"=== ws-frame {i} len={len(d)} delims={delims_present(d)} ===\n{d}\n\n")
        for i, (u, b) in enumerate(http_bodies[:50]):
            f.write(f"=== http {i} len={len(b)} url={u} ===\n{b[:6000]}\n\n")
    if recv or http_bodies:
        print(f"  dumped {min(len(recv), 300)} receive-frames + {min(len(http_bodies), 50)} "
              f"http bodies -> {out}")

    for d in recv[:3]:
        print(f"\n--- receive frame  len={len(d)}  delims={delims_present(d)} ---")
        print(d[:700])
    print("\nPaste the previews above (or send bet365_frames.txt) so I can build the decoder.")


if __name__ == "__main__":
    main()
