# SysHelper

Minimal Windows PC diagnostics in Python, with an English interface.

- **Overview:** computer identity, domain/workgroup, OS and installed components.
- **Hardware:** CPU/RAM/GPU readings, disk space, available storage counters and power status.
- **Drivers, Network, Devices, System:** planned.
- **Temperatures and voltages:** placeholders for future development.

Run check updates only the selected category. Show details expands its report.
Select text and press Ctrl+C to copy. Save report exports the current category
or all collected reports. Some readings depend on device support and permissions.

## Run and test

Use Windows and Python 3.10+ with tkinter. No third-party runtime packages are required.

```powershell
py main.py
py -m unittest discover -s tests -v
```

## Build one EXE

```powershell
py -m pip install -r requirements-build.txt
.\scripts\build.ps1
```

Output: `dist\SysHelper.exe`. Python is bundled; the destination PC does not
need it installed. The EXE build must run on Windows.

## Structure

```text
main.py                    Entry point
syshelper/
    ui.py                  Window and controls
    sections/              Category reports
    collectors/            Windows data collection
    report_utils.py        Text formatting
    reports.py             Report export
tests/                    Tests with synthetic data
scripts/build.ps1          EXE build
requirements.txt           Runtime dependencies (none)
requirements-build.txt     Build dependencies
```

Saved reports can contain PC names, domains and serial numbers. Keep them in
`reports/` or use the default `SysHelper-*.txt` names; both are ignored by Git.
Tests contain synthetic values. Source files do not store collected computer data.
