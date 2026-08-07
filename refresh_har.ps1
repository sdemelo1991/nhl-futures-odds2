# Run by the NHL-HAR-Refresh scheduled task (~every 20 min, staggered off the
# 10-min direct task). Drives a real browser to capture DraftKings (Akamai
# blocks server-side fetch), parses it, and dedupes. Does NOT push — it just
# refreshes DK's slice of data/odds.json; the NHL-Live-Refresh task commits &
# pushes the file (so the two tasks never race on git). Logs to har_refresh.log.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$ts = Get-Date -Format "yyyy-MM-dd HH:mm"

python scrapers\capture.py draftkings | Out-Null   # headless; falls back nowhere — see log
python scrapers\draftkings.py --write | Out-Null
python scrapers\dedupe_players.py --write | Out-Null

$dk = ""
try { $dk = (python -c "import json;d=json.load(open('data/odds.json',encoding='utf-8'));print(sum(1 for t in d['to_win']['cup'] if 'draftkings' in d['to_win']['cup'][t]))") } catch {}
Add-Content -Path "$PSScriptRoot\har_refresh.log" `
    -Value "[$ts] DK captured+parsed (cup teams w/ DK price: $dk); push handled by NHL-Live-Refresh" -Encoding utf8
