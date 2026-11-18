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


def focus_rows(call_ltp=100, put_ltp=100, call_oi=1000, put_oi=1000, volume=1000, extra=False):
    strikes = [22400, 22450, 22500, 22550, 22600]
    if extra:
        strikes = [22350, *strikes, 22650]
    rows = []
    for strike in strikes:
        rows.append({
            "strike": strike,
            "call_ltp": call_ltp,
            "call_oi": call_oi,
            "call_volume": volume,
            "put_ltp": put_ltp,
            "put_oi": put_oi,
            "put_volume": volume,
        })
    return rows


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

    def test_only_atm_plus_minus_two_strikes_drive_scoring(self):
        prev = snapshot(22500, focus_rows(extra=True))
        curr_rows = focus_rows(call_ltp=106, call_oi=1120, put_ltp=94, put_oi=1120, volume=1400, extra=True)
        curr_rows[0].update({"call_ltp": 1, "call_oi": 100000, "put_ltp": 500, "put_oi": 100000})
        curr_rows[-1].update({"call_ltp": 1, "call_oi": 100000, "put_ltp": 500, "put_oi": 100000})
        curr = snapshot(22500, curr_rows, "2026-11-18T09:18:00+00:00")

        result = analyze_options_market(curr, [prev])

        self.assertEqual([row["strike"] for row in result["strikes"]], [22400, 22450, 22500, 22550, 22600])
        self.assertEqual(result["live_bias"]["target_strikes"], [22400, 22450, 22500, 22550, 22600])
        self.assertEqual(result["live_bias"]["direction"], "BULLISH")

    def test_live_trend_conflict_becomes_mixed_overall(self):
        s0 = snapshot(22500, focus_rows(), "2026-11-18T09:15:00+00:00")
        s1 = snapshot(22510, focus_rows(call_ltp=105, call_oi=1100, put_ltp=95, put_oi=1100, volume=1200), "2026-11-18T09:18:00+00:00")
        s2 = snapshot(22520, focus_rows(call_ltp=110, call_oi=1200, put_ltp=90, put_oi=1200, volume=1400), "2026-11-18T09:21:00+00:00")
        s3 = snapshot(22530, focus_rows(call_ltp=115, call_oi=1300, put_ltp=85, put_oi=1300, volume=1600), "2026-11-18T09:24:00+00:00")
        curr = snapshot(22505, focus_rows(call_ltp=107, call_oi=1460, put_ltp=93, put_oi=1460, volume=1800), "2026-11-18T09:27:00+00:00")

        result = analyze_options_market(curr, [s0, s1, s2, s3])

        self.assertEqual(result["live_bias"]["direction"], "BEARISH")
        self.assertEqual(result["trend_bias"]["direction"], "BULLISH")
        self.assertEqual(result["trend_bias"]["agreement_with_live"], "Conflicts")
        self.assertEqual(result["direction"], "MIXED")
        self.assertEqual(result["day_trend"]["direction"], "BULLISH")
        self.assertEqual(result["day_trend"]["interval_count"], 4)

    def test_change_windows_include_five_minute_and_session_numbers(self):
        s0 = snapshot(22500, focus_rows(), "2026-11-18T09:15:00+00:00")
        s1 = snapshot(22515, focus_rows(call_ltp=104, call_oi=1100, put_ltp=96, put_oi=1080, volume=1200), "2026-11-18T09:18:00+00:00")
        curr = snapshot(22530, focus_rows(call_ltp=110, call_oi=1250, put_ltp=90, put_oi=1200, volume=1500), "2026-11-18T09:21:00+00:00")

        result = analyze_options_market(curr, [s0, s1], day_history=[s0, s1])

        windows = result["change_windows"]
        self.assertTrue(windows["3m"]["available"])
        self.assertTrue(windows["5m"]["available"])
        self.assertTrue(windows["session"]["available"])
        self.assertEqual(windows["5m"]["baseline_timestamp"], s0["timestamp"])
        self.assertGreater(windows["session"]["change"]["call_oi_change_pct"], 0)
        self.assertEqual(len(windows["15m"]["rows"]), 5)

    def test_current_bucket_in_history_is_not_used_as_previous_snapshot(self):
        s0 = snapshot(22500, focus_rows(), "2026-11-18T09:15:00+00:00")
        curr = snapshot(22530, focus_rows(call_ltp=110, call_oi=1250, put_ltp=90, put_oi=1200, volume=1500), "2026-11-18T09:18:00+00:00")

        result = analyze_options_market(curr, [s0, curr], day_history=[s0, curr])

        self.assertTrue(result["change_windows"]["3m"]["available"])
        self.assertEqual(result["change_windows"]["3m"]["baseline_timestamp"], s0["timestamp"])
        self.assertGreater(result["change_windows"]["3m"]["change"]["call_oi_change"], 0)


if __name__ == "__main__":
    unittest.main()
