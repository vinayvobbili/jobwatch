# Exercises `jobwatch service` (the Task Scheduler backend in jobwatch/service.py) on a real Windows machine.
# Run by .github/workflows/service-windows.yml on a windows-latest runner; also runnable by hand on Windows with
# an installed jobwatch:  pwsh scripts/windows_service_check.ps1 [-Port 8765]
#
# What it cannot test: the ONLOGON trigger and a reboot. A runner has no interactive logon to wait for, so
# "starts at login" is checked only as far as the task XML (a LogonTrigger for the user) and `schtasks /Run`
# (what the installer itself does to start the page now). RestartOnFailure is exercised by killing the process
# and watching; whatever Task Scheduler does is reported as observed, not assumed.
param([int]$Port = 8765)

$ErrorActionPreference = 'Continue'
$Task = 'jobwatch-ui'
$Url = "http://127.0.0.1:$Port/"
$Failures = New-Object System.Collections.Generic.List[string]
$tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$Summary = if ($env:GITHUB_STEP_SUMMARY) { $env:GITHUB_STEP_SUMMARY } else { Join-Path $tmp 'jobwatch-service-summary.md' }
Set-Content -Path $Summary -Value "## jobwatch service on Windows ($([System.Environment]::OSVersion.VersionString))`n" -Encoding utf8

function Say([string]$text) { Write-Host $text; Add-Content -Path $Summary -Value $text -Encoding utf8 }
function Block([string]$title, $body) {
    $text = ($body | Out-String).TrimEnd()
    Write-Host "--- $title`n$text"
    Add-Content -Path $Summary -Encoding utf8 -Value "<details><summary>$title</summary>`n`n``````text`n$text`n```````n`n</details>`n"
}
function Check([string]$name, [bool]$ok, [string]$detail = '') {
    if ($ok) { Say "- PASS $name" } else { Say "- FAIL $name $detail"; $Failures.Add($name) }
}
function Get-Page { try { (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 } }
function Wait-Page([int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) { if ((Get-Page) -eq 200) { return $true }; Start-Sleep -Seconds 2 }
    return $false
}
function Port-Open {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $c.Close() }
}
function Ui-Processes {
    Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'jobwatch\.cli' }
}
function Task-Status { ((schtasks /Query /TN $Task /FO LIST /V 2>&1) | Out-String) }

$work = Join-Path $tmp 'jobwatch-service-check'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$cfg = Join-Path $work 'jobwatch.yaml'
# Made up: fictional companies, and no checking of boards (fetch_every: off) so the page needs no network.
Set-Content -Path $cfg -Encoding utf8 -Value @'
companies:
  - greenhouse:globex
  - ashby:initech
fetch_every: off
filters:
  titles: ["engineer"]
'@
$xmlPath = Join-Path $env:LOCALAPPDATA 'jobwatch\jobwatch-ui-task.xml'
$logPath = Join-Path $env:LOCALAPPDATA 'jobwatch\ui.log'

