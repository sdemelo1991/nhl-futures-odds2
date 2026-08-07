# One-time setup: registers a Windows Scheduled Task that refreshes DraftKings
# via the browser capture every 20 minutes (staggered 3 min off NHL-Live-Refresh
# so the two never race). DK's data lands in data/odds.json; the 10-min direct
# task commits & pushes it. Run once:  .\setup_har_task.ps1
$proj = $PSScriptRoot
$task = "NHL-HAR-Refresh"

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$proj\refresh_har.ps1`""
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(3)) `
    -RepetitionInterval (New-TimeSpan -Minutes 20) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings `
    -Description "Browser-capture DraftKings every 20 min; parse into odds.json." -Force

Write-Host "Registered scheduled task '$task' (every 20 min). Logs -> har_refresh.log"
Write-Host "Stop later with:  Unregister-ScheduledTask -TaskName '$task' -Confirm:`$false"
