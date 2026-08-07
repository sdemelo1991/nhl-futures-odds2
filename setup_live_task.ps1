# One-time setup: registers a Windows Scheduled Task that refreshes the
# direct-API books every 10 minutes (while you're logged on) and pushes any
# odds change to GitHub so the Streamlit Cloud app updates on its own.
# Run once:  .\setup_live_task.ps1
# NOTE: do one manual `git push` first so your GitHub credential is cached —
# the task pushes non-interactively and can't answer a login prompt.
$proj = $PSScriptRoot
$task = "NHL-Live-Refresh"

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$proj\refresh_live.ps1`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8)

Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings `
    -Description "Refresh direct-API NHL books every 10 min; push data/odds.json on change." -Force

Write-Host "Registered scheduled task '$task' (every 10 min). Logs -> live_refresh.log"
Write-Host "Stop later with:  Unregister-ScheduledTask -TaskName '$task' -Confirm:`$false"
