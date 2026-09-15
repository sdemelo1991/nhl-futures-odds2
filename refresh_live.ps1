# Run by the NHL-Live-Refresh scheduled task (every ~10 min while you're logged on).
# Re-fetches the DIRECT-API books (no manual capture needed), dedupes player
# names, recomputes Jack Adams best_avail across whichever books post it, and
# — only if the odds actually moved — commits + pushes data/odds.json (+
# coaches_2026-27.json) so the Streamlit Cloud app updates. HAR-capture books
# (DK/BetMGM/BetOnline/Betano/theScore) are NOT here — they need a browser
# capture (see capture.py once built). Logs to live_refresh.log.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$ts  = Get-Date -Format "yyyy-MM-dd HH:mm"
$log = "$PSScriptRoot\live_refresh.log"

foreach ($b in @("pinnacle", "fanduel", "kalshi", "kambi", "dazn",
                 "betmgm", "betano", "betonline", "thescore")) {
    python "scrapers\$b.py" --write | Out-Null
}
python scrapers\dedupe_players.py --write | Out-Null
python scrapers\history.py | Out-Null   # append any per-selection price changes to price_history.json
python recompute_best_avail.py | Out-Null   # keep Jack Adams best_avail in sync with fresh odds

# Push only on a real odds change (ignore the timestamp-only bump every write does).
$state = (python scrapers\_live_hash.py | Out-String).Trim()
if ($state -match "CHANGED") {
    git add data/odds.json data/price_history.json coaches_2026-27.json
    git commit -m "auto: refresh direct-API odds [$ts]" | Out-Null
    # Never let an unattended push pop a GUI or block waiting for sign-in:
    # if the stored credential is ever invalid, the push fails fast and logs it
    # instead of hanging a GitHub-login window open (which is what piled up
    # dozens of windows overnight). Re-auth once manually to refresh the token.
    $env:GIT_TERMINAL_PROMPT = "0"   # git won't prompt on the console
    $env:GCM_INTERACTIVE     = "never" # Git Credential Manager won't show its GUI
    $push = (git -c credential.interactive=false push 2>&1 | Out-String)
    Add-Content -Path $log -Value "[$ts] CHANGED -> pushed`n$push" -Encoding utf8
} else {
    Add-Content -Path $log -Value "[$ts] no odds change" -Encoding utf8
}
