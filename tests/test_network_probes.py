"""Per-server targeting, query reuse, and bounded error handling."""

import subprocess
import unittest
from unittest.mock import patch

from syshelper.collectors.network_probes import collect_dns_checks, collect_ping_checks, query_dns


class NetworkProbeTests(unittest.TestCase):
    def test_each_active_configured_server_is_queried_once_and_public_servers_are_reused(self):
        adapters = [
            {"Name": "Test LAN", "Status": "Up", "DNS": ["1.1.1.1", "192.0.2.53"]},
            {"Name": "Test VPN", "Status": "Up", "DNS": ["192.0.2.53"]},
            {"Name": "Offline", "Status": "Disconnected", "DNS": ["192.0.2.99"]},
        ]
        with patch("syshelper.collectors.network_probes.query_dns", return_value={"Status": "OK"}) as query:
            checks = collect_dns_checks(adapters)
        servers = [call.args[0] for call in query.call_args_list]
        self.assertEqual(len(servers), 7)
        self.assertEqual(servers.count("1.1.1.1"), 1)
        self.assertEqual(servers.count("192.0.2.53"), 1)
        self.assertNotIn("192.0.2.99", servers)
        configured = next(c for c in checks if c["Server"] == "192.0.2.53")
        self.assertEqual(configured["ConfiguredOn"], ["Test LAN", "Test VPN"])
        self.assertEqual({c.get("Provider") for c in checks if c.get("Provider")}, {"Cloudflare", "Google", "Quad9"})

    def test_dns_uses_specific_server_and_preserves_errors(self):
        with patch("syshelper.collectors.network_probes.run_powershell",
                   return_value={"Status": "FAILED", "Error": "DNS name does not exist"}) as run:
            result = query_dns("192.0.2.53")
        script = run.call_args.args[0]
        self.assertIn("-Server '192.0.2.53'", script)
        self.assertIn("-DnsOnly -NoHostsFile -QuickTimeout", script)
        self.assertEqual(result["Error"], "DNS name does not exist")

    def test_timeout_is_local_to_the_dns_check(self):
        with patch("syshelper.collectors.network_probes.run_powershell",
                   side_effect=subprocess.TimeoutExpired("powershell", 8)):
            result = query_dns("192.0.2.53")
        self.assertEqual(result["Status"], "TIMEOUT")

    def test_invalid_address_cannot_be_embedded_in_powershell(self):
        with patch("syshelper.collectors.network_probes.run_powershell") as run:
            for server in ("'; Write-Output injected; '", "fe80::1%unsafe'"):
                self.assertEqual(query_dns(server)["Status"], "ERROR")
        run.assert_not_called()

    def test_ipv6_gateway_has_interface_scope_and_ping_failure_remains_separate(self):
        with patch("syshelper.collectors.network_probes.run_powershell", side_effect=RuntimeError("Synthetic ping failure")):
            checks = collect_ping_checks([{"Gateway": "fe80::1", "Index": 7}])
        self.assertEqual(checks[0]["Target"], "fe80::1%7")
        self.assertEqual(checks[0]["Status"], "ERROR")
        self.assertEqual(checks[1]["Name"], "Public ping")
        self.assertIn("Synthetic ping failure", checks[0]["Error"])


if __name__ == "__main__":
    unittest.main()
