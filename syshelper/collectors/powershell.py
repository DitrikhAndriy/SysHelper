"""Shared hidden PowerShell runner for read-only JSON collectors."""

import base64
import json
import os
import subprocess


def run_powershell(script, timeout):
    if os.name != "nt":
        raise OSError("SysHelper currently supports Windows only.")
    executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or
                           f"PowerShell exited with code {result.returncode}.")
    return json.loads(result.stdout.lstrip("\ufeff"))
