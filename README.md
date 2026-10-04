# SysHelper

Minimal Windows PC diagnostics in Python, with an English interface.

| Category | Available information |
| --- | --- |
| Overview | Computer identity, domain/workgroup, Windows and installed components |
| Hardware | CPU/RAM/GPU readings, disk space, storage counters and power status |
| Network | IP/masks, MAC, DHCP/leases, DNS, profiles, traffic and connection checks |
| Drivers | Present device problems, driver versions, providers, dates, INF and reported signatures |

Devices and System are planned. Temperatures and voltages remain placeholders.

**Run check** updates only the selected category. **Show details** expands its
report. Select text and press **Ctrl+C** to copy. **Save report** exports the
current category or all previously collected reports.

## Run and test

Requires Windows and Python 3.10+ with tkinter. Uses built-in Windows
PowerShell; no third-party Python runtime packages are needed.

```powershell
py main.py
py -m unittest discover -s tests -v
```

## Build one EXE

```powershell
py -m pip install -r requirements-build.txt
.\scripts\build.ps1
```

Output: `dist\SysHelper.exe`. Build on Windows; the destination PC does not
need Python installed. EXE packaging has not yet been validated.

## Structure

- `main.py`: entry point; `syshelper/ui.py`: window and controls.
- `syshelper/sections/`: separate report formatters for each category.
- `syshelper/collectors/`: category collectors, network probes and Windows helpers.
- `syshelper/report_utils.py` and `reports.py`: shared formatting and export.
- `tests/`: synthetic fixtures; `scripts/build.ps1`: EXE build.

## Diagnostic notes

Network sends test requests to `www.msftconnecttest.com`, each configured DNS
resolver on active adapters, and the standard IPv4 resolver pairs from
[Cloudflare](https://developers.cloudflare.com/1.1.1.1/ip-addresses/),
[Google](https://developers.google.com/speed/public-dns/docs/using) and
[Quad9](https://docs.quad9.net/services/). It also tests TCP to `1.1.1.1:443`
and four ICMP samples to `1.1.1.1` and up to four gateways. Results describe
this PC's connection; blocked probes do not prove a service outage.

Drivers reads local Windows data without installing drivers or checking for
updates. Driver dates are package dates, not installation times. Signatures
are reported by WMI, not independently verified. Some readings depend on
hardware support and permissions.

Collected data stays in memory until you choose to save a report. Reports can
contain host names, domains, IP/MAC addresses, serial numbers and device IDs.
Use `reports/` or the default `SysHelper-*.txt` names; both are ignored by Git.
Tests use synthetic data; source files do not store collected PC information.