try {
    # ---- 1. install ----
    Say "### 1. install"
    $out = & jobwatch -c $cfg service install --port $Port 2>&1
    $code = $LASTEXITCODE
    Block 'jobwatch service install' $out
    Check 'install exits 0' ($code -eq 0) "exit $code"

    # ---- 2. the task is registered ----
    Say "### 2. task registered"
    $q = Task-Status
    Block "schtasks /Query /TN $Task /V /FO LIST" $q
    Check 'schtasks lists the task' ($q -match "TaskName:\s+\\$Task")
    Check 'task runs as the runner user, logon only' ($q -match 'Logon Mode:\s+Interactive only')
    Check 'task has a run-at-logon trigger' ($q -match 'Schedule Type:\s+At logon time')

    # ---- 3. the XML written beside the log ----
    Say "### 3. task XML"
    Check 'XML file exists' (Test-Path $xmlPath) $xmlPath
    $raw = [System.IO.File]::ReadAllBytes($xmlPath)
    Check 'XML is UTF-16 with a byte-order mark' ($raw.Length -gt 2 -and $raw[0] -eq 0xFF -and $raw[1] -eq 0xFE)
    $doc = New-Object System.Xml.XmlDocument
    $parsed = $false
    try { $doc.Load($xmlPath); $parsed = $true } catch { Say "  XML parse error: $_" }
    Check 'XML parses' $parsed
    if ($parsed) {
        $ns = New-Object System.Xml.XmlNamespaceManager($doc.NameTable)
        $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
        $get = { param($p) $doc.SelectSingleNode($p, $ns).InnerText }
        Check 'RestartOnFailure interval is 1 minute' ((& $get '//t:RestartOnFailure/t:Interval') -eq 'PT1M')
        Check 'RestartOnFailure count is 999' ((& $get '//t:RestartOnFailure/t:Count') -eq '999')
        Check 'no execution time limit' ((& $get '//t:ExecutionTimeLimit') -eq 'PT0S')
        Check 'a second copy is ignored' ((& $get '//t:MultipleInstancesPolicy') -eq 'IgnoreNew')
        Check 'least privilege, interactive token' (((& $get '//t:RunLevel') -eq 'LeastPrivilege') -and ((& $get '//t:LogonType') -eq 'InteractiveToken'))
        Check 'a repeating trigger every 5 minutes starts a stopped page' ((& $get '//t:TimeTrigger/t:Repetition/t:Interval') -eq 'PT5M')
        Check 'a logon trigger for the user' (($null -ne $doc.SelectSingleNode('//t:LogonTrigger', $ns)) -and ((& $get '//t:LogonTrigger/t:UserId') -ne ''))
        $cmd = & $get '//t:Exec/t:Command'
        $arguments = & $get '//t:Exec/t:Arguments'
        Say "  command: $cmd`n  arguments: $arguments"
        Check 'runs pythonw (no console window)' ($cmd -match 'pythonw\.exe$')
        Check "arguments name the watchlist, port $Port and --log" (($arguments -match [regex]::Escape('jobwatch.cli')) -and ($arguments -match "--port $Port") -and ($arguments -match '--log') -and ($arguments -match [regex]::Escape($cfg)))
    }
    # What Task Scheduler itself stored (it may normalise the XML).
    $stored = (schtasks /Query /TN $Task /XML 2>&1) | Out-String
    Block 'schtasks /Query /XML (as stored)' $stored
    Check 'Task Scheduler kept RestartOnFailure' ($stored -match '<RestartOnFailure>' -and $stored -match 'PT1M')

    # ---- 4. the page answers ----
    Say "### 4. page"
    Check "page answers 200 on $Url within 60 s" (Wait-Page 60)
    $s = & jobwatch service status 2>&1
    Block 'jobwatch service status' $s
    Check 'service status says running' (($s | Out-String) -match '^running')
    Check 'service status names the url' (($s | Out-String) -match "http://jobwatch\.localhost:$Port/")
    Block 'ui.log' (Get-Content $logPath -ErrorAction SilentlyContinue)
    Check 'ui.log was written by --log' ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt 0))

    # ---- 5. kill it, see whether the task brings it back ----
    Say "### 5. kill the process; does RestartOnFailure bring it back?"
    # Task Scheduler's history log is off by default; turn it on (the runner is an administrator) to see what it does.
    $historyLog = (Get-WinEvent -ListLog '*TaskScheduler/Operational' -ErrorAction SilentlyContinue).LogName
    if ($historyLog) { wevtutil set-log $historyLog /enabled:true 2>&1 | Out-Null }
    $before = @(Ui-Processes)
    Block 'ui processes before the kill' ($before | Select-Object ProcessId, Name, ParentProcessId, CommandLine | Format-List)
    Check 'found the page process to kill' ($before.Count -gt 0)
    $oldIds = @($before | ForEach-Object { $_.ProcessId })
    $before | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    $killedAt = Get-Date
    Start-Sleep -Seconds 3
    Say "  port open 3 s after the kill: $(Port-Open)"
    Block 'task status 3 s after the kill' (Task-Status)
    $back = $false
    $timeline = @()
    while (((Get-Date) - $killedAt).TotalSeconds -lt 400) {  # the repeating trigger fires every 5 minutes
        $now = @(Ui-Processes | Where-Object { $oldIds -notcontains $_.ProcessId })
        $stat = (Task-Status | Select-String -Pattern '^(Status|Last Result):.*$' | ForEach-Object { $_.Line.Trim() }) -join ' | '
        $timeline += ("{0,4:N0} s  new processes: {1}  page: {2}  {3}" -f ((Get-Date) - $killedAt).TotalSeconds, $now.Count, (Get-Page), $stat)
        if ($now.Count -gt 0 -and (Get-Page) -eq 200) { $back = $true; break }
        Start-Sleep -Seconds 10
    }
    Block 'timeline after the kill (every 10 s)' $timeline
    $secs = [int]((Get-Date) - $killedAt).TotalSeconds
    # First run on a real runner: RestartOnFailure alone did NOT bring back a force-killed pythonw (the history log
    # said the task "successfully completed", last result -1, status Ready), hence the repeating trigger.
    Check "a killed page is started again within 5 minutes (it was back after $secs s)" $back
    $events = Get-WinEvent -LogName $historyLog -MaxEvents 60 -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -match $Task } | Sort-Object TimeCreated |
        ForEach-Object { '{0:HH:mm:ss}  {1,-4} {2}' -f $_.TimeCreated, $_.Id, ($_.Message -replace '\s+', ' ') }
    Block 'Task Scheduler history (Operational log; empty if the log is disabled on this runner)' $events
}
finally {
    # ---- 6. uninstall ----
    Say "### 6. uninstall"
    $out = & jobwatch service uninstall 2>&1
    $code = $LASTEXITCODE
    Block 'jobwatch service uninstall' $out
    Check 'uninstall exits 0' ($code -eq 0) "exit $code"
    Check 'uninstall says removed' (($out | Out-String) -match 'Removed')
    Start-Sleep -Seconds 3
    $gone = (schtasks /Query /TN $Task 2>&1 | Out-String)
    Check 'the task is gone' ($LASTEXITCODE -ne 0) $gone
    Check 'the XML file is removed' (-not (Test-Path $xmlPath))
    Check 'the port is closed' (-not (Port-Open))
    Check 'no page process is left' (@(Ui-Processes).Count -eq 0)
    $out = & jobwatch service uninstall 2>&1
    $code = $LASTEXITCODE
    Block 'second jobwatch service uninstall' $out
    Check 'a second uninstall is clean (exit 0, "Not installed.")' (($code -eq 0) -and (($out | Out-String) -match 'Not installed'))
    $s = & jobwatch service status 2>&1
    Check 'status after uninstall says not installed' (($s | Out-String) -match 'Not installed')
}

Say "`n### Not exercised here`nThe logon trigger firing and a reboot: a runner has no logon to wait for. Only the trigger's XML and ``schtasks /Run`` are checked."
if ($Failures.Count) { Say "`n**FAILED: $($Failures -join '; ')**"; exit 1 }
Say "`n**All checks passed.**"
