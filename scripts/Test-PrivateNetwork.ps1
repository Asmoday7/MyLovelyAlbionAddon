param([Parameter(Mandatory=$true)][string]$Report)
# Isolated Windows CI only. A self-built socket probe; no Albion, driver install or game packets.
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Dedicated elevated Windows runner required.' }
. (Join-Path $PSScriptRoot '../albion_trade_desk/windows/PrivateNetwork.ps1')
$folder = Join-Path ([IO.Path]::GetTempPath()) ('atd-network-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $folder | Out-Null
$exe = Join-Path $folder 'LocalPolicyProbe.exe'
$rule = 'AlbionTradeDesk-Test-' + [guid]::NewGuid().ToString('N')
$backup = Join-Path $folder 'audit.csv'
$profiles = @(Get-NetFirewallProfile | Select-Object Name,Enabled)
$listener = $null
$udp = $null
$probe = $null
$audited = $false
$failure = $null
try {
    # Generated from this repository's source. This is NOT AOD or any downloaded executable.
    $source = @'
using System;
using System.Net;
using System.Net.Sockets;
class LocalPolicyProbe {
    static void Main(string[] args) {
        using (var tcp = new TcpClient()) { tcp.Connect("127.0.0.1", int.Parse(args[0])); }
        using (var udp = new UdpClient()) { udp.Send(new byte[]{1},1,"127.0.0.1",int.Parse(args[1])); }
        // Documentation-only addresses, expected blocked before any packet leaves this process.
        using (var tcp = new TcpClient()) {
            try { var pending=tcp.BeginConnect("198.51.100.1",443,null,null); if(pending.AsyncWaitHandle.WaitOne(2500)) tcp.EndConnect(pending); }
            catch(SocketException) { }
        }
        using (var udp = new UdpClient()) { try { udp.Send(new byte[]{1},1,"198.51.100.1",9); } catch(SocketException) { } }
    }
}
'@
    Add-Type -TypeDefinition $source -OutputAssembly $exe -OutputType ConsoleApplication
    auditpol.exe /backup /file:$backup | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot backup temporary runner audit policy.' }
    $audited = $true
    auditpol.exe /set '/subcategory:{0CCE9226-69AE-11D9-BED3-505054503030}' /failure:enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enable WFP connection failure events.' }
    auditpol.exe /set '/subcategory:{0CCE9225-69AE-11D9-BED3-505054503030}' /failure:enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enable WFP packet drop events.' }
    Set-NetFirewallProfile -Name Domain,Private,Public -Enabled True
    New-PrivateProtection $rule $exe
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
    $listener.Start()
    $tcpPort=$listener.LocalEndpoint.Port
    $udp = New-Object Net.Sockets.UdpClient(0)
    $udp.Client.ReceiveTimeout=5000
    $udpPort=$udp.Client.LocalEndPoint.Port
    $tcpAccept=$listener.AcceptTcpClientAsync()
    $begin=[DateTime]::Now
    $probe=Start-Process -FilePath $exe -ArgumentList @($tcpPort,$udpPort) -PassThru
    if (-not $tcpAccept.Wait(10000)) { throw 'Protection broke TCP loopback.' }
    $accepted=$tcpAccept.Result; $accepted.Dispose()
    $remote = New-Object Net.IPEndPoint([Net.IPAddress]::Any,0)
    $data=$udp.Receive([ref]$remote)
    if ($data.Length -ne 1) { throw 'Protection broke UDP loopback.' }
    if (-not $probe.WaitForExit(15000)) { throw 'Network probe timed out.' }
    if ($probe.ExitCode -ne 0) { throw 'Network probe failed.' }
    $blocked=@()
    for ($attempt=0; $attempt -lt 10; $attempt++) {
        $blocked=@(Get-WinEvent -FilterHashtable @{LogName='Security';Id=5152,5157;StartTime=$begin} -ErrorAction SilentlyContinue | ForEach-Object {
            $xml=[xml]$_.ToXml();$fields=@{}
            foreach($entry in $xml.Event.EventData.Data){$fields[[string]$entry.Name]=[string]$entry.'#text'}
            if ($fields.Application -like '*localpolicyprobe.exe' -and $fields.DestAddress -eq '198.51.100.1') {
                # Publish only this synthetic process's protocol/destination, never unrelated events.
                [pscustomobject]@{ protocol=$fields.Protocol; destination=$fields.DestAddress; event_id=$_.Id }
            }
        })
        if (@($blocked | Where-Object protocol -eq '6').Count -and @($blocked | Where-Object protocol -eq '17').Count) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not @($blocked | Where-Object protocol -eq '6').Count) { throw 'No WFP evidence of TCP blocking for probe.' }
    if (-not @($blocked | Where-Object protocol -eq '17').Count) { throw 'No WFP evidence of UDP blocking for probe.' }
    # Changing a filter must invalidate the same policy checker used by the real guardian.
    $filter=Get-NetFirewallAddressFilter -AssociatedNetFirewallRule (Get-NetFirewallRule -Name $rule)
    $filter | Set-NetFirewallAddressFilter -RemoteAddress '198.51.100.1'
    $detected=$false
    try { Assert-PrivateProtection $rule $exe } catch { $detected=$true }
    if (-not $detected) { throw 'Address filter tampering was not detected.' }
    @{windows=[Environment]::OSVersion.VersionString;loopback_tcp=$true;loopback_udp=$true;
      external_tcp_blocked=$true;external_udp_blocked=$true;wfp_events=$blocked;tamper_detected=$true;
      tested_program='self-built synthetic probe';game_tested=$false;aod_tested=$false;full_client_privacy_certified=$false} |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Report -Encoding UTF8
} catch {
    $failure=$_
} finally {
    if ($probe -and -not $probe.HasExited) { $probe.Kill();$probe.WaitForExit() }
    if ($listener) { $listener.Stop() }
    if ($udp) { $udp.Dispose() }
    Get-NetFirewallRule -Name $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    foreach($profile in $profiles){Set-NetFirewallProfile -Name $profile.Name -Enabled $profile.Enabled}
    if ($audited) {
        auditpol.exe /restore /file:$backup | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to restore runner audit policy.' }
    }
    Remove-Item -LiteralPath $folder -Recurse -Force
}
if ($failure) { throw $failure }
