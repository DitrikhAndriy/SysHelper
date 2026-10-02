"""Computer identity and installed equipment. Live resource usage belongs to Hardware."""

from ..collectors.inventory import collect_snapshot
from ..report_utils import NA, add_errors, block, display_rows, first, row, size, uptime_rows, value, volume_title


def collect_overview():
    return format_overview(collect_snapshot())


def membership_rows(computer, detailed=False):
    """Do not interpret an unknown membership state as a workgroup."""
    joined = computer.get("PartOfDomain")
    if joined is True:
        rows = [row("Membership", "Domain joined"), row("Domain", computer.get("Domain"))]
    elif joined is False:
        rows = [row("Membership", "Workgroup"), row("Workgroup", computer.get("Workgroup") or computer.get("Domain"))]
    else:
        rows = [row("Membership", NA)]
    if detailed:
        roles = {0: "Standalone workstation", 1: "Member workstation", 2: "Standalone server",
                 3: "Member server", 4: "Backup domain controller", 5: "Primary domain controller"}
        rows.extend([row("Role", roles.get(computer.get("DomainRole"), NA)), row("DNS host", computer.get("DNSHostName"))])
    return rows


def format_overview(data, now=None):
    computer, system, bios, board = (first(data, key) for key in ("Computer", "OS", "BIOS", "Board"))
    kind = {1: "Desktop", 2: "Laptop", 3: "Workstation", 4: "Server", 5: "Server",
            6: "Server", 7: "Server", 8: "Tablet"}.get(computer.get("PCSystemType"), NA)
    model = " ".join(str(item).strip() for item in (computer.get("Manufacturer"), computer.get("Model")) if item)
    if model and kind != NA:
        model += " · " + kind
    os_parts = [str(item) for item in (system.get("Caption"), data.get("Version")) if item]
    if system.get("BuildNumber"):
        os_parts.append("Build " + str(system["BuildNumber"]))
    cpu_brief, cpu_detail = [], []
    performance = first(data, "CPUPerformance")
    for cpu in data.get("CPU") or [{}]:
        cores = f"{value(cpu.get('NumberOfCores'))} cores / {value(cpu.get('NumberOfLogicalProcessors'))} threads"
        cpu_brief.append(row("CPU", f"{value(cpu.get('Name'))} · {cores}" if cpu.get("Name") else NA))
        base = performance.get("ProcessorFrequency") if len(data.get("CPU") or []) == 1 else None
        clock = base or cpu.get("MaxClockSpeed")
        virtual = cpu.get("VirtualizationFirmwareEnabled")
        cpu_detail.extend([row("CPU", cpu.get("Name")), row("Cores", cores),
                           row("Base clock" if base else "Max clock", f"{clock / 1000:.2f} GHz (reported)" if clock else NA),
                           row("Socket", cpu.get("SocketDesignation")),
                           row("Virtualization", "Enabled" if virtual is True else "Disabled" if virtual is False else NA)])
        if len(data.get("CPU") or []) == 1:
            l1 = sum(item.get("InstalledSize") or 0 for item in data.get("Cache") or [] if item.get("Level") == 3)
            cpu_detail.append(row("L1 cache", f"{l1} KB" if l1 else NA))
        for label, field in (("L2 cache", "L2CacheSize"), ("L3 cache", "L3CacheSize")):
            cache = cpu.get(field)
            cpu_detail.append(row(label, f"{cache / 1024:.1f} MB" if cache else NA))
    cpu_detail.append(row("Sockets", len(data["CPU"]) if data.get("CPU") else NA))
    modules = data.get("Memory") or []
    installed = sum(module.get("Capacity") or 0 for module in modules) or None
    slots = sum(item.get("MemoryDevices") or 0 for item in data.get("MemorySlots") or [])
    memory_rows = [row("Installed", size(installed)), row("Slots used", f"{len(modules)} / {slots}" if modules and slots else f"{len(modules)} installed" if modules else NA)]
    memory_types = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 30: "LPDDR4", 35: "LPDDR5"}
    for module in modules:
        speed = module.get("ConfiguredClockSpeed") or module.get("Speed")
        memory_rows.extend(["", row(value(module.get("DeviceLocator")),
                                   f"{size(module.get('Capacity'))} · {memory_types.get(module.get('SMBIOSMemoryType'), NA)} · "
                                   + (f"{speed} MT/s" if speed else NA)), row("Manufacturer", module.get("Manufacturer")),
                            row("Form factor", {8: "DIMM", 12: "SO-DIMM", 14: "SMD"}.get(module.get("FormFactor"), NA))])
    gpu_brief, gpu_detail = [], []
    for gpu in data.get("DXGI") or data.get("GPU") or [{}]:
        dedicated = gpu.get("Dedicated")
        usable = gpu.get("CapacityKind") == "usable"
        gpu_brief.append(row("GPU", value(gpu.get("Name")) + (f" · {size(dedicated)} VRAM" + (" usable" if usable else "") if dedicated is not None else "")))
        gpu_detail.extend([row("GPU", gpu.get("Name")), row("VRAM usable" if usable else "Dedicated VRAM", size(dedicated))])
        if gpu.get("Error"):
            gpu_detail.append(row("VRAM query", gpu["Error"]))
    disks = data.get("Disks") or []
    disk_types = {3: "HDD", 4: "SSD", 5: "SCM"}
    disk_rows = [row(f"Disk {disk.get('Index', '?')}", f"{value(disk.get('Model'))} · {size(disk.get('Size'))} · {disk_types.get(disk.get('MediaType'), NA)}") for disk in disks] or [row("Disks", NA)]
    volumes = []
    for volume in data.get("Volumes") or []:
        volumes.extend([volume_title(volume), row("  Disk", ", ".join(str(index) for index in volume.get("Disks") or []) or NA),
                        row("  Capacity", size(volume.get("Size"))), row("  File system", volume.get("FileSystem")), ""])
    brief = [block("COMPUTER", [row("Name", computer.get("Name")), row("Model", model or NA), row("OS", " · ".join(os_parts) or NA)]),
             block("MEMBERSHIP", membership_rows(computer)), block("COMPONENTS", cpu_brief + [row("Memory", size(installed))] + gpu_brief),
             block("STORAGE", disk_rows), block("DISPLAYS", display_rows(data)), block("UPTIME", uptime_rows(data, now)[:1])]
    detailed = [block("COMPUTER", [row("Name", computer.get("Name")), row("Manufacturer", computer.get("Manufacturer")), row("Model", computer.get("Model")), row("Type", kind), row("Serial", bios.get("SerialNumber"))]),
                block("MEMBERSHIP", membership_rows(computer, detailed=True)),
                block("OPERATING SYSTEM", [row("OS", system.get("Caption")), row("Version", data.get("Version")), row("Build", system.get("BuildNumber")), row("Architecture", system.get("OSArchitecture")), row("Installed", system.get("Installed")), row("Directory", system.get("WindowsDirectory"))]),
                block("PROCESSOR", cpu_detail), block("MEMORY", memory_rows), block("GRAPHICS", gpu_detail),
                block("PHYSICAL DISKS", disk_rows), block("VOLUMES", volumes or [row("Volumes", NA)]),
                block("MOTHERBOARD", [row("Manufacturer", board.get("Manufacturer")), row("Model", board.get("Product"))]),
                block("BIOS", [row("Manufacturer", bios.get("Manufacturer")), row("Version", bios.get("SMBIOSBIOSVersion")), row("Release date", bios.get("Date"))]),
                block("DISPLAYS", display_rows(data)), block("UPTIME", uptime_rows(data, now))]
    add_errors(data, brief, detailed, {"Win32_ComputerSystem", "Win32_OperatingSystem", "Windows version", "Win32_Processor", "Win32_CacheMemory", "Win32_PhysicalMemory", "Win32_PhysicalMemoryArray", "Win32_VideoController", "DXGI", "Win32_DiskDrive", "MSFT_PhysicalDisk", "Win32_LogicalDisk", "Win32_BaseBoard", "Win32_BIOS", "WmiMonitorID", "DisplayModes"} | {volume.get("DeviceID") for volume in data.get("Volumes") or []})
    return "\n\n".join(brief), "\n\n".join(detailed)
