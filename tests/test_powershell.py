"""Shared subprocess boundary: raw failures, Unicode JSON and timeouts."""

import base64
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from syshelper.collectors.powershell import run_powershell


class PowerShellTests(unittest.TestCase):
    def test_unicode_json_and_bom_are_preserved(self):
        result = SimpleNamespace(returncode=0, stdout='\ufeff{"Name": "Тест"}', stderr="")
        with patch("syshelper.collectors.powershell.os.name", "nt"), \
                patch("syshelper.collectors.powershell.subprocess.run", return_value=result) as run:
            data = run_powershell("Write-Output 'Тест'", timeout=8)
        self.assertEqual(data["Name"], "Тест")
        command = run.call_args.args[0]
        self.assertEqual(base64.b64decode(command[-1]).decode("utf-16le"), "Write-Output 'Тест'")
        self.assertEqual(run.call_args.kwargs["timeout"], 8)

    def test_native_failure_is_not_replaced_by_an_empty_snapshot(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="Access denied")
        with patch("syshelper.collectors.powershell.os.name", "nt"), \
                patch("syshelper.collectors.powershell.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Access denied"):
                run_powershell("test", timeout=8)

    def test_timeout_and_malformed_output_propagate(self):
        with patch("syshelper.collectors.powershell.os.name", "nt"), \
                patch("syshelper.collectors.powershell.subprocess.run", side_effect=subprocess.TimeoutExpired("powershell", 8)):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_powershell("test", timeout=8)
        result = SimpleNamespace(returncode=0, stdout="not JSON", stderr="")
        with patch("syshelper.collectors.powershell.os.name", "nt"), \
                patch("syshelper.collectors.powershell.subprocess.run", return_value=result):
            with self.assertRaises(json.JSONDecodeError):
                run_powershell("test", timeout=8)


if __name__ == "__main__":
    unittest.main()
