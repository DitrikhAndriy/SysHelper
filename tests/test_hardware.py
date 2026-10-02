"""Scope, sensor validity and report export regression checks."""

from queue import Queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from syshelper.sections.hardware import format_hardware
from syshelper.reports import export_text
from syshelper.ui import SysHelperApp


class HardwareTests(unittest.TestCase):
    def test_temperature_and_voltage_fields_are_deferred(self):
        brief, detailed = format_hardware({'Sensors': [
            {'SensorType': 'Temperature', 'Parent': '/amdcpu/0', 'Name': 'CPU Package', 'Value': 55},
            {'SensorType': 'Voltage', 'Name': 'CPU voltage', 'Value': 1.2},
        ], 'DXGI': [{'Name': 'GPU', 'Temperature': 46}]})
        for report in (brief, detailed):
            self.assertIn('Temperatures  [NOT IMPLEMENTED]', report)
            self.assertIn('Voltages      [NOT IMPLEMENTED]', report)
            self.assertNotIn('°C', report)
            self.assertNotIn('1.2 V', report)

    def test_gpu_zero_usage_and_stopped_fan_are_valid(self):
        brief, detailed = format_hardware({'DXGI': [{'Name': 'GPU', 'Temperature': 46,
            'Usage': 0, 'VRAMUsed': 0, 'FanRPM': 0, 'CoreClock': 210}]})
        self.assertIn('3D usage      0%', brief)
        self.assertNotIn('46 °C', brief)
        self.assertIn('Fan           0 RPM', detailed)

    def test_disk_missing_sensor_does_not_mean_zero_degrees(self):
        brief, detailed = format_hardware({'StorageSensors': [{'Index': 0, 'Name': 'SSD',
            'Temperature': 0, 'Health': 'Healthy', 'Wear': 0, 'ReadErrors': 0}]})
        self.assertIn('Temperatures  [NOT IMPLEMENTED]', brief)
        self.assertNotIn('0 °C', brief)
        self.assertIn('0% used', detailed)

    def test_worker_only_collects_selected_category(self):
        app = SimpleNamespace(results=Queue())
        with patch('syshelper.ui.collect_snapshot', return_value={'CollectedAt': '2024-01-03T12:00:00+03:00'}) as collect:
            SysHelperApp._collect_report(app, 'Hardware')
        collect.assert_called_once_with('Hardware')
        self.assertEqual(app.results.qsize(), 1)
        self.assertEqual(app.results.get()[0], 'Hardware')

    def test_export_scope_and_details(self):
        reports = {'Overview': ('OVERVIEW SHORT', 'OVERVIEW FULL'), 'Hardware': ('HARDWARE SHORT', 'HARDWARE FULL')}
        selected = export_text(reports, 'Hardware')
        self.assertIn('HARDWARE SHORT', selected)
        self.assertNotIn('OVERVIEW', selected)
        combined = export_text(reports, 'Hardware', details=True, all_reports=True,
                               order=('Overview', 'Hardware', 'Network'))
        self.assertIn('OVERVIEW FULL', combined)
        self.assertIn('HARDWARE FULL', combined)
        self.assertNotIn('Network', combined)
        self.assertNotIn('SHORT', combined)

    def test_unrun_category_is_not_exported_as_fake_report(self):
        with self.assertRaises(ValueError):
            export_text({'Overview': ('short', 'full')}, 'Hardware')
        with self.assertRaises(ValueError):
            export_text({}, 'Overview', all_reports=True)


if __name__ == '__main__':
    unittest.main()
