import sys
import unittest
from datetime import datetime
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from kite_market import IST, market_state


class MarketHoursTest(unittest.TestCase):
    def test_weekday_market_window_runs_from_9_to_330_ist(self):
        self.assertEqual(market_state(datetime(2026, 11, 18, 8, 59, tzinfo=IST)), "PREOPEN")
        self.assertEqual(market_state(datetime(2026, 11, 18, 9, 0, tzinfo=IST)), "OPEN")
        self.assertEqual(market_state(datetime(2026, 11, 18, 15, 29, 59, tzinfo=IST)), "OPEN")
        self.assertEqual(market_state(datetime(2026, 11, 18, 15, 30, tzinfo=IST)), "CLOSED")

    def test_weekends_are_closed(self):
        self.assertEqual(market_state(datetime(2026, 11, 21, 10, 0, tzinfo=IST)), "CLOSED")


if __name__ == "__main__":
    unittest.main()
