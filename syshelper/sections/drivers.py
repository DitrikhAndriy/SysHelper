"""Driver versions and Windows device problems, without age-based warnings."""

from ..report_utils import NA, aligned_row as row, block, value


CODES = {
    0: "Working properly", 10: "Device cannot start", 14: "Restart required",
    18: "Reinstall drivers", 22: "Device disabled", 24: "Device unavailable or not fully configured",
    28: "Drivers are not installed", 31: "Windows cannot load required drivers",
    32: "Driver service disabled", 37: "Driver initialization failed", 39: "Driver cannot be loaded",
    43: "Windows stopped this device after a reported problem", 45: "Device not connected",
    48: "Driver blocked by Windows", 52: "Windows cannot verify the digital signature",
}
MAIN_CLASSES = {"DISPLAY", "NET", "MEDIA", "BLUETOOTH", "SCSIADAPTER", "HDC"}


def _status(device):
    code = device.get("Code")
    if code == 22:
        return "[DISABLED] Code 22 · Device disabled"
    if code not in (None, 0):
        return f"[WARNING] Code {code} · {CODES.get(code, 'Windows device problem')}"
    if device.get("Status") in ("Error", "Degraded"):
        return "[WARNING] " + device["Status"]
    if code == 0:
        return "[OK]"
    return NA


def _problem(device):
    if device.get("Code") == 22:
        return False
    return device.get("Code") not in (None, 0) or device.get("Status") in ("Error", "Degraded")


def _driver_rows(driver, details):
    if not driver:
        # Missing WMI metadata is not evidence that a device needs a driver.
        return [row("Driver data", NA)]
    rows = [row("Version", driver.get("DriverVersion")), row("Provider", driver.get("DriverProviderName")),
            row("Driver date", driver.get("Date"))]
    if details:
        signature = {True: "Signed (reported)", False: "[WARNING] Unsigned (reported)"}.get(driver.get("IsSigned"), NA)
        rows += [row("INF", driver.get("InfName")), row("Signature", signature), row("Signer", driver.get("Signer"))]
    return rows


def _main_device(device):
    identity = str(device.get("ID") or "").upper()
    physical = identity.startswith(("PCI\\", "USB\\", "HDAUDIO\\", "INTELAUDIO\\", "ACPI\\", "SD\\"))
    return physical and (str(device.get("Class") or "").upper() in MAIN_CLASSES or
                         str(device.get("Service") or "").upper() in ("USBXHCI", "USBEHCI", "USBOHCI", "USBUHCI"))


def format_drivers(data):
    devices = sorted(data.get("Devices") or [], key=lambda d: (d.get("Class") or "", d.get("Name") or d.get("ID") or ""))
    by_id = {}
    for driver in data.get("Drivers") or []:
        if driver.get("DeviceID"):
            by_id.setdefault(str(driver["DeviceID"]).casefold(), []).append(driver)
    errors = data.get("Errors") or []
    problems = [d for d in devices if _problem(d)]
    disabled = [d for d in devices if d.get("Code") == 22]
    unknown = [d for d in devices if d.get("Code") is None]
    unsigned = []
    for device in devices:
        if any(driver.get("IsSigned") is False for driver in by_id.get(str(device.get("ID") or "").casefold(), [])):
            unsigned.append(device)
    if problems:
        health = f"[WARNING] {len(problems)} device problem(s)"
        if errors or unknown:
            health += " · check incomplete"
    elif errors or unknown or not devices:
        health = "[UNAVAILABLE] Check incomplete; see details"
    else:
        health = "[OK] No Windows device problems reported"
    stats = [row("Device status", health), row("Present devices", len(devices)), row("Problems", len(problems)),
             row("Disabled", len(disabled)), row("Unsigned", f"{len(unsigned)} (reported)")]
    if unknown:
        stats.append(row("Unknown status", len(unknown)))
    issues, main, full = [], [], []
    for device in devices:
        identity = str(device.get("ID") or "").casefold()
        drivers = by_id.get(identity, [])
        name = device.get("Name") or device.get("ID") or "Unknown device"
        short = [row("Status", _status(device))]
        for driver in drivers or [None]:
            short.extend(_driver_rows(driver, False))
        is_problem = _problem(device)
        if is_problem or device.get("Code") == 22 or device in unsigned:
            if device in unsigned:
                short.append(row("Signature", "[WARNING] Unsigned (reported)"))
            issues.append(block(name, short))
        elif _main_device(device):
            versions = [row("Driver", " · ".join(value(driver.get(key)) for key in
                         ("DriverVersion", "DriverProviderName", "Date"))) for driver in drivers]
            main.append(block(name, versions or [row("Driver data", NA)]))
        detail = [row("Class", device.get("Class")), row("Status", _status(device)),
                  row("Windows status", device.get("Status")), row("Problem code", device.get("Code")),
                  row("Manufacturer", device.get("Manufacturer")), row("Service", device.get("Service"))]
        for driver in drivers or [None]:
            detail.extend(_driver_rows(driver, True))
        detail.append(row("Device ID", device.get("ID")))
        full.append(block(name, detail))
    brief = [block("STATUS", stats)]
    if issues:
        brief.append(block("ATTENTION", ["\n\n".join(issues)]))
    brief.append(block("MAIN DRIVERS", ["\n\n".join(main)] if main else [NA]))
    detailed = [block("STATUS", stats), block("PRESENT DEVICE DRIVERS", ["\n\n".join(full)] if full else [NA])]
    if errors:
        detailed.append(block("COLLECTION ERRORS", [f"{e['Source']}\n{e['Error']}" for e in errors]))
    return "\n\n".join(brief), "\n\n".join(detailed)
