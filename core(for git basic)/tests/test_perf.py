import unittest

from stdedit.perf import PerfMeter, format_bytes


class TestPerf(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(None), "RAM --")
        self.assertEqual(format_bytes(1024 * 1024), "RAM 1.0 MB")

    def test_meter_frame(self):
        meter = PerfMeter(interval=0)
        start = meter.frame_start()
        meter.frame_end(start)
        self.assertGreaterEqual(meter.frame_ms, 0.0)
        self.assertTrue(meter.label().startswith("RAM "))


if __name__ == "__main__":
    unittest.main()
