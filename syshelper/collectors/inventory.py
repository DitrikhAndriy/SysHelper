"""Shared read-only Windows inventory. No third-party packages."""

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
import subprocess

from .windows_info import gpu_inventory


NA = "[UNAVAILABLE]"

# Keep the query inside the module so a one-file executable needs no script assets.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$issues = [Collections.Generic.List[object]]::new()
function Read-Cim($class, $namespace = 'root/cimv2') {
    try { Get-CimInstance -ClassName $class -Namespace $namespace -OperationTimeoutSec 6 }
    catch { $issues.Add(@{Source=$class; Error=$_.ToString()}) }
}
$os = Read-Cim 'Win32_OperatingSystem'
$version = $null
try { $version = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion }
catch { $issues.Add(@{Source='Windows version'; Error=$_.ToString()}) }
$disks = @(Read-Cim 'Win32_DiskDrive')
$media = @(Read-Cim 'MSFT_PhysicalDisk' 'root/Microsoft/Windows/Storage')
$diskRows = @($disks | ForEach-Object {
    $disk = $_
    $matches = @($media | Where-Object {
        $disk.SerialNumber -and $_.SerialNumber -and
        $_.SerialNumber.Trim() -eq $disk.SerialNumber.Trim()
    })
    $type = $null
    if ($matches.Count -eq 1) { $type = $matches[0].MediaType }
    @{Index=$disk.Index; Model=$disk.Model; Size=$disk.Size; MediaType=$type}
})
$volumes = @(Read-Cim 'Win32_LogicalDisk' | Where-Object DriveType -eq 3 |
    Select-Object DeviceID, VolumeName, Size, FreeSpace, FileSystem)
