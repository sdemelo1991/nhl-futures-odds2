# Runs by the NHL-Circa-Check scheduled task. Polls the Circa Dropbox sheet;
# logs the result and drops CIRCA_UPDATED.flag when the sheet changes.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$ts  = Get-Date -Format "yyyy-MM-dd HH:mm"
$out = (python scrapers\circa.py 2>&1 | Out-String)
$code = $LASTEXITCODE

Add-Content -Path "$PSScriptRoot\circa_check.log" -Value "[$ts] exit=$code`n$out" -Encoding utf8

if ($code -eq 2) {
    $msg = "Circa NHL sheet CHANGED at $ts.`n" +
           "1) Send scrapers\.cache\circa_nhl.png to Claude to refresh circa_data.json`n" +
           "2) Run: python scrapers\circa.py --write   (or .\run_all.ps1)"
    Set-Content -Path "$PSScriptRoot\CIRCA_UPDATED.flag" -Value $msg -Encoding utf8
    Write-Host $msg
}
