"""Bounded DNS queries and small ICMP samples, without changing configuration."""

import base64
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import subprocess

from .powershell import run_powershell


DNS_HOST = "www.msftconnecttest.com"
PUBLIC_DNS = {
    "Cloudflare": ("1.1.1.1", "1.0.0.1"),
    "Google": ("8.8.8.8", "8.8.4.4"),
    "Quad9": ("9.9.9.9", "149.112.112.112"),
}


def query_dns(server):
    """Query the specified resolver, not merely its ping or TCP status."""
    try:
        # Validate before embedding an address in PowerShell, including IPv6 scope.
        address = ipaddress.ip_address(server)
        if isinstance(address, ipaddress.IPv6Address) and address.scope_id and not address.scope_id.isdigit():
            raise ValueError("DNS IPv6 scope must be an interface index.")
        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$watch = [Diagnostics.Stopwatch]::StartNew()
try {
    $answers = @(Resolve-DnsName -Name 'www.msftconnecttest.com' -Type A -Server '__SERVER__' -DnsOnly -NoHostsFile -QuickTimeout |
        Where-Object IPAddress | ForEach-Object IPAddress | Select-Object -Unique)
    $watch.Stop()
    if ($answers.Count -eq 0) { throw 'DNS response contained no IPv4 addresses.' }
    @{Status='OK'; Milliseconds=$watch.Elapsed.TotalMilliseconds; Addresses=$answers} | ConvertTo-Json -Compress
} catch {
    @{Status='FAILED'; Error=$_.ToString()} | ConvertTo-Json -Compress
}
""".replace("__SERVER__", str(address))
        return run_powershell(script, timeout=8)
    except subprocess.TimeoutExpired:
        return {"Status": "TIMEOUT", "Error": "DNS query process exceeded 8 seconds."}
    except (OSError, ValueError, RuntimeError) as error:
        return {"Status": "ERROR", "Error": str(error)}


def collect_dns_checks(adapters):
    targets = {}
    for adapter in adapters:
        if adapter.get("Status") != "Up":
            continue
        for server in adapter.get("DNS") or []:
            target = targets.setdefault(server, {"Server": server, "ConfiguredOn": []})
            if adapter["Name"] not in target["ConfiguredOn"]:
                target["ConfiguredOn"].append(adapter["Name"])
    for provider, servers in PUBLIC_DNS.items():
        for server in servers:
            targets.setdefault(server, {"Server": server, "ConfiguredOn": []})["Provider"] = provider
    # A configured public resolver is queried once and reused in both report groups.
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(query_dns, targets))
    return [dict(target, Host=DNS_HOST, **result) for target, result in zip(targets.values(), results)]


PING_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$samples = @($targets | ForEach-Object {
    @{Name=$_.Name; Target=$_.Target; Times=[Collections.Generic.List[long]]::new();
      Replies=[Collections.Generic.List[string]]::new(); Errors=[Collections.Generic.List[string]]::new(); Sent=0}
})
for ($round = 0; $round -lt 4; $round++) {
    $pending = @($samples | ForEach-Object {
        $sample = $_
        $ping = [Net.NetworkInformation.Ping]::new()
        $sample.Sent++
        try { @{Sample=$sample; Ping=$ping; Task=$ping.SendPingAsync([string]$sample.Target, 1000)} }
        catch { $sample.Errors.Add($_.ToString()); $ping.Dispose() }
    })
    foreach ($item in $pending) {
        try {
            $reply = $item.Task.GetAwaiter().GetResult()
            $item.Sample.Replies.Add($reply.Status.ToString())
            if ($reply.Status -eq 'Success') { $item.Sample.Times.Add($reply.RoundtripTime) }
        } catch { $item.Sample.Errors.Add($_.ToString()) }
        finally { $item.Ping.Dispose() }
    }
    if ($round -lt 3) { Start-Sleep -Milliseconds 200 }
}
@($samples | ForEach-Object {
    $received = $_.Times.Count
    $average = $null; $minimum = $null; $maximum = $null
    if ($received) {
        $stats = $_.Times | Measure-Object -Average -Minimum -Maximum
        $average = $stats.Average; $minimum = $stats.Minimum; $maximum = $stats.Maximum
    }
    @{Name=$_.Name; Target=$_.Target; Sent=$_.Sent; Received=$received;
      Loss=100 * ($_.Sent - $received) / $_.Sent; Average=$average; Minimum=$minimum; Maximum=$maximum;
      Status=$(if ($_.Errors.Count) {'ERROR'} elseif ($received -eq $_.Sent) {'OK'} else {'WARNING'});
      Replies=@($_.Replies); Errors=@($_.Errors)}
}) | ConvertTo-Json -Depth 5 -Compress
"""


def collect_ping_checks(gateways):
    targets = []
    for route in gateways[:4]:
        target = str(route["Gateway"])
        if ipaddress.ip_address(target).is_link_local and ":" in target and "%" not in target:
            target += f"%{int(route['Index'])}"
        targets.append({"Name": "Gateway", "Target": target})
    targets.append({"Name": "Public ping", "Target": "1.1.1.1"})
    # Base64 JSON avoids shell quoting and executes through PowerShell's JSON parser.
    encoded = base64.b64encode(json.dumps(targets).encode("utf-8")).decode("ascii")
    setup = "$targets = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "')) | ConvertFrom-Json\n"
    try:
        results = run_powershell(setup + PING_SCRIPT, timeout=12)
        return results if isinstance(results, list) else [results]
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        return [dict(target, Status="ERROR", Error=str(error)) for target in targets]
