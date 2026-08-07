# One-time setup: registers a Windows Scheduled Task that polls Circa's Dropbox
# NHL futures sheet every 3 hours (when you're logged on) and flags changes.
# Run once:  .\setup_circa_task.ps1
$proj = $PSScriptRoot
$task = "NHL-Circa-Check"

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$proj\refresh_circa.ps1`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 3) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings `
    -Description "Poll Circa Dropbox NHL futures every 3h; flag changes." -Force

Write-Host "Registered scheduled task '$task' (every 3h). Logs -> circa_check.log"
Write-Host "Remove later with:  Unregister-ScheduledTask -TaskName '$task' -Confirm:`$false"
