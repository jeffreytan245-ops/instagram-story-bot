<#
.SYNOPSIS
  Registers (or removes) a Windows scheduled task that runs post_story.py every day at 13:00.

.EXAMPLE
  .\install_task.ps1                      # daily at 13:00, runs when you are logged on
  .\install_task.ps1 -Time 09:30          # different time
  .\install_task.ps1 -RunWhenLoggedOff    # also fires while you are logged out (PC must be on)
  .\install_task.ps1 -Remove              # delete the task
#>
param(
    [string]$Time = "13:00",
    [string]$TaskName = "Instagram Daily Story",
    [switch]$RunWhenLoggedOff,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
    return
}

$script = Join-Path $PSScriptRoot "post_story.py"
if (-not (Test-Path $script)) { throw "post_story.py not found next to this script." }
if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    Write-Warning ".env not found. Copy .env.example to .env and fill it in before 13:00."
}

$python = (Get-Command python -ErrorAction Stop).Source

$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)

if ($RunWhenLoggedOff) {
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
} else {
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Posts the next queued Instagram Story via post_story.py" -Force | Out-Null

Write-Host "Task '$TaskName' registered: daily at $Time."
Write-Host "Next run: $((Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime)"
Write-Host "Test now with:  Start-ScheduledTask -TaskName '$TaskName'"
