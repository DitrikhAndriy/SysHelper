"""Current resource readings, separate from the computer passport."""

from ..collectors.inventory import collect_snapshot
import math
from ..report_utils import NA, add_errors, block, first, row, size, volume_title


def collect_hardware():
    return format_hardware(collect_snapshot("Hardware"))


def format_hardware(data):
    performance = first(data, "CPUPerformance")
    loads = [cpu["LoadPercentage"] for cpu in data.get("CPU") or [] if cpu.get("LoadPercentage") is not None]
    usage = performance.get("PercentProcessorUtility")
    if usage is None and loads:
        usage = sum(loads) / len(loads)
    frequency, scaling = performance.get("ProcessorFrequency"), performance.get("PercentProcessorPerformance")
    speed = frequency * scaling / 100 if frequency and scaling is not None else None
    sensors = data.get("Sensors") or []
    cpu_rows = [row("Usage", f"{min(100, usage):.0f}%" if usage is not None else NA),
                row("Speed", f"{speed / 1000:.2f} GHz (sampled)" if speed else NA)]
    stats = first(data, "SystemStats")
    cpu_details = cpu_rows + [row("Processes", data.get("ProcessCount")), row("Threads", stats.get("ThreadCount")), row("Handles", stats.get("HandleCount"))]
    total, free = data.get("MemoryTotal"), data.get("MemoryFree")
    memory_rows = [row("Usable", NA), row("Used", NA), row("Available", NA)]
    if total and free is not None:
        used = max(0, total - free)
        memory_rows = [row("Usable", size(total * 1024)), row("Used", f"{size(used * 1024)} · {used / total * 100:.0f}%"), row("Available", size(free * 1024))]
    memory_details = list(memory_rows)
    installed = sum(module.get("Capacity") or 0 for module in data.get("Memory") or [])
    if installed and total:
        memory_details.append(row("HW reserved", f"{max(0, installed - total * 1024) / 1024 ** 2:.0f} MB"))
    mem = first(data, "MemoryPerformance")
    committed, limit = mem.get("CommittedBytes"), mem.get("CommitLimit")
    memory_details.append(row("Committed", f"{size(committed)} / {size(limit)}" if committed is not None and limit is not None else NA))
    cache_fields = ("CacheBytes", "StandbyCacheCoreBytes", "StandbyCacheNormalPriorityBytes", "StandbyCacheReserveBytes")
    cached = sum(mem[key] for key in cache_fields) if all(mem.get(key) is not None for key in cache_fields) else None
    memory_details.extend([row("Cached", size(cached)), row("Paged pool", size(mem.get("PoolPagedBytes"))), row("Nonpaged pool", size(mem.get("PoolNonpagedBytes")))])
    gpu_brief, gpu_details = [], []
    for gpu in data.get("DXGI") or []:
        reading = [row("GPU", gpu.get("Name")),
                   row("3D usage", f"{gpu['Usage']}%" if gpu.get("Usage") is not None else NA),
                   row("VRAM used", size(gpu.get("VRAMUsed")))]
        gpu_brief.extend(reading)
        gpu_details.extend(reading + [row("VRAM usable", size(gpu.get("Usable", gpu.get("Dedicated")))), row("Shared limit", size(gpu.get("Shared"))),
                           row("Core clock", f"{gpu['CoreClock']:.0f} MHz" if gpu.get("CoreClock") is not None else NA),
                           row("Memory clock", f"{gpu['MemoryClock']:.0f} MHz" if gpu.get("MemoryClock") is not None else NA),
                           row("Fan", f"{gpu['FanRPM']} RPM" if gpu.get("FanRPM") is not None else NA)])
        gpu_details.extend(row("Sensor error", error) for error in gpu.get("ReadingErrors") or [])
        if gpu.get("Error"):
            gpu_details.append(row("GPU query", gpu["Error"]))
    disks, disk_details = [], []
    for volume in data.get("Volumes") or []:
        capacity, remaining = volume.get("Size"), volume.get("FreeSpace")
        percent = remaining / capacity * 100 if capacity and remaining is not None else None
        warning = "   [WARNING: Low free space]" if percent is not None and percent < 10 else ""
        disks.append(row(volume.get("DeviceID", "Volume"), f"{size(remaining)} free / {size(capacity)}{warning}"))
        disk_details.extend([volume_title(volume), row("  Free", size(remaining) + (f" · {percent:.0f}%" if percent is not None else "") + warning),
                             row("  Used", size(capacity - remaining) if capacity is not None and remaining is not None else NA), ""])
    storage_brief, storage_details = [], []
    for disk in data.get("StorageSensors") or []:
        title = f"Disk {disk.get('Index', '?')} · {disk.get('Name') or 'Unknown'}"
        rows = [title, row("  Health", disk.get("Health"))]
        storage_brief.extend(rows + [""])
        storage_details.extend(rows + [row("  Wear", f"{disk['Wear']}% used" if disk.get("Wear") is not None else NA),
                                      row("  Power-on", f"{disk['Hours']} hours" if disk.get("Hours") is not None else NA),
                                      row("  Read errors", disk.get("ReadErrors")), row("  Write errors", disk.get("WriteErrors")), ""])
    activity = first(data, "DiskActivity")
    activity_rows = [row(label, f"{activity[field] / 1024 ** 2:.1f} MB/s" if activity.get(field) is not None else NA)
                     for label, field in (("Read", "DiskReadBytesPersec"), ("Write", "DiskWriteBytesPersec"))]
    brief = [block("PROCESSOR", cpu_rows), block("MEMORY", memory_rows), block("GRAPHICS", gpu_brief or [row("GPU", NA)]),
             block("DISK SPACE", disks or [row("Volumes", NA)]), block("STORAGE", storage_brief or [row("Sensors", NA)])]
    detailed = [block("PROCESSOR", cpu_details), block("MEMORY", memory_details), block("GRAPHICS", gpu_details or [row("GPU", NA)]),
                block("DISK SPACE", disk_details or [row("Volumes", NA)]), block("STORAGE", storage_details or [row("Sensors", NA)]), block("DISK ACTIVITY", activity_rows)]
    # Reserved for future temperature/voltage collectors; never infer sensor values.
    deferred = block("SENSORS", [row("Temperatures", "[NOT IMPLEMENTED]"), row("Voltages", "[NOT IMPLEMENTED]")])
    brief.append(deferred)
    detailed.append(deferred)
    extra = []
    for sensor in sensors:
        item = sensor.get("Value")
        if not isinstance(item, (int, float)) or not math.isfinite(item):
            continue
        sensor_type = sensor.get("SensorType")
        suffix = {"Fan": "RPM", "Power": "W"}.get(sensor_type)
        if not suffix:
            continue
        extra.append(row(sensor.get("Name") or "Sensor", f"{item:.1f} {suffix} · {sensor.get('Parent', '')}"))
    if extra:
        detailed.append(block("FANS & POWER", extra))
    battery = data.get("Battery")
    if battery:
        rows = [row("Charge", f"{battery['Charge']}%" if battery.get("Charge") is not None else NA), row("Power source", battery.get("Source")), row("Status", battery.get("Status"))]
        brief.append(block("BATTERY", rows))
        detailed.append(block("BATTERY", rows))
    add_errors(data, brief, detailed, {"Win32_Processor", "Win32_PerfFormattedData_Counters_ProcessorInformation", "Win32_PerfFormattedData_PerfProc_Process", "Win32_OperatingSystem", "Win32_PhysicalMemory", "Win32_PerfFormattedData_PerfOS_Memory", "Win32_PerfFormattedData_PerfDisk_PhysicalDisk", "Win32_LogicalDisk", "DXGI", "Battery", "Storage sensors", "Sensor provider"})
    return "\n\n".join(brief), "\n\n".join(detailed)
