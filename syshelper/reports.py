"""Export cached category reports without running new checks."""


def export_text(reports, category, details=False, all_reports=False, order=(), timestamps=None):
    categories = [name for name in (order or reports) if name in reports] if all_reports else [category]
    if not categories or any(name not in reports for name in categories):
        raise ValueError("No report available. Run a check first.")
    blocks = []
    for name in categories:
        header = f"SysHelper | {name}"
        timestamp = (timestamps or {}).get(name)
        if timestamp:
            header += f"\nCollected: {timestamp}"
        blocks.append(header + "\n\n" + reports[name][1 if details else 0])
    return "\n\n".join(blocks) + "\n"
