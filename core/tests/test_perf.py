import sys
import unittest
from unittest import mock

from stdedit.perf import PerfMeter, format_bytes, rss_bytes


class TestPerf(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(None), "RAM --")
        self.assertEqual(format_bytes(1024 * 1024), "RAM 1.0 MB")
        self.assertEqual(format_bytes(0), "RAM 0.0 B")
        self.assertEqual(format_bytes(1024), "RAM 1.0 KB")

    def test_meter_frame(self):
        meter = PerfMeter(interval=0)
        start = meter.frame_start()
        meter.frame_end(start)
        self.assertGreaterEqual(meter.frame_ms, 0.0)
        self.assertTrue(meter.label().startswith("RAM "))

    @unittest.skipUnless(sys.platform == "linux", "requires /proc")
    def test_rss_bytes_reports_positive_int(self):
        self.assertIsInstance(rss_bytes(), int)
        self.assertGreater(rss_bytes(), 0)

    def test_rss_bytes_none_when_proc_unavailable(self):
        with mock.patch("builtins.open", side_effect=OSError("no /proc")):
            self.assertIsNone(rss_bytes())

    def test_meter_label_without_sample_shows_dash(self):
        meter = PerfMeter(interval=999)
        self.assertEqual(meter.label(), "RAM --  0.0 ms")


if __name__ == "__main__":
    unittest.main()
