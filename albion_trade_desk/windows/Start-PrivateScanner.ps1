# Downloaded from the LOCAL Trade Desk UI after explicit experimental opt-in.
# No changes to the game, no packet capture implementation, no personal ingest.
$ErrorActionPreference = 'Stop'
if (-not (Get-Command Assert-PrivateProtection -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot 'PrivateNetwork.ps1')
}
$destination = if ($managed) { $managed.destination } else { '@@DESTINATION@@' }
$sessionId = if ($managed) { $managed.session_id } else { '@@SESSION_ID@@' }
Add-Type -AssemblyName System.Windows.Forms
if ($destination -eq '@@' + 'DESTINATION@@' -or $destination -notmatch '^http://127\.0\.0\.1:[0-9]{1,5}/private/(east|west|europe)/[A-Za-z0-9_-]+$') {
    throw 'Download this launcher from the active Private Market Scanner session first.'
}
$baseAddress = ([uri]$destination).GetLeftPart([System.UriPartial]::Authority)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    [System.Windows.Forms.MessageBox]::Show('Private Scanner needs administrator access to block external connections for the selected Data Client. It does not change the game. Windows will ask for permission.', 'Albion Trade Desk') | Out-Null
    Start-Process powershell.exe -Verb RunAs -ArgumentList @('-NoProfile', '-STA', '-File', ('"' + $PSCommandPath + '"'))
    exit
}
$mutex = New-Object System.Threading.Mutex($false, 'Global\AlbionTradeDesk.PrivateScanner')
if (-not $mutex.WaitOne(0)) { throw 'Another Private Scanner launcher is already running.' }
$child = $null
$rule = $null
$journal = $null
$sessionDir = $null
$failure = $null
$protectionActive = $false
$npcapAvailable = $false
$pausedTasks = @()
function Write-Audit($kind, $detail) {
    if ($journal) {
        @{ at = [DateTime]::UtcNow.ToString('o'); kind = $kind; detail = $detail } |
            ConvertTo-Json -Compress -Depth 5 | Add-Content -LiteralPath $journal -Encoding UTF8
    }
}
function Set-ManagedState($state, $errorText) {
    if ($managed) {
        $data = @{state=$state; error=$errorText; pid=$(if($child){$child.Id}else{$null});
            sha256=$hash; client_path=$script:client; firewall_active=$protectionActive; npcap=$npcapAvailable}
        $tmp = Join-Path $managed.folder 'state.tmp'
        $data | ConvertTo-Json | Set-Content -LiteralPath $tmp -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination (Join-Path $managed.folder 'state.json') -Force
    }
}
function Other-Clients($ignorePid = 0) {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $ignorePid -and
        ($_.Name -match '(?i)albion.*data.*client.*\.exe$' -or $_.ExecutablePath -eq $script:client)
    })
}
try {
    $sessionDir = if ($managed) { $managed.folder } else { Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('AlbionTradeDesk\PrivateScanner\' + [guid]::NewGuid().ToString('N')) }
    New-Item -ItemType Directory -Path $sessionDir -Force | Out-Null
    $journal = Join-Path $sessionDir 'network-audit.jsonl'
    $script:client = if ($managed) { $managed.client_path } else { '' }
    $expectedHash = if ($managed) { $managed.sha256 } else { '4feb2e2dd3c5e2e65f494581e3e5076b394a41bf777c936bc1bdfcc26fd1229c' }
    if (-not $client -or -not (Test-Path -LiteralPath $client)) {
        # The audited NSIS installer uses this exact registry key/default directory.
        $install = Get-ItemProperty -LiteralPath 'HKLM:\Software\Albion Data Client' -ErrorAction SilentlyContinue
        $candidates = @()
        if ($install -and $install.'(default)') { $candidates += Join-Path $install.'(default)' 'albiondata-client.exe' }
        $candidates += Join-Path $env:ProgramFiles 'Albion Data Client/albiondata-client.exe'
        foreach ($candidate in $candidates) {
            if ((Test-Path -LiteralPath $candidate) -and (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash -eq $expectedHash) {
                $script:client = (Resolve-Path -LiteralPath $candidate).ProviderPath
                break
            }
        }
    }
    if (-not $client -or -not (Test-Path -LiteralPath $client)) {
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Select the installed OFFICIAL albiondata-client.exe (not an installer)'
    $picker.Filter = 'Official Data Client (*.exe)|*.exe'
    if ($picker.ShowDialog() -ne 'OK') { throw 'Файл AOD не выбран. Повторите запуск и выберите установленный клиент.' }
    $script:client = (Resolve-Path -LiteralPath $picker.FileName).ProviderPath
    }
    if ($managed -and (Test-Path -LiteralPath (Join-Path $managed.folder 'stop'))) { throw 'Launch cancelled.' }
    $npcapAvailable = Test-Path -LiteralPath (Join-Path $env:SystemRoot 'System32/Npcap/wpcap.dll')
    if (-not $npcapAvailable) {
        throw 'Npcap не найден. Установите Npcap с https://npcap.com/#download, затем повторите запуск сборщика.'
    }
    $verified = (Get-FileHash -LiteralPath $client -Algorithm SHA256).Hash
    if ($verified -ne $expectedHash) { throw 'Файл не совпадает с проверенным AOD 0.1.61 x64. Выберите установленный exe официального релиза 0.1.61. Клиент не запущен.' }
    if ([IO.Path]::GetFileName($client) -notmatch '(?i)^albiondata-client.*\.exe$' -or $client -match '(?i)installer\.exe$') {
        throw 'Select the installed official client executable, not its installer or a renamed copy.'
    }
    if ((Other-Clients).Count -gt 0) {
        throw 'AOD уже запущен. Закройте его, включая значок в трее, затем повторите запуск. Чужой процесс не остановлен.'
    }
    $tasks = @(Get-ScheduledTask | Where-Object {
        $_.State -ne 'Disabled' -and
        ($_.TaskName -match '(?i)albion.*data.*client' -or
        @($_.Actions | Where-Object { $_.Execute -match '(?i)albion.*data.*client' -or $_.Execute -eq $client }).Count -gt 0)
    })
    $startup = @(Get-CimInstance Win32_StartupCommand | Where-Object { $_.Command -match '(?i)albion.*data.*client' })
    $directTasks = @($tasks | Where-Object {
        @($_.Actions).Count -eq 1 -and [Environment]::ExpandEnvironmentVariables([string]$_.Actions[0].Execute).Trim('"') -eq $client
    })
    if ($startup.Count -or $directTasks.Count -ne $tasks.Count) {
        throw 'Found a custom Data Client autostart entry. Disable that entry in Windows before using the private collector; unrelated startup settings will not be modified.'
    }
    if ($directTasks.Count) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            'The official AOD installer enabled normal autostart. Pause its scheduled task during private collection? It will be restored after this client stops. A crash may leave it paused; see the local audit log.',
            'Albion Trade Desk - AOD autostart', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { throw 'Private start cancelled; normal autostart was not changed.' }
        foreach ($task in $directTasks) {
            Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath | Out-Null
            $pausedTasks += @{name=$task.TaskName;path=$task.TaskPath}
        }
    }
    if (@(Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count -gt 0) {
        throw 'Windows Firewall profiles must be enabled. No client was started.'
    }
    $hash = (Get-FileHash -LiteralPath $client -Algorithm SHA256).Hash
    Write-Audit 'autostart-paused' @{ tasks = $pausedTasks }
    Write-Audit 'preflight' @{ client = $client; sha256 = $hash; rules_permission = 'unconfirmed'; live_game_verified = $false }
    # The official client reads config from its current directory. Isolate it from
    # existing config files and explicitly disable its separate WebSocket server.
    [IO.File]::WriteAllText((Join-Path $sessionDir 'config.json'), '{"EnableWebsockets":false,"AllowedWebsocketHosts":[]}', (New-Object System.Text.UTF8Encoding($false)))
    $rule = 'AlbionTradeDesk-Private-' + [guid]::NewGuid().ToString('N')
    $remote = @(Get-PrivateRemoteRanges)
    New-PrivateProtection $rule $client
    $protectionActive = $true
    Write-Audit 'firewall-active' @{ rule = $rule; remote_ranges = $remote }
    $health = Invoke-RestMethod -Uri ($baseAddress + '/api/private/status') -TimeoutSec 3
    if (-not $health.enabled -or $health.id -ne $sessionId) { throw 'This receiver session has ended. Download a new launcher.' }
    # A sole local public ingest target. Empty personalized ingest. DO NOT use -d:
    # DisableUpload would also stop delivery to the local HTTP receiver.
    $arguments = @('-i', $destination, '-p=')
    Write-Audit 'launch-policy' @{ destination = 'loopback-only'; personalized_ingest = 'empty'; websocket = $false; disable_upload = $false }
    if ($managed -and (Test-Path -LiteralPath (Join-Path $sessionDir 'stop'))) { throw 'Launch cancelled.' }
    if ((Other-Clients).Count -gt 0) { throw 'Another AOD instance started during setup. No private client was launched.' }
    $child = Start-Process -FilePath $client -ArgumentList $arguments -WorkingDirectory $sessionDir -PassThru
    Write-Host 'Private client started. Keep this window open. Close it with Ctrl+C to stop the client.'
    Write-Host ('Local audit folder: ' + $sessionDir)
    Write-Host 'Network verification is not certified; see docs/PRIVATE_SCANNER.md.'
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    Set-ManagedState 'waiting' $null
    while (-not $child.HasExited) {
        if ($managed -and (Test-Path -LiteralPath (Join-Path $sessionDir 'stop'))) { break }
        if ((Other-Clients $child.Id).Count -gt 0) { throw 'Another Data Client was detected. Stopping this private client.' }
        Assert-PrivateProtection $rule $client
        # WMI/NetTCPConnection only: never collect browser traffic or packet payloads.
        try { $connections = @(Get-NetTCPConnection -OwningProcess $child.Id -ErrorAction Stop) }
        catch {
            if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { $connections = @() }
            else { throw }
        }
        foreach ($connection in $connections) {
            $key = '{0}:{1}:{2}' -f $connection.RemoteAddress, $connection.RemotePort, $connection.State
            if ($seen.Add($key)) {
                Write-Audit 'tcp-observation' @{ address = $connection.RemoteAddress; port = $connection.RemotePort; state = [string]$connection.State }
            }
            if ($connection.State -eq 'Established' -and
                $connection.RemoteAddress -notin @('127.0.0.1', '::1', '::ffff:127.0.0.1')) {
                throw 'An external established connection was observed. Private verification FAILED.'
            }
        }
        # A stopped receiver/session should also stop the supervised client.
        $health = Invoke-RestMethod -Uri ($baseAddress + '/api/private/status') -TimeoutSec 3
        if (-not $health.enabled -or $health.id -ne $sessionId) {
            throw 'Private receiver session is no longer active.'
        }
        Start-Sleep -Milliseconds 250
        $child.Refresh()
    }
    if (-not ($managed -and (Test-Path -LiteralPath (Join-Path $sessionDir 'stop')))) {
        throw 'AOD exited. See the local log; capture may require Npcap or WebView2.'
    }
} catch {
    $failure = $_.Exception.Message
    Write-Audit 'error' @{ message = $_.Exception.Message }
} finally {
    $safeToRemoveRule = $true
    if ($child -and -not $child.HasExited) {
        try { Stop-Process -Id $child.Id -Force; $child.WaitForExit(5000) | Out-Null; $child.Refresh() }
        catch { $safeToRemoveRule = $false }
        if (-not $child.HasExited) { $safeToRemoveRule = $false }
    }
    # An upstream updater can replace the original process. Never remove protection
    # while any process still uses the selected executable; do not kill foreign copies.
    if ($rule -and $safeToRemoveRule) {
        try {
            $remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $script:client })
            if ($remaining.Count) {
                $safeToRemoveRule = $false
                $failure = 'AOD replacement or another process is still running. Protection remains active; no foreign process was stopped.'
            }
        } catch {
            $safeToRemoveRule = $false
            $failure = 'Cannot verify all AOD processes have exited. Protection remains active.'
        }
    }
    if ($rule -and $safeToRemoveRule) {
        try {
            Remove-NetFirewallRule -Name $rule -ErrorAction Stop
            $protectionActive = $false
            Write-Audit 'cleanup' @{ firewall_rule_removed = $true }
        } catch {
            $failure = 'Не удалось снять защитное правило после остановки. Имя правила и причина сохранены в журнале.'
            Write-Audit 'cleanup' @{ firewall_rule_removed = $false; rule = $rule; reason = $_.Exception.Message }
            Write-Warning ('Check the retained protection rule manually: ' + $rule)
        }
    } elseif ($rule) {
        $failure = 'Остановка AOD не подтверждена. Защитное правило сохранено; проверьте журнал.'
        Write-Audit 'cleanup' @{ firewall_rule_retained = $rule; reason = 'client exit not confirmed' }
        Write-Warning ('Protection rule was retained because client exit is unknown: ' + $rule)
    }
    if ($safeToRemoveRule) {
        foreach ($task in $pausedTasks) {
            try { Enable-ScheduledTask -TaskName $task.name -TaskPath $task.path | Out-Null }
            catch { $failure = 'AOD stopped, but autostart restoration failed. See the local audit log.'; Write-Audit 'autostart-restore-error' @{message=$_.Exception.Message;task=$task} }
        }
    } elseif ($pausedTasks.Count) {
        Write-Audit 'autostart-retained-disabled' @{tasks=$pausedTasks;reason='client exit not confirmed'}
    }
    Set-ManagedState $(if ($failure) { 'error' } else { 'disabled' }) $failure
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
if ($failure -and -not $managed) {
    [System.Windows.Forms.MessageBox]::Show($failure, 'Private Scanner stopped') | Out-Null
}
