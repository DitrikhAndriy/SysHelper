"""Device problems, driver matching, and category isolation with synthetic data."""

from queue import Queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from syshelper.sections.drivers import format_drivers
from syshelper.ui import SysHelperApp


def device(**changes):
    row = {"ID": r"PCI\TEST_DEVICE\001", "Name": "Test GPU", "Class": "Display", "Code": 0, "Status": "OK"}
    row.update(changes)
    return row


def driver(**changes):
    row = {"DeviceID": r"pci\test_device\001", "DriverVersion": "1.2.3.4", "DriverProviderName": "Test provider",
           "Date": "2006-06-21", "IsSigned": True, "InfName": "oem1.inf"}
    row.update(changes)
    return row


class DriversTests(unittest.TestCase):
    def test_old_driver_date_is_not_a_problem_and_ids_match_case_insensitively(self):
        brief, full = format_drivers({"Devices": [device()], "Drivers": [driver()]})
        self.assertIn("[OK] No Windows device problems", brief)
        self.assertIn("1.2.3.4", brief)
        self.assertIn("2006-06-21", brief)
        self.assertNotIn("[WARNING]", brief)
        self.assertNotIn("oem1.inf", brief)
        self.assertIn("oem1.inf", full)

    def test_code_28_is_missing_driver_even_when_status_is_generic(self):
        brief, full = format_drivers({"Devices": [device(Code=28, Status="Unknown")]})
        self.assertIn("[WARNING] Code 28", brief)
        self.assertIn("Drivers are not installed", full)
        self.assertIn("ATTENTION", brief)

    def test_disabled_device_is_not_counted_as_a_broken_driver(self):
        brief, full = format_drivers({"Devices": [device(Code=22, Status="Error")]})
        self.assertIn("[DISABLED] Code 22", brief)
        self.assertNotIn("[WARNING]", brief)
        self.assertRegex(brief, r"Problems\s+0")

    def test_unavailable_inventory_cannot_claim_healthy_devices(self):
        brief, full = format_drivers({"Errors": [{"Source": "Present devices", "Error": "Access denied"}]})
        self.assertNotIn("[OK]", brief)
        self.assertIn("Check incomplete", brief)
        self.assertIn("Access denied", full)

    def test_unsigned_report_is_visible_but_missing_metadata_is_not_missing_driver(self):
        brief, full = format_drivers({"Devices": [device()], "Drivers": [driver(IsSigned=False)]})
        self.assertIn("Unsigned (reported)", brief)
        self.assertIn("Signature", full)
        brief, full = format_drivers({"Devices": [device()]})
        self.assertNotIn("Drivers are not installed", brief)
        self.assertRegex(full, r"Driver data\s+\[UNAVAILABLE\]")

    def test_driver_for_another_device_does_not_attach_by_friendly_name(self):
        brief, full = format_drivers({"Devices": [device()], "Drivers": [driver(DeviceID=r"PCI\OTHER\002")]})
        self.assertNotIn("1.2.3.4", full)

    def test_unknown_problem_code_and_status_conflict_remain_visible(self):
        brief, full = format_drivers({"Devices": [device(Code=999)]})
        self.assertIn("Code 999", brief)
        brief, full = format_drivers({"Devices": [device(Code=0, Status="Error")]})
        self.assertIn("[WARNING] Error", full)
        self.assertIn("device problem(s)", brief)

    def test_drivers_worker_does_not_collect_other_categories(self):
        app = SimpleNamespace(results=Queue())
        with patch("syshelper.ui.collect_drivers_snapshot", return_value={"CollectedAt": "2024-01-01T12:00:01+00:00"}) as collect, \
                patch("syshelper.ui.collect_network_snapshot") as network, patch("syshelper.ui.collect_snapshot") as inventory:
            SysHelperApp._collect_report(app, "Drivers")
        collect.assert_called_once_with()
        network.assert_not_called()
        inventory.assert_not_called()
        section, report, status, timestamp = app.results.get()
        self.assertEqual(section, "Drivers")
        self.assertEqual(status, "")
        self.assertIn("MAIN DRIVERS", report[0])

    def test_virtual_devices_stay_in_details_unless_they_have_problems(self):
        virtual = device(ID=r"ROOT\TEST_VPN\001", Class="Net", Name="Test virtual network")
        brief, full = format_drivers({"Devices": [device(), virtual]})
        self.assertNotIn("Test virtual network", brief)
        self.assertIn("Test virtual network", full)
        virtual["Code"] = 10
        brief, _ = format_drivers({"Devices": [virtual]})
        self.assertIn("Test virtual network", brief)


if __name__ == "__main__":
    unittest.main()
