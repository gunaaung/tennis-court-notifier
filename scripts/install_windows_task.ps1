$ErrorActionPreference = "Stop"

$TaskName = "TennisCourtNotifier"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $ProjectRoot "scripts\run_scheduled.py"

$PythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $PythonW) {
    $PythonExe = (Get-Command python.exe -ErrorAction Stop | Select-Object -First 1 -ExpandProperty Source)
    $Candidate = Join-Path (Split-Path -Parent $PythonExe) "pythonw.exe"
    if (Test-Path $Candidate) {
        $PythonW = $Candidate
    } else {
        $PythonW = $PythonExe
    }
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "09:00"

$Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "09:00" -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 10 -Minutes 15)).Repetition

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Check tennis courts every 10 minutes (09:00-19:00 ICT) and notify LINE." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' using $PythonW"
