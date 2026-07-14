"""Tests for Checkmk performance data parsing."""

import unittest
import importlib.util
from pathlib import Path

_UTILS_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "homeassistant_checkmk"
    / "utils.py"
)
_SPEC = importlib.util.spec_from_file_location("checkmk_utils", _UTILS_PATH)
_UTILS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_UTILS)
metric_device_class = _UTILS.metric_device_class
parse_perf_data = _UTILS.parse_perf_data
invalid_regex_patterns = _UTILS.invalid_regex_patterns
match_any = _UTILS.match_any
selection_allows = _UTILS.selection_allows


class ParsePerfDataTest(unittest.TestCase):
    def test_parses_cpu_metrics_and_thresholds(self):
        metrics = parse_perf_data("user=12.5%;80;90;0;100 system=3.25% wait=0%")

        self.assertEqual(metrics[0]["name"], "user")
        self.assertEqual(metrics[0]["value"], 12.5)
        self.assertEqual(metrics[0]["unit"], "%")
        self.assertEqual(metrics[0]["warning"], 80.0)
        self.assertEqual(metrics[0]["maximum"], 100.0)
        self.assertEqual(len(metrics), 3)

    def test_parses_quoted_disk_and_temperature_metrics(self):
        metrics = parse_perf_data("'disk / used'=42.5GB;;;0;100 temperature=51C")

        self.assertEqual(metrics[0]["name"], "disk / used")
        self.assertEqual(metrics[0]["unit"], "GB")
        self.assertEqual(metrics[1]["unit"], "°C")

    def test_skips_invalid_values(self):
        self.assertEqual(parse_perf_data("state=U broken"), [])
        self.assertEqual(parse_perf_data("'unterminated=1"), [])

    def test_maps_device_classes(self):
        self.assertEqual(metric_device_class("MB"), "data_size")
        self.assertEqual(metric_device_class("B/s"), "data_rate")
        self.assertEqual(metric_device_class("°C"), "temperature")
        self.assertIsNone(metric_device_class("%"))

    def test_infers_units_from_real_checkmk_metrics(self):
        cpu = parse_perf_data(
            "user=14.779325;;;; system=4.77707;;;; util=23.107491;;;0;",
            "CPU utilization",
        )
        memory = parse_perf_data(
            "mem_used=9414086656;;;0;24904916992 mem_used_percent=37.800113;;;0;",
            "Memory",
        )
        filesystem = parse_perf_data(
            "fs_used=93095.800781;183652.75;206609.34375;0;229565.9375 "
            "fs_used_percent=40.552968;80;90;0;100",
            "Filesystem /",
        )
        disk = parse_perf_data(
            "disk_utilization=0.245533;;;; "
            "disk_read_throughput=3003.733333;;;; "
            "disk_average_wait=0.000777;;;;",
            "Disk IO SUMMARY",
        )

        self.assertEqual([metric["unit"] for metric in cpu], ["%", "%", "%"])
        self.assertEqual([metric["unit"] for metric in memory], ["B", "%"])
        self.assertEqual([metric["unit"] for metric in filesystem], ["MB", "%"])
        self.assertEqual([metric["unit"] for metric in disk], ["%", "B/s", "s"])

    def test_matches_case_insensitive_wildcards_and_regex(self):
        self.assertTrue(match_any("STR-QSV-1", ["*qsv*"]))
        self.assertTrue(match_any("CPU utilization", [r"re:^cpu\s+util"]))
        self.assertFalse(match_any("Memory", [r"re:^cpu"]))

    def test_reports_invalid_regex(self):
        self.assertEqual(
            invalid_regex_patterns(["*qsv*", "re:[broken"]), ["re:[broken"]
        )

    def test_exact_selection_and_patterns_are_combined(self):
        self.assertTrue(selection_allows("host-a", {"host-a"}, [], []))
        self.assertTrue(selection_allows("host-b", {"host-a"}, ["host-*"], []))
        self.assertFalse(selection_allows("db-a", {"host-a"}, ["host-*"], []))
        self.assertFalse(selection_allows("host-a", {"host-a"}, [], ["re:^host-a$"]))


if __name__ == "__main__":
    unittest.main()
