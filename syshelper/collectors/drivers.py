"""Read-only installed PnP driver inventory for currently present devices."""

from datetime import datetime

from .powershell import run_powershell


SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$issues = [Collections.Generic.List[object]]::new()
function Read-Data($source, [scriptblock]$query) {
    try { & $query } catch { $issues.Add(@{Source=$source; Error=$_.ToString()}) }
}
$present = @(Read-Data 'Present devices' { Get-PnpDevice -PresentOnly })
$entities = @(Read-Data 'Device status' { Get-CimInstance Win32_PnPEntity -OperationTimeoutSec 10 })
$drivers = @(Read-Data 'Driver inventory' { Get-CimInstance Win32_PnPSignedDriver -OperationTimeoutSec 10 })
$rows = @($present | ForEach-Object {
    $device = $_
    $entity = $entities | Where-Object DeviceID -eq $device.InstanceId | Select-Object -First 1
    @{Name=$device.FriendlyName; ID=$device.InstanceId; Class=$device.Class; Status=$device.Status.ToString();
      Code=$entity.ConfigManagerErrorCode; Service=$entity.Service; Manufacturer=$entity.Manufacturer}
})
@{
    Devices=$rows
    Drivers=@($drivers | Select-Object DeviceID, DeviceName, DriverVersion, DriverProviderName, InfName, IsSigned, Signer,
        @{n='Date';e={
            if ($_.DriverDate -is [datetime]) { $_.DriverDate.ToString('yyyy-MM-dd') }
            elseif ($_.DriverDate -match '^\d{8}') { $_.DriverDate.Substring(0,4) + '-' + $_.DriverDate.Substring(4,2) + '-' + $_.DriverDate.Substring(6,2) }
        }})
    Errors=@($issues)
} | ConvertTo-Json -Depth 6 -Compress
"""


def collect_drivers_snapshot():
    data = run_powershell(SCRIPT, timeout=60)
    for driver in data.get("Drivers") or []:
        driver["Date"] = driver.get("Date") or None
    data["CollectedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return data
