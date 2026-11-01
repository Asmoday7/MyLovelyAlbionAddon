# Network policy shared by the real guardian and the isolated Windows test probe.
function Get-PrivateRemoteRanges {
    @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
}
function Assert-PrivateProtection([string]$RuleName, [string]$ProgramPath) {
    if (@(Get-Service BFE,MpsSvc | Where-Object Status -ne 'Running').Count) { throw 'Windows filtering/firewall service is not running.' }
    if (@(Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count -gt 0) {
        throw 'Windows Firewall profiles must be enabled.'
    }
    $active = Get-NetFirewallRule -PolicyStore ActiveStore -Name $RuleName -ErrorAction Stop
    if ($active.Enabled -ne 'True' -or $active.Action -ne 'Block' -or $active.Direction -ne 'Outbound' -or $active.Profile -ne 'Any') {
        throw 'Firewall rule does not enforce all-profile outbound blocking.'
    }
    $application = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $active
    if ($application.Program -ne $ProgramPath) { throw 'Firewall application filter mismatch.' }
    $port = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $active
    if ([string]$port.Protocol -notin @('Any','256') -or $port.LocalPort -ne 'Any' -or $port.RemotePort -ne 'Any') {
        throw 'Firewall rule does not protect all protocols and ports.'
    }
    $address = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $active
    $expected = @(Get-PrivateRemoteRanges)
    if (@($address.RemoteAddress).Count -ne $expected.Count) { throw 'Firewall remote ranges mismatch.' }
    foreach ($range in $expected) {
        if ($address.RemoteAddress -notcontains $range) { throw 'Firewall remote ranges mismatch.' }
    }
    if ($address.LocalAddress -ne 'Any') { throw 'Firewall local address filter mismatch.' }
}
function New-PrivateProtection([string]$RuleName, [string]$ProgramPath) {
    New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Outbound -Action Block -Enabled True -Profile Any -Program $ProgramPath -Protocol Any -RemoteAddress (Get-PrivateRemoteRanges) | Out-Null
    Assert-PrivateProtection $RuleName $ProgramPath
}
