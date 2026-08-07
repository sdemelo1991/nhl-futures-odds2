# NHL Futures Pricing Desk — one-shot refresh + launch.
# Usage:  .\run_all.ps1        (from the project folder)
#
# Refreshes every book we can pull automatically, re-applies the latest
# DraftKings captures, then launches the dashboard. Books that are mobile-only
# / manual (entered by paste) keep whatever is already in data\odds.json.

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

if (Test-Path "$PSScriptRoot\CIRCA_UPDATED.flag") {
    Write-Host "`n*** CIRCA UPDATED ***" -ForegroundColor Magenta
    Get-Content "$PSScriptRoot\CIRCA_UPDATED.flag" | Write-Host -ForegroundColor Magenta
    Write-Host "(clear this notice after refreshing: Remove-Item CIRCA_UPDATED.flag)`n" -ForegroundColor Magenta
}

Write-Host "`n=== Refreshing books ===" -ForegroundColor Cyan

Write-Host "`n[Pinnacle] (direct API)" -ForegroundColor Yellow
python scrapers\pinnacle.py --write

Write-Host "`n[FanDuel] (direct API)" -ForegroundColor Yellow
python scrapers\fanduel.py --write

Write-Host "`n[Kalshi] (direct API; YES-ask @ `$300 liquidity)" -ForegroundColor Yellow
python scrapers\kalshi.py --write

Write-Host "`n[DraftKings] (from saved captures in scrapers\.cache\dk*.har/json)" -ForegroundColor Yellow
python scrapers\draftkings.py --write

Write-Host "`n[BetOnline] (from saved capture scrapers\.cache\betonline.har)" -ForegroundColor Yellow
python scrapers\betonline.py --write

Write-Host "`n[BetMGM] (from saved capture scrapers\.cache\betmgm.har)" -ForegroundColor Yellow
python scrapers\betmgm.py --write

Write-Host "`n[Kambi/Northstar] (direct Kambi API; HAR fallback)" -ForegroundColor Yellow
python scrapers\kambi.py --write

Write-Host "`n[Betano] (from saved capture scrapers\.cache\betano.har)" -ForegroundColor Yellow
python scrapers\betano.py --write

Write-Host "`n[DAZN] (direct Altenar widget API; HAR fallback)" -ForegroundColor Yellow
python scrapers\dazn.py --write

Write-Host "`n[theScore] (from saved capture scrapers\.cache\thescore.har)" -ForegroundColor Yellow
python scrapers\thescore.py --write

Write-Host "`n[Circa] (applies transcribed circa_data.json; run 'circa.py' alone to poll Dropbox)" -ForegroundColor Yellow
python scrapers\circa.py --write

Write-Host "`n[Manual books] (apply transcribed <book>_data.json from your pastes)" -ForegroundColor Yellow
python scrapers\apply_manual.py bookmaker
python scrapers\apply_manual.py caesars
python scrapers\apply_manual.py bet365
python scrapers\apply_manual.py hardrock

# --- add future direct-API books here, one line each ---
# python scrapers\betmgm.py --write
# python scrapers\betano.py --write

Write-Host "`n=== Launching dashboard ===" -ForegroundColor Cyan
streamlit run app.py
