"""Synthetic network failures, IPv6 and category isolation checks."""

from queue import Queue
import base64
import json
import os
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from syshelper.sections.network import format_network
from syshelper.collectors.network import SCRIPT
from syshelper.ui import SysHelperApp


def adapter(**changes):
    data = {"Name": "Test Ethernet", "Status": "Up", "Virtual": False,
            "IPv4": [{"Address": "192.0.2.10", "Prefix": 24, "State": "Preferred"}],
            "IPv6": [], "DNS": ["192.0.2.1"], "Gateways": ["192.0.2.1"],
            "DHCPv4": "Enabled", "LeaseObtained": "2024-01-01 12:00:01",
            "Send": 0, "Receive": 125000}
    data.update(changes)
    return data


class NetworkTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows PowerShell regression")
    def test_real_powershell_gateway_projection_preserves_addresses_and_order(self):
        # Run the actual collector's selection on synthetic data, without probes.
        build = SCRIPT.split("$routeRows =", 1)[1].split("$checks =", 1)[0]
        select = SCRIPT.split("$gatewayTargets =", 1)[1].split("$proxy =", 1)[0]
        script = r"""
$ErrorActionPreference = 'Stop'
$routes = @(
    [pscustomobject]@{DestinationPrefix='0.0.0.0/0'; NextHop='192.0.2.1'; InterfaceAlias='Test'; InterfaceIndex=7; AddressFamily='IPv4'; RouteMetric=30},
    [pscustomobject]@{DestinationPrefix='::/0'; NextHop='fe80::1'; InterfaceAlias='Test'; InterfaceIndex=7; AddressFamily='IPv6'; RouteMetric=10},
    [pscustomobject]@{DestinationPrefix='0.0.0.0/0'; NextHop='192.0.2.1'; InterfaceAlias='Test'; InterfaceIndex=7; AddressFamily='IPv4'; RouteMetric=30}
)
$interfaces = @()
""" + "$routeRows =" + build + "$gatewayTargets =" + select + "$gatewayTargets | ConvertTo-Json -Compress"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        result = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                capture_output=True, encoding="utf-8", timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        targets = json.loads(result.stdout)
        self.assertEqual([r["Gateway"] for r in targets], ["fe80::1", "192.0.2.1"])
        self.assertEqual([r["Index"] for r in targets], [7, 7])

    def test_probe_execution_error_does_not_claim_gateway_failed_to_reply(self):
        brief, full = format_network({"Checks": [{"Name": "Gateway", "Status": "ERROR",
            "Target": "192.0.2.1", "Error": "Synthetic execution error"}]})
        self.assertNotIn("gateway did not answer", brief)
        self.assertIn("Gateway check could not run", brief)
        self.assertIn("Synthetic execution error", full)

    def test_summary_keeps_ipconfig_fields_and_details_add_lease_and_traffic(self):
        brief, full = format_network({"Adapters": [adapter(MAC="00-00-00-00-00-01")]})
        self.assertIn("192.0.2.10/24", brief)
        self.assertIn("00-00-00-00-00-01", brief)
        self.assertRegex(brief, r"Subnet mask\s+255\.255\.255\.0")
        self.assertIn("DHCP server", brief)
        self.assertNotIn("Lease obtained", brief)
        self.assertNotIn("Receive", brief)
        self.assertIn("00-00-00-00-00-01", full)
        self.assertIn("2024-01-01 12:00:01", full)
        self.assertIn("0.0 Kbit/s", full)
        self.assertIn("1.00 Mbit/s", full)

    def test_gateway_failure_does_not_override_successful_internet_probe(self):
        brief, full = format_network({"Checks": [
            {"Name": "Internet", "Status": "OK", "Result": "Expected response received"},
            {"Name": "Gateway", "Status": "WARNING", "Result": "TimedOut"}]})
        self.assertIn("[OK] Internet probe passed", brief)
        self.assertIn("ping may be blocked", brief)
        self.assertNotIn("Internet access not confirmed", full)

    def test_dns_failure_preserves_original_error_in_details(self):
        message = "No such host is known"
        brief, full = format_network({"Checks": [
            {"Name": "DNS", "Status": "FAILED", "Error": message},
            {"Name": "Public TCP", "Status": "OK"},
            {"Name": "Internet", "Status": "FAILED", "Error": "Connection failed"}]})
        self.assertIn("DNS lookup failed", brief)
        self.assertIn("Public TCP is reachable", brief)
        self.assertIn(message, full)
        self.assertNotIn(message, brief)

    def test_unexpected_web_response_is_not_reported_as_online(self):
        brief, full = format_network({"Checks": [
            {"Name": "Internet", "Status": "WARNING", "Result": "HTTP 302: unexpected response"}]})
        self.assertIn("Internet access not confirmed", brief)
        self.assertIn("HTTP 302", full)
        self.assertNotIn("Internet probe passed", brief)

    def test_ipv6_only_and_inactive_adapters(self):
        brief, full = format_network({"Adapters": [adapter(IPv4=[], IPv6=[
            {"Address": "2001:db8::10", "Prefix": 64, "State": "Preferred"}]),
            adapter(Name="Disconnected test", Status="Disconnected")]})
        self.assertIn("2001:db8::10/64", brief)
        self.assertNotIn("Disconnected test", brief)
        self.assertIn("Disconnected test", full)
        self.assertNotIn("No adapter has an active link", brief)

    def test_apipa_warning_but_normal_private_ip_is_valid(self):
        brief, _ = format_network({"Adapters": [adapter(IPv4=[
            {"Address": "169.254.10.20", "Prefix": 16}])]})
        self.assertIn("self-assigned", brief)
        brief, _ = format_network({"Adapters": [adapter()]})
        self.assertNotIn("self-assigned", brief)

    def test_inventory_access_error_does_not_claim_link_is_down(self):
        brief, full = format_network({"Errors": [{"Source": "Adapters", "Error": "Access denied"}]})
        self.assertIn("Some information is unavailable", brief)
        self.assertIn("Access denied", full)
        self.assertNotIn("No adapter has an active link", brief)

    def test_network_worker_does_not_collect_overview_or_hardware(self):
        app = SimpleNamespace(results=Queue())
        with patch("syshelper.ui.collect_network_snapshot", return_value={
                "CollectedAt": "2024-01-01T12:00:01+00:00"}) as network, \
                patch("syshelper.ui.collect_snapshot") as inventory:
            SysHelperApp._collect_report(app, "Network")
        network.assert_called_once_with()
        inventory.assert_not_called()
        section, report, status, timestamp = app.results.get()
        self.assertEqual(section, "Network")
        self.assertEqual(status, "")
        self.assertIn("CONNECTIVITY", report[0])
        self.assertEqual(timestamp, "2024-01-01T12:00:01+00:00")

    def test_multiple_ipv4_addresses_keep_their_own_masks(self):
        brief, _ = format_network({"Adapters": [adapter(IPv4=[
            {"Address": "192.0.2.10", "Prefix": 24},
            {"Address": "198.51.100.10", "Prefix": 27}])]})
        self.assertIn("255.255.255.0", brief)
        self.assertIn("255.255.255.224", brief)

    def test_network_identity_suffixes_and_duplicate_address_are_visible(self):
        brief, full = format_network({"Identity": {"HostName": "TEST-PC", "PrimarySuffix": "corp.example",
            "SearchList": ["corp.example", "lab.example"]}, "Adapters": [adapter(IPv4=[
            {"Address": "192.0.2.10", "Prefix": 24, "State": "Duplicate", "Origin": "Manual"}])]})
        self.assertIn("TEST-PC", brief)
        self.assertIn("lab.example", brief)
        self.assertIn("(Duplicate)", brief)
        self.assertIn("· Manual", full)
        self.assertIn("[WARNING] Test Ethernet", brief)

    def test_disconnected_adapter_is_compact_and_empty_configuration_is_not_an_error(self):
        brief, full = format_network({"Adapters": [adapter(Status="Disconnected")]})
        self.assertNotIn("Lease obtained", full)
        self.assertNotIn("Subnet mask", full)
        brief, _ = format_network({"Adapters": [adapter(Gateways=[], DNS=[])]})
        self.assertRegex(brief, r"Gateway\s+None")
        self.assertRegex(brief, r"DNS servers\s+None")

    def test_profile_readable_origins_and_adapter_spacing(self):
        brief, full = format_network({"Adapters": [adapter(Profile="Public", IPv6=[
            {"Address": "fe80::1%7", "Prefix": 64, "Origin": "WellKnown"}], IPv4=[
            {"Address": "192.0.2.10", "Prefix": 24, "Origin": "Dhcp"}]),
            adapter(Name="Test Wi-Fi", Status="Disconnected")]})
        self.assertIn("Up · Public", brief)
        self.assertIn("· DHCP", full)
        self.assertIn("· Link-local", full)
        self.assertNotIn("WellKnown", full)
        self.assertIn("\n\nTest Wi-Fi", full)
        lease = next(line for line in full.splitlines() if line.startswith("Lease obtained"))
        self.assertEqual(lease.index("2024"), 17)

    def test_dns_status_is_query_result_not_a_global_outage_claim(self):
        brief, full = format_network({"DNSChecks": [
            {"Server": "192.0.2.53", "ConfiguredOn": ["Test Ethernet"], "Status": "FAILED", "Error": "Synthetic DNS error"},
            {"Server": "1.1.1.1", "ConfiguredOn": [], "Provider": "Cloudflare", "Status": "OK", "Milliseconds": 0,
             "Addresses": ["192.0.2.10"], "Host": "test.example"}]})
        self.assertIn("CONFIGURED DNS", brief)
        self.assertIn("PUBLIC DNS", brief)
        self.assertIn("Cloudflare", brief)
        self.assertIn("0.0 ms", brief)
        self.assertIn("Synthetic DNS error", full)
        self.assertNotIn("Synthetic DNS error", brief)
        self.assertNotIn("outage", brief)

    def test_partial_loss_and_zero_latency_are_preserved(self):
        brief, full = format_network({"Checks": [{"Name": "Gateway", "Target": "192.0.2.1",
            "Status": "WARNING", "Sent": 4, "Received": 3, "Loss": 25, "Average": 0,
            "Minimum": 0, "Maximum": 0, "Replies": ["Success", "Success", "TimedOut", "Success"]}]})
        self.assertIn("avg 0.0 ms", brief)
        self.assertIn("loss 25% (3/4)", brief)
        self.assertIn("TimedOut", full)


if __name__ == "__main__":
    unittest.main()
