"""Read-only network inventory and bounded connectivity probes for Windows."""

from datetime import datetime

from .network_probes import collect_dns_checks, collect_ping_checks
from .powershell import run_powershell


# Embedded for PyInstaller --onefile; no script or third-party runtime needed.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$issues = [Collections.Generic.List[object]]::new()
function Read-Data($source, [scriptblock]$query) {
    try { & $query } catch { $issues.Add(@{Source=$source; Error=$_.ToString()}) }
}
$adapters = @(Read-Data 'Adapters' { Get-NetAdapter })
$addresses = @(Read-Data 'Addresses' { Get-NetIPAddress })
$interfaces = @(Read-Data 'Interfaces' { Get-NetIPInterface })
$dns = @(Read-Data 'DNS configuration' { Get-DnsClientServerAddress })
$clients = @(Read-Data 'DNS suffix' { Get-DnsClient })
$globalDNS = Read-Data 'Global DNS' { Get-DnsClientGlobalSetting }
$identity = Read-Data 'Network identity' { [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties() }
$routes = @(Read-Data 'Routes' { Get-NetRoute | Where-Object DestinationPrefix -in @('0.0.0.0/0', '::/0') })
$profiles = @(Read-Data 'Windows connectivity' { Get-NetConnectionProfile })
$configs = @(Read-Data 'DHCP' { Get-CimInstance Win32_NetworkAdapterConfiguration -OperationTimeoutSec 6 })
$before = @(Read-Data 'Traffic' { Get-NetAdapterStatistics })
$timer = [Diagnostics.Stopwatch]::StartNew()
Start-Sleep -Milliseconds 1000
$after = @(Read-Data 'Traffic' { Get-NetAdapterStatistics })
$timer.Stop()
$rows = @($adapters | Sort-Object ifIndex | ForEach-Object {
    $a = $_
    $ip = @($addresses | Where-Object InterfaceIndex -eq $a.ifIndex)
    $int = @($interfaces | Where-Object InterfaceIndex -eq $a.ifIndex)
    $config = $configs | Where-Object InterfaceIndex -eq $a.ifIndex | Select-Object -First 1
    $ipv4Interface = $int | Where-Object AddressFamily -eq IPv4 | Select-Object -First 1
    $profile = $profiles | Where-Object InterfaceIndex -eq $a.ifIndex | Select-Object -First 1
    $old = $before | Where-Object Name -eq $a.Name | Select-Object -First 1
    $new = $after | Where-Object Name -eq $a.Name | Select-Object -First 1
    $send = $null; $receive = $null
    if ($old -and $new -and $timer.Elapsed.TotalSeconds -gt 0) {
        $sent = [double]$new.SentBytes - [double]$old.SentBytes
        $received = [double]$new.ReceivedBytes - [double]$old.ReceivedBytes
        if ($sent -ge 0) { $send = $sent / $timer.Elapsed.TotalSeconds }
        if ($received -ge 0) { $receive = $received / $timer.Elapsed.TotalSeconds }
    }
    @{
        Name=$a.Name; Index=$a.ifIndex; Description=$a.InterfaceDescription
        Status=$a.Status.ToString(); MAC=$a.MacAddress; LinkSpeed=$a.LinkSpeed
        Virtual=$a.Virtual; Send=$send; Receive=$receive
        Profile=$(if ($profile) {$profile.NetworkCategory.ToString()})
        WindowsIPv4=$(if ($profile) {$profile.IPv4Connectivity.ToString()})
        WindowsIPv6=$(if ($profile) {$profile.IPv6Connectivity.ToString()})
        IPv4=@($ip | Where-Object AddressFamily -eq IPv4 | ForEach-Object {
            @{Address=$_.IPAddress; Prefix=$_.PrefixLength; State=$_.AddressState.ToString(); Origin=$_.PrefixOrigin.ToString()}
        })
        IPv6=@($ip | Where-Object AddressFamily -eq IPv6 | ForEach-Object {
            @{Address=$_.IPAddress; Prefix=$_.PrefixLength; State=$_.AddressState.ToString(); Origin=$_.PrefixOrigin.ToString()}
        })
        DNS=@($dns | Where-Object InterfaceIndex -eq $a.ifIndex | ForEach-Object ServerAddresses | Select-Object -Unique)
        Suffix=($clients | Where-Object InterfaceIndex -eq $a.ifIndex | Select-Object -First 1).ConnectionSpecificSuffix
        RegisterDNS=($clients | Where-Object InterfaceIndex -eq $a.ifIndex | Select-Object -First 1).RegisterThisConnectionsAddress
        DHCPv4=$(if ($ipv4Interface) {$ipv4Interface.Dhcp.ToString()})
        DHCPServer=$config.DHCPServer
        LeaseObtained=$(if ($config.DHCPLeaseObtained) {$config.DHCPLeaseObtained.ToString('yyyy-MM-dd HH:mm:ss')})
        LeaseExpires=$(if ($config.DHCPLeaseExpires) {$config.DHCPLeaseExpires.ToString('yyyy-MM-dd HH:mm:ss')})
        Gateways=@($routes | Where-Object InterfaceIndex -eq $a.ifIndex | ForEach-Object NextHop | Select-Object -Unique)
    }
})
$routeRows = @($routes | ForEach-Object {
    $r = $_
    $i = $interfaces | Where-Object { $_.InterfaceIndex -eq $r.InterfaceIndex -and $_.AddressFamily -eq $r.AddressFamily } | Select-Object -First 1
    [pscustomobject]@{Prefix=$r.DestinationPrefix; Gateway=$r.NextHop; Interface=$r.InterfaceAlias;
      Index=$r.InterfaceIndex; Metric=([int]$r.RouteMetric + [int]$i.InterfaceMetric)}
} | Sort-Object Metric)
$checks = [Collections.Generic.List[object]]::new()
$hostName = 'www.msftconnecttest.com'
$async = $null
try {
    $async = [Net.Dns]::BeginGetHostAddresses($hostName, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne(4000)) { throw [TimeoutException]::new('DNS lookup timed out after 4 seconds.') }
    $resolved = [Net.Dns]::EndGetHostAddresses($async)
    $checks.Add(@{Name='DNS'; Target=$hostName; Status='OK'; Result=(@($resolved | ForEach-Object IPAddressToString) -join ', ')})
} catch { $checks.Add(@{Name='DNS'; Target=$hostName; Status='FAILED'; Error=$_.ToString()}) }
finally { if ($async) { $async.AsyncWaitHandle.Close() } }
$tcp = [Net.Sockets.TcpClient]::new()
try {
    $task = $tcp.ConnectAsync('1.1.1.1', 443)
    if (-not $task.Wait(3000)) { throw [TimeoutException]::new('TCP connection timed out after 3 seconds.') }
    $checks.Add(@{Name='Public TCP'; Target='1.1.1.1:443'; Status='OK'; Result='Connected'})
} catch { $checks.Add(@{Name='Public TCP'; Target='1.1.1.1:443'; Status='WARNING'; Error=$_.ToString()}) }
finally { $tcp.Close() }
$url = 'http://www.msftconnecttest.com/connecttest.txt'
$response = $null; $reader = $null
try {
    $request = [Net.HttpWebRequest]::Create($url)
    $request.Timeout = 4000; $request.ReadWriteTimeout = 4000
    $request.AllowAutoRedirect = $false
    $response = $request.GetResponse()
    $reader = [IO.StreamReader]::new($response.GetResponseStream())
    $buffer = [char[]]::new(256)
    $count = $reader.Read($buffer, 0, $buffer.Length)
    $body = [string]::new($buffer, 0, $count)
    if ([int]$response.StatusCode -eq 200 -and $body.Trim() -eq 'Microsoft Connect Test') {
        $checks.Add(@{Name='Internet'; Target=$url; Status='OK'; Result='Expected response received'})
    } else {
        $checks.Add(@{Name='Internet'; Target=$url; Status='WARNING'; Result="HTTP $([int]$response.StatusCode): unexpected response (possible sign-in page or filtering)"})
    }
} catch { $checks.Add(@{Name='Internet'; Target=$url; Status='FAILED'; Error=$_.ToString()}) }
finally { if ($reader) {$reader.Dispose()}; if ($response) {$response.Close()} }
$gatewayTargets = @($routeRows | Where-Object { $_.Gateway -and $_.Gateway -notin @('0.0.0.0', '::') } |
    Select-Object -Property Gateway, Index -Unique | Select-Object -First 4)
$proxy = Read-Data 'Proxy' { Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' }
@{
    Adapters=$rows; Routes=$routeRows; Checks=@($checks); PingTargets=$gatewayTargets
    Identity=@{HostName=$identity.HostName; PrimarySuffix=$identity.DomainName; SearchList=@($globalDNS.SuffixSearchList)}
    Proxy=@{UserProxyEnabled=[bool]$proxy.ProxyEnable; PACConfigured=[bool]$proxy.AutoConfigURL}
    Errors=@($issues)
} | ConvertTo-Json -Depth 8 -Compress
"""


def collect_network_snapshot():
    data = run_powershell(SCRIPT, timeout=60)
    data["DNSChecks"] = collect_dns_checks(data.get("Adapters") or [])
    data["Checks"].extend(collect_ping_checks(data.pop("PingTargets", []) or []))
    data["CollectedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return data
