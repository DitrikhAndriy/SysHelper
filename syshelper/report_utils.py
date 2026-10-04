"""Common compact text formatting for diagnostic reports."""

from datetime import datetime

NA = "[UNAVAILABLE]"


def value(item):
    return str(item).strip() if item is not None and str(item).strip() else NA


def first(data, key):
    return next(iter(data.get(key) or []), {})


def row(label, item):
    return f"{label:<14}{' ' if len(label) >= 14 else ''}{value(item)}"


def aligned_row(label, item):
    """Wider alignment for Network and Drivers' longer field names."""
    return f"{label:<16} {value(item)}"


def block(title, rows):
    return title + "\n" + "\n".join(rows)


def size(item):
    if item is None:
        return NA
    unit, divisor = ("TB", 1024 ** 4) if item >= 1024 ** 4 else ("GB", 1024 ** 3)
    return f"{item / divisor:.1f}".rstrip("0").rstrip(".") + f" {unit}"


def volume_title(volume):
    label = str(volume.get("VolumeName") or "").strip()
    return value(volume.get("DeviceID")) + (" · " + label if label else "")


def add_errors(data, brief, detailed, sources):
    errors = [error for error in data.get("Errors") or [] if error.get("Source") in sources]
    if errors:
        brief.append("[WARNING] Some information is unavailable. See details.")
        detailed.append(block("COLLECTION ERRORS", [f"{error['Source']}\n{error['Error']}" for error in errors]))


def display_rows(data):
    rows, matched = [], set()
    for index, mode in enumerate(data.get("DisplayModes") or [], start=1):
        names = []
        for monitor_id in mode.get("MonitorIDs") or []:
            instance = "\\".join(monitor_id.split("#")[:3]).removeprefix("\\\\?\\").casefold()
            for monitor in data.get("Monitors") or []:
                identity = monitor.get("InstanceName", "").rsplit("_", 1)[0].casefold()
                if identity and identity == instance and monitor.get("Name"):
                    names.append(monitor["Name"])
                    matched.add(identity)
        hz = f"{mode['Hz']} Hz" if mode.get("Hz", 0) > 1 else NA
        description = f"{mode['Width']} × {mode['Height']} · {hz}"
        rows.append(row(f"Display {index}", (" / ".join(names) + " · " if names else "") + description))
    for monitor in data.get("Monitors") or []:
        if monitor.get("InstanceName", "").rsplit("_", 1)[0].casefold() not in matched:
            rows.append(row("Monitor", monitor.get("Name")))
    return rows or [row("Display", NA)]


def uptime_rows(data, now=None):
    boot = first(data, "OS").get("LastBoot")
    if not boot:
        return [row("D:HH:MM:SS", NA), row("Last boot", NA)]
    boot_date = datetime.fromisoformat(boot)
    captured = datetime.fromisoformat(data["CollectedAt"]) if data.get("CollectedAt") else datetime.now().astimezone()
    elapsed = max(0, int(((now or captured) - boot_date).total_seconds()))
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return [row("D:HH:MM:SS", f"{days}:{hours:02}:{minutes:02}:{seconds:02}"),
            row("Last boot", boot_date.astimezone().strftime("%Y-%m-%d %H:%M:%S"))]