$volumeRows = @($volumes | ForEach-Object {
    $volume = $_
    $indices = @()
    try {
        $partitions = @(Get-CimAssociatedInstance -InputObject (
            Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($volume.DeviceID)'"
        ) -Association Win32_LogicalDiskToPartition)
        $indices = @($partitions | Select-Object -ExpandProperty DiskIndex -Unique)
    } catch { $issues.Add(@{Source=$volume.DeviceID; Error=$_.ToString()}) }
    @{DeviceID=$volume.DeviceID; VolumeName=$volume.VolumeName; Size=$volume.Size;
      FreeSpace=$volume.FreeSpace; FileSystem=$volume.FileSystem; Disks=$indices}
})
$monitors = @(Read-Cim 'WmiMonitorID' 'root/wmi' | Where-Object Active | ForEach-Object {
    $name = -join @($_.UserFriendlyName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ })
    @{Name=$name; InstanceName=$_.InstanceName}
})
$result = @{
    Computer = @(Read-Cim 'Win32_ComputerSystem' | Select-Object Name, Manufacturer, Model, PCSystemType, PartOfDomain, Domain, Workgroup, DomainRole, DNSHostName)
    OS = @($os | Select-Object Caption, BuildNumber, OSArchitecture, WindowsDirectory,
        @{n='Installed';e={if ($_.InstallDate) {$_.InstallDate.ToString('yyyy-MM-dd HH:mm:ss')}}},
        @{n='LastBoot';e={if ($_.LastBootUpTime) {$_.LastBootUpTime.ToString('o')}}})
    Version = $version
    CPU = @(Read-Cim 'Win32_Processor' | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed, LoadPercentage, SocketDesignation, VirtualizationFirmwareEnabled, L2CacheSize, L3CacheSize)
    CPUPerformance = @(Read-Cim 'Win32_PerfFormattedData_Counters_ProcessorInformation' | Where-Object Name -eq '_Total' | Select-Object PercentProcessorUtility, PercentProcessorPerformance, ProcessorFrequency)
    Cache = @(Read-Cim 'Win32_CacheMemory' | Select-Object Level, InstalledSize)
    Memory = @(Read-Cim 'Win32_PhysicalMemory' | Select-Object DeviceLocator, Capacity, Manufacturer, SMBIOSMemoryType, ConfiguredClockSpeed, Speed, FormFactor)
    MemorySlots = @(Read-Cim 'Win32_PhysicalMemoryArray' | Select-Object MemoryDevices)
    MemoryTotal = $os.TotalVisibleMemorySize
    MemoryFree = $os.FreePhysicalMemory
    GPU = @(Read-Cim 'Win32_VideoController' | Select-Object Name)
    Disks = $diskRows
    Volumes = $volumeRows
    Board = @(Read-Cim 'Win32_BaseBoard' | Select-Object Manufacturer, Product)
    BIOS = @(Read-Cim 'Win32_BIOS' | Select-Object Manufacturer, SMBIOSBIOSVersion, SerialNumber,
        @{n='Date';e={if ($_.ReleaseDate) {$_.ReleaseDate.ToString('yyyy-MM-dd')}}})
    Monitors = $monitors
    Errors = $issues
}
$result | ConvertTo-Json -Depth 6 -Compress
"""

HARDWARE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$issues = [Collections.Generic.List[object]]::new()
function Read-Cim($class, $namespace = 'root/cimv2') {
    try { Get-CimInstance -ClassName $class -Namespace $namespace -OperationTimeoutSec 6 }
    catch { $issues.Add(@{Source=$class; Error=$_.ToString()}) }
}
$os = Read-Cim 'Win32_OperatingSystem'
$storage = @()
try {
    $storage = @(Get-Disk | ForEach-Object {
        $disk = $_
        $counter = $null
        try { $counter = $disk | Get-StorageReliabilityCounter }
        catch { $issues.Add(@{Source='Storage sensors'; Error="Disk $($disk.Number): $($_.ToString())"}) }
        @{Index=$disk.Number; Name=$disk.FriendlyName; Health=$disk.HealthStatus;
          Wear=$counter.Wear; Hours=$counter.PowerOnHours;
          ReadErrors=$counter.ReadErrorsUncorrected; WriteErrors=$counter.WriteErrorsUncorrected}
    })
} catch { $issues.Add(@{Source='Storage sensors'; Error=$_.ToString()}) }
$sensors = @()
foreach ($provider in @('LibreHardwareMonitor', 'OpenHardwareMonitor')) {
    try {
        $sensors += @(Get-CimInstance -Namespace "root/$provider" -ClassName Sensor -OperationTimeoutSec 3 |
            Where-Object { $_.SensorType -in @('Fan', 'Power') } |
            Select-Object Name, SensorType, Value, Parent, Identifier, @{n='Provider';e={$provider}})
    } catch {
        # An optional sensor provider is normally absent; keep actual access errors.
        if ($_.Exception.NativeErrorCode.ToString() -notin @('InvalidNamespace', 'InvalidClass')) {
            $issues.Add(@{Source='Sensor provider'; Error="$provider`: $($_.ToString())"})
        }
    }
}
@{
    CPU = @(Read-Cim 'Win32_Processor' | Select-Object Name, LoadPercentage)
    CPUPerformance = @(Read-Cim 'Win32_PerfFormattedData_Counters_ProcessorInformation' | Where-Object Name -eq '_Total' | Select-Object PercentProcessorUtility, PercentProcessorPerformance, ProcessorFrequency)
    SystemStats = @(Read-Cim 'Win32_PerfFormattedData_PerfProc_Process' | Where-Object Name -eq '_Total' | Select-Object ThreadCount, HandleCount)
    ProcessCount = @(Get-Process).Count
    Memory = @(Read-Cim 'Win32_PhysicalMemory' | Select-Object Capacity)
    MemoryTotal = $os.TotalVisibleMemorySize
    MemoryFree = $os.FreePhysicalMemory
    MemoryPerformance = @(Read-Cim 'Win32_PerfFormattedData_PerfOS_Memory' | Select-Object CommittedBytes, CommitLimit, CacheBytes, StandbyCacheCoreBytes, StandbyCacheNormalPriorityBytes, StandbyCacheReserveBytes, PoolPagedBytes, PoolNonpagedBytes)
    Volumes = @(Read-Cim 'Win32_LogicalDisk' | Where-Object DriveType -eq 3 | Select-Object DeviceID, VolumeName, Size, FreeSpace)
    DiskActivity = @(Read-Cim 'Win32_PerfFormattedData_PerfDisk_PhysicalDisk' | Where-Object Name -eq '_Total' | Select-Object DiskReadBytesPersec, DiskWriteBytesPersec)
    StorageSensors = $storage
    Sensors = $sensors
    Errors = $issues
} | ConvertTo-Json -Depth 6 -Compress
"""


