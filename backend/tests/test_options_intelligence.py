import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from options_intelligence import analyze_options_market, classify_position


def snapshot(spot, rows, timestamp="2026-11-18T09:15:00+00:00"):
    return {
        "timestamp": timestamp,
        "instrument": "NIFTY",
        "expiry": "2026-11-19",
        "spot": spot,
        "atm": 22500,
        "strike_step": 50,
        "rows": rows,
    }


class OptionsIntelligenceTest(unittest.TestCase):
    def test_classifies_standard_positioning_types(self):
        self.assertEqual(classify_position(1.2, 100, 0.1, 1), "Long Build-up")
        self.assertEqual(classify_position(-1.2, 100, 0.1, 1), "Short Build-up")
        self.assertEqual(classify_position(1.2, -100, 0.1, 1), "Short Covering")
        self.assertEqual(classify_position(-1.2, -100, 0.1, 1), "Long Unwinding")
        self.assertEqual(classify_position(0.01, 100, 0.1, 1), "Neutral")

    def test_bullish_direction_from_call_buying_and_put_writing(self):
        prev = snapshot(22490, [
            {"strike": 22450, "call_ltp": 120, "call_oi": 800, "call_volume": 1000, "put_ltp": 82, "put_oi": 1200, "put_volume": 900},
            {"strike": 22500, "call_ltp": 100, "call_oi": 1000, "call_volume": 1100, "put_ltp": 100, "put_oi": 1000, "put_volume": 1200},
            {"strike": 22550, "call_ltp": 78, "call_oi": 1300, "call_volume": 900, "put_ltp": 125, "put_oi": 850, "put_volume": 800},
        ])
        curr = snapshot(22525, [
            {"strike": 22450, "call_ltp": 123, "call_oi": 830, "call_volume": 1300, "put_ltp": 79, "put_oi": 1280, "put_volume": 1220},
            {"strike": 22500, "call_ltp": 112, "call_oi": 1250, "call_volume": 1700, "put_ltp": 90, "put_oi": 1350, "put_volume": 1800},
            {"strike": 22550, "call_ltp": 84, "call_oi": 1420, "call_volume": 1250, "put_ltp": 119, "put_oi": 930, "put_volume": 1110},
        ], "2026-11-18T09:18:00+00:00")

        result = analyze_options_market(curr, [prev])

        self.assertEqual(result["direction"], "BULLISH")
        self.assertGreater(result["bullish_score"], result["bearish_score"])
        self.assertEqual(result["live_bias"]["direction"], "BULLISH")
        atm = next(row for row in result["strikes"] if row["is_atm"])
        self.assertEqual(atm["call"]["positioning"], "Long Build-up")
        self.assertEqual(atm["put"]["positioning"], "Short Build-up")

    def test_bearish_direction_from_call_writing_and_put_buying(self):
        prev = snapshot(22510, [
            {"strike": 22450, "call_ltp": 122, "call_oi": 800, "call_volume": 1000, "put_ltp": 80, "put_oi": 1200, "put_volume": 900},
            {"strike": 22500, "call_ltp": 105, "call_oi": 1000, "call_volume": 1100, "put_ltp": 94, "put_oi": 1000, "put_volume": 1200},
            {"strike": 22550, "call_ltp": 82, "call_oi": 1300, "call_volume": 900, "put_ltp": 118, "put_oi": 850, "put_volume": 800},
        ])
        curr = snapshot(22475, [
            {"strike": 22450, "call_ltp": 116, "call_oi": 930, "call_volume": 1400, "put_ltp": 87, "put_oi": 1350, "put_volume": 1400},
            {"strike": 22500, "call_ltp": 93, "call_oi": 1320, "call_volume": 1800, "put_ltp": 108, "put_oi": 1290, "put_volume": 1750},
            {"strike": 22550, "call_ltp": 76, "call_oi": 1510, "call_volume": 1350, "put_ltp": 127, "put_oi": 980, "put_volume": 1130},
        ], "2026-11-18T09:18:00+00:00")

        result = analyze_options_market(curr, [prev])

        self.assertEqual(result["direction"], "BEARISH")
        self.assertGreater(result["bearish_score"], result["bullish_score"])
        self.assertEqual(result["live_bias"]["direction"], "BEARISH")
        atm = next(row for row in result["strikes"] if row["is_atm"])
        self.assertEqual(atm["call"]["positioning"], "Short Build-up")
        self.assertEqual(atm["put"]["positioning"], "Long Build-up")


if __name__ == "__main__":
    unittest.main()
