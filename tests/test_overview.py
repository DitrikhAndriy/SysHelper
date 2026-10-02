"""Formatting checks for incomplete snapshots and warning boundaries."""

from datetime import datetime, timezone
import unittest

from syshelper.sections.overview import format_overview
from syshelper.sections.hardware import format_hardware


class OverviewTests(unittest.TestCase):
    def test_empty_snapshot_does_not_invent_values(self):
        compact, detailed = format_overview({})
        self.assertIn("[UNAVAILABLE]", compact)
        self.assertNotIn("0 installed", detailed)
        self.assertNotIn("BATTERY", compact)
        self.assertNotIn("[OK]", compact)

    def test_zero_free_space_warns_but_ten_percent_does_not(self):
        compact, detailed = format_hardware({"Volumes": [
            {"DeviceID": "C:", "Size": 100, "FreeSpace": 0, "Disks": [0]},
            {"DeviceID": "D:", "Size": 100, "FreeSpace": 10, "Disks": [1, 2]},
        ]})
        self.assertEqual(compact.count("[WARNING: Low free space]"), 1)
        self.assertEqual(detailed.count("[WARNING: Low free space]"), 1)

    def test_details_replace_short_report_and_preserve_errors(self):
        compact, detailed = format_overview({
            "Computer": [{"Name": "TEST-PC", "PCSystemType": 2}],
            "Battery": {"Charge": 0, "Source": "Battery", "Status": "Not charging"},
            "Errors": [{"Source": "Win32_BIOS", "Error": "Access denied: 0x80070005"}],
        })
        self.assertNotIn("Access denied: 0x80070005", compact)
        self.assertIn("Access denied: 0x80070005", detailed)
        self.assertNotIn("BATTERY", compact)
        hardware, _ = format_hardware({"Battery": {"Charge": 0}})
        self.assertIn("0%", hardware)
        self.assertIn("Laptop", detailed)
        self.assertEqual(detailed.count("COMPUTER\n"), 1)

    def test_memory_and_cpu_zero_usage_are_valid(self):
        data = {
            "MemoryTotal": 16 * 1024 * 1024, "MemoryFree": 16 * 1024 * 1024,
            "CPU": [{"Name": "CPU", "LoadPercentage": 0}],
            "Memory": [{"Capacity": 16 * 1024 ** 3, "DeviceLocator": "DIMM A1"}],
        }
        compact, detailed = format_overview(data)
        hardware, _ = format_hardware(data)
        self.assertIn("Used          0 GB · 0%", hardware)
        self.assertIn("Usage         0%", hardware)
        self.assertNotIn("Usage", detailed)
        self.assertIn("Installed     16 GB", detailed)

    def test_uptime_uses_timezone_aware_boot(self):
        compact, detailed = format_overview({
            "OS": [{"LastBoot": "2024-01-01T09:30:00+03:00"}],
        }, now=datetime(2024, 1, 3, 10, 30, tzinfo=timezone.utc))
        self.assertIn("2:04:00:00", compact)
        self.assertIn("Last boot", detailed)

    def test_empty_volume_label_and_bios_date_are_clear(self):
        _, detailed = format_overview({
            "Volumes": [{"DeviceID": "C:", "VolumeName": "", "Size": 100, "FreeSpace": 50}],
            "BIOS": [{"Date": "2020-01-02"}],
        })
        self.assertIn("VOLUMES\nC:\n", detailed)
        self.assertNotIn("C: · [UNAVAILABLE]", detailed)
        self.assertIn("Release date  2020-01-02", detailed)

    def test_vram_uses_dxgi_capacity_over_four_gb(self):
        compact, detailed = format_overview({
            "DXGI": [{"Name": "Test GPU", "Dedicated": 8 * 1024 ** 3, "Shared": 16 * 1024 ** 3}],
            "GPU": [{"Name": "Test GPU", "DriverVersion": "1.2.3"}],
        })
        self.assertIn("8 GB VRAM", compact)
        self.assertIn("Dedicated VRAM 8 GB", detailed)
        self.assertNotIn("Shared limit", detailed)
        self.assertNotIn("1.2.3", detailed)

    def test_monitors_match_identity_even_if_order_differs(self):
        compact, _ = format_overview({
            "Monitors": [{"Name": "Monitor B", "InstanceName": "DISPLAY\\BBB\\002_0"},
                         {"Name": "Monitor A", "InstanceName": "DISPLAY\\AAA\\001_0"}],
            "DisplayModes": [{"Name": "\\\\.\\DISPLAY1", "Width": 1920, "Height": 1080, "Hz": 60,
                              "MonitorIDs": ["\\\\?\\DISPLAY#AAA#001#{guid}"]}],
        })
        self.assertIn("Display 1     Monitor A · 1920 × 1080 · 60 Hz", compact)
        self.assertNotIn("\\\\.\\DISPLAY1", compact)
        self.assertIn("Monitor B", compact)

    def test_sampled_cpu_speed_and_memory_slots(self):
        data = {
            "CPU": [{"Name": "Test CPU", "MaxClockSpeed": 3700, "VirtualizationFirmwareEnabled": True}],
            "CPUPerformance": [{"ProcessorFrequency": 3700, "PercentProcessorPerformance": 124,
                                "PercentProcessorUtility": 5}],
            "Memory": [{"Capacity": 16 * 1024 ** 3, "FormFactor": 8}],
            "MemorySlots": [{"MemoryDevices": 2}],
        }
        _, detailed = format_overview(data)
        _, hardware = format_hardware(data)
        self.assertIn("4.59 GHz (sampled)", hardware)
        self.assertNotIn("sampled", detailed)
        self.assertIn("Base clock    3.70 GHz (reported)", detailed)
        self.assertIn("Virtualization Enabled", detailed)
        self.assertIn("Slots used    1 / 2", detailed)
        self.assertIn("Form factor   DIMM", detailed)

    def test_dxgi_only_vram_is_labeled_usable(self):
        compact, detailed = format_overview({"DXGI": [{
            "Name": "GPU", "Dedicated": 8 * 1024 ** 3, "CapacityKind": "usable",
        }]})
        self.assertIn("8 GB VRAM usable", compact)
        self.assertIn("VRAM usable", detailed)
        self.assertNotIn("Dedicated VRAM", detailed)

    def test_domain_and_workgroup_are_distinct(self):
        for computer, expected, excluded in (
            ({"PartOfDomain": True, "Domain": "corp.example", "DomainRole": 1}, "Domain        corp.example", "Workgroup"),
            ({"PartOfDomain": False, "Domain": "WORKGROUP", "DomainRole": 0}, "Workgroup     WORKGROUP", "Domain joined"),
            ({}, "Membership    [UNAVAILABLE]", "Workgroup"),
        ):
            compact, detailed = format_overview({"Computer": [computer]})
            self.assertIn(expected, compact)
            self.assertIn(expected, detailed)
            self.assertNotIn(excluded, compact)

    def test_live_values_only_appear_in_hardware(self):
        data = {"CPU": [{"LoadPercentage": 25}], "MemoryTotal": 1024 ** 2,
                "MemoryFree": 512 * 1024, "ProcessCount": 123,
                "Volumes": [{"DeviceID": "C:", "Size": 100, "FreeSpace": 1}]}
        _, overview = format_overview(data)
        _, hardware = format_hardware(data)
        for label in ("Usage", "Available", "Committed", "Processes", "[WARNING: Low free space]"):
            self.assertNotIn(label, overview)
            self.assertIn(label, hardware)

    def test_hardware_errors_do_not_pollute_overview(self):
        data = {"Errors": [{"Source": "Win32_PerfFormattedData_PerfOS_Memory", "Error": "Memory counters failed"}]}
        _, overview = format_overview(data)
        _, hardware = format_hardware(data)
        self.assertNotIn("Memory counters failed", overview)
        self.assertIn("Memory counters failed", hardware)

    def test_uptime_is_fixed_to_snapshot_time(self):
        compact, _ = format_overview({"OS": [{"LastBoot": "2024-01-01T09:30:00+03:00"}],
                                      "CollectedAt": "2024-01-01T09:30:12+03:00"})
        self.assertIn("0:00:00:12", compact)


if __name__ == "__main__":
    unittest.main()