def _display_modes():
    """Enumerate active Windows display sources, including resolution and refresh."""
    class DisplayDevice(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    class DevMode(ctypes.Structure):
        _fields_ = [("name", wintypes.WCHAR * 32), ("spec", wintypes.WORD),
                    ("version", wintypes.WORD), ("size", wintypes.WORD),
                    ("extra", wintypes.WORD), ("fields", wintypes.DWORD),
                    ("display_union", ctypes.c_byte * 16), ("color", wintypes.SHORT),
                    ("duplex", wintypes.SHORT), ("yres", wintypes.SHORT),
                    ("tt", wintypes.SHORT), ("collate", wintypes.SHORT),
                    ("form", wintypes.WCHAR * 32), ("dpi", wintypes.WORD),
                    ("bits", wintypes.DWORD), ("width", wintypes.DWORD),
                    ("height", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("frequency", wintypes.DWORD), ("icm", wintypes.DWORD),
                    ("intent", wintypes.DWORD), ("media", wintypes.DWORD),
                    ("dither", wintypes.DWORD), ("reserved1", wintypes.DWORD),
                    ("reserved2", wintypes.DWORD), ("panwidth", wintypes.DWORD),
                    ("panheight", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.POINTER(DisplayDevice), wintypes.DWORD]
    user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.POINTER(DevMode)]
    modes = []
    index = 0
    while True:
        device = DisplayDevice()
        device.cb = ctypes.sizeof(device)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        index += 1
        if not device.StateFlags & 1:
            continue
        mode = DevMode()
        mode.size = ctypes.sizeof(mode)
        if user32.EnumDisplaySettingsW(device.DeviceName, 0xFFFFFFFF, ctypes.byref(mode)):
            monitor_ids = []
            monitor_index = 0
            while True:
                monitor = DisplayDevice()
                monitor.cb = ctypes.sizeof(monitor)
                if not user32.EnumDisplayDevicesW(device.DeviceName, monitor_index, ctypes.byref(monitor), 1):
                    break
                monitor_index += 1
                if monitor.StateFlags & 1:
                    monitor_ids.append(monitor.DeviceID)
            modes.append({"Name": device.DeviceName, "Width": mode.width,
                          "Height": mode.height, "Hz": mode.frequency, "MonitorIDs": monitor_ids})
    return modes


def _battery():
    class PowerStatus(ctypes.Structure):
        _fields_ = [("AC", wintypes.BYTE), ("Flags", wintypes.BYTE),
                    ("Percent", wintypes.BYTE), ("Reserved", wintypes.BYTE),
                    ("Life", wintypes.DWORD), ("FullLife", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(PowerStatus)]
    status = PowerStatus()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    if status.Flags != 255 and status.Flags & 128:
        return None
    return {"Charge": status.Percent if status.Percent != 255 else None,
            "Source": {0: "Battery", 1: "AC adapter"}.get(status.AC, NA),
            "Status": NA if status.Flags == 255 else (
                "Charging" if status.Flags & 8 else "Not charging")}


def collect_snapshot(category="Overview"):
    """Collect only the requested category; no unrelated reports are refreshed."""
    if category not in ("Overview", "Hardware"):
        raise ValueError(f"Unknown category: {category}")
    if os.name != "nt":
        raise OSError("SysHelper currently supports Windows only.")
    executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    script = HARDWARE_SCRIPT if category == "Hardware" else SCRIPT
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or
                           f"PowerShell exited with code {result.returncode}.")
    data = json.loads(result.stdout.lstrip("\ufeff"))
    native = [("DXGI", lambda: gpu_inventory(include_readings=category == "Hardware"))]
    native.append(("Battery", _battery) if category == "Hardware" else ("DisplayModes", _display_modes))
    for name, collector in native:
        try:
            data[name] = collector()
        except OSError as error:
            data[name] = None
            data["Errors"].append({"Source": name, "Error": str(error)})
    data["CollectedAt"] = datetime.now().astimezone().isoformat()
    return data
