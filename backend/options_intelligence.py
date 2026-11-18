from __future__ import annotations

import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone


DIRECTION_VALUES = {"BULLISH", "BEARISH", "SIDEWAYS", "MIXED", "INSUFFICIENT DATA"}

DEFAULT_WEIGHTS = {
    "call_long_buildup": 3.0,
    "call_short_buildup": 3.2,
    "call_short_covering": 2.2,
    "call_long_unwinding": 1.8,
    "put_long_buildup": 3.0,
    "put_short_buildup": 3.2,
    "put_short_covering": 2.2,
    "put_long_unwinding": 1.8,
    "atm": 1.65,
    "near_1": 1.35,
    "near_2": 1.12,
    "far": 0.82,
    "volume_confirmation": 0.45,
    "premium_threshold_pct": 0.45,
    "oi_threshold_contracts": 1,
    "spot_momentum": 1.3,
    "trend_weight": 1.15,
    "live_weight": 1.0,
    "pcr_weight": 0.9,
    "vwap_weight": 0.7,
}


@dataclass(frozen=True)
class SideSignal:
    positioning: str
    directional_bias: str
    bullish_score: float
    bearish_score: float
    reason: str


def merge_weights(config=None):
    weights = deepcopy(DEFAULT_WEIGHTS)
    if isinstance(config, dict):
        for key, value in config.items():
            try:
                weights[key] = float(value)
            except (TypeError, ValueError):
                continue
    return weights


def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def safe_num(value, default=0.0):
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        pass
    return default


def round2(value):
    value = safe_num(value)
    return round(value, 2)


def percent_change(current, previous):
    current = safe_num(current)
    previous = safe_num(previous)
    if previous <= 0:
        return 0.0
    return ((current - previous) / previous) * 100


def classify_position(price_change, oi_change, premium_threshold_pct=0.0, oi_threshold=0):
    if abs(price_change) < premium_threshold_pct or abs(oi_change) < oi_threshold:
        return "Neutral"
    if price_change > 0 and oi_change > 0:
        return "Long Build-up"
    if price_change < 0 and oi_change > 0:
        return "Short Build-up"
    if price_change > 0 and oi_change < 0:
        return "Short Covering"
    if price_change < 0 and oi_change < 0:
        return "Long Unwinding"
    return "Neutral"


def interpret_position(side, positioning, weight=1.0, volume_confirmed=False, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    side = str(side or "").upper()
    positioning = positioning or "Neutral"
    volume_bonus = weights["volume_confirmation"] if volume_confirmed else 0.0

    table = {
        ("CE", "Long Build-up"): ("BULLISH", weights["call_long_buildup"], 0.0, "Call buyers added OI while CE premium rose."),
        ("CE", "Short Build-up"): ("BEARISH", 0.0, weights["call_short_buildup"], "Call writers added OI while CE premium fell."),
        ("CE", "Short Covering"): ("BULLISH", weights["call_short_covering"], 0.0, "Call shorts covered as CE premium rose."),
        ("CE", "Long Unwinding"): ("BEARISH", 0.0, weights["call_long_unwinding"], "Call longs exited while CE premium fell."),
        ("PE", "Long Build-up"): ("BEARISH", 0.0, weights["put_long_buildup"], "Put buyers added OI while PE premium rose."),
        ("PE", "Short Build-up"): ("BULLISH", weights["put_short_buildup"], 0.0, "Put writers added OI while PE premium fell."),
        ("PE", "Short Covering"): ("BEARISH", 0.0, weights["put_short_covering"], "Put shorts covered as PE premium rose."),
        ("PE", "Long Unwinding"): ("BULLISH", weights["put_long_unwinding"], 0.0, "Put longs exited while PE premium fell."),
    }
    bias, bull, bear, reason = table.get((side, positioning), ("SIDEWAYS", 0.0, 0.0, "No meaningful premium and OI change."))
    if bull:
        bull += volume_bonus
    if bear:
        bear += volume_bonus
    return SideSignal(positioning, bias, bull * weight, bear * weight, reason)


def bias_from_scores(bullish_score, bearish_score, min_total=3.0, mixed_gap=0.18):
    bullish_score = safe_num(bullish_score)
    bearish_score = safe_num(bearish_score)
    total = bullish_score + bearish_score
    if total < min_total:
        return "INSUFFICIENT DATA", 0
    diff = bullish_score - bearish_score
    ratio = abs(diff) / total if total else 0
    confidence = int(round(min(96, max(18, ratio * 100))))
    if ratio < mixed_gap:
        return ("SIDEWAYS" if total >= 7 else "MIXED"), confidence
    return ("BULLISH" if diff > 0 else "BEARISH"), confidence


def strike_weight(strike, atm, step, weights):
    distance = abs(safe_num(strike) - safe_num(atm))
    if step <= 0:
        return weights["far"]
    buckets = round(distance / step)
    if buckets == 0:
        return weights["atm"]
    if buckets == 1:
        return weights["near_1"]
    if buckets == 2:
        return weights["near_2"]
    return weights["far"]


def nearest_atm(spot, rows):
    if not rows:
        return None
    spot = safe_num(spot)
    if spot > 0:
        return min(rows, key=lambda row: abs(safe_num(row.get("strike")) - spot)).get("strike")
    return max(rows, key=lambda row: safe_num(row.get("call_oi")) + safe_num(row.get("put_oi"))).get("strike")


def infer_step(rows):
    strikes = sorted({safe_num(row.get("strike")) for row in rows if safe_num(row.get("strike")) > 0})
    gaps = [round(strikes[i] - strikes[i - 1]) for i in range(1, len(strikes)) if strikes[i] > strikes[i - 1]]
    if not gaps:
        return 50
    return min(gaps, key=lambda gap: abs(gap - 50))


def rows_by_strike(snapshot):
    return {safe_num(row.get("strike")): row for row in snapshot.get("rows", [])}


def row_delta(row, previous_row, prefix, field):
    return safe_num(row.get(f"{prefix}_{field}")) - safe_num((previous_row or {}).get(f"{prefix}_{field}"))


def build_strike_analysis(snapshot, previous_snapshot=None, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    rows = snapshot.get("rows") or []
    prev_rows = rows_by_strike(previous_snapshot or {})
    atm = snapshot.get("atm") or nearest_atm(snapshot.get("spot"), rows)
    step = snapshot.get("strike_step") or infer_step(rows)
    strike_rows = []
    totals = defaultdict(float)
    explanations = []

    for row in rows:
        strike = safe_num(row.get("strike"))
        prev = prev_rows.get(strike, {})
        weight = strike_weight(strike, atm, step, weights)
        call_price_change = row_delta(row, prev, "call", "ltp")
        put_price_change = row_delta(row, prev, "put", "ltp")
        call_price_pct = percent_change(row.get("call_ltp"), prev.get("call_ltp"))
        put_price_pct = percent_change(row.get("put_ltp"), prev.get("put_ltp"))
        call_oi_change = row_delta(row, prev, "call", "oi")
        put_oi_change = row_delta(row, prev, "put", "oi")
        call_volume_change = max(0.0, row_delta(row, prev, "call", "volume"))
        put_volume_change = max(0.0, row_delta(row, prev, "put", "volume"))
        call_volume_confirmed = call_volume_change > 0
        put_volume_confirmed = put_volume_change > 0

        call_position = classify_position(
            call_price_pct,
            call_oi_change,
            weights["premium_threshold_pct"],
            weights["oi_threshold_contracts"],
        )
        put_position = classify_position(
            put_price_pct,
            put_oi_change,
            weights["premium_threshold_pct"],
            weights["oi_threshold_contracts"],
        )
        call_signal = interpret_position("CE", call_position, weight, call_volume_confirmed, weights)
        put_signal = interpret_position("PE", put_position, weight, put_volume_confirmed, weights)

        bullish = call_signal.bullish_score + put_signal.bullish_score
        bearish = call_signal.bearish_score + put_signal.bearish_score
        totals["bullish"] += bullish
        totals["bearish"] += bearish

        row_payload = {
            "strike": row.get("strike"),
            "weight": round2(weight),
            "call": {
                "ltp": row.get("call_ltp"),
                "oi": row.get("call_oi"),
                "volume": row.get("call_volume"),
                "change_oi": round2(call_oi_change),
                "change_ltp": round2(call_price_change),
                "change_ltp_pct": round2(call_price_pct),
                "positioning": call_position,
                "bias": call_signal.directional_bias,
                "score": round2(call_signal.bullish_score - call_signal.bearish_score),
            },
            "put": {
                "ltp": row.get("put_ltp"),
                "oi": row.get("put_oi"),
                "volume": row.get("put_volume"),
                "change_oi": round2(put_oi_change),
                "change_ltp": round2(put_price_change),
                "change_ltp_pct": round2(put_price_pct),
                "positioning": put_position,
                "bias": put_signal.directional_bias,
                "score": round2(put_signal.bullish_score - put_signal.bearish_score),
            },
            "net_score": round2(bullish - bearish),
            "is_atm": strike == safe_num(atm),
        }
        strike_rows.append(row_payload)

    strike_rows.sort(key=lambda item: safe_num(item["strike"]))
    notable = sorted(strike_rows, key=lambda item: abs(item["net_score"]), reverse=True)[:5]
    for item in notable:
        if abs(item["net_score"]) < 0.5:
            continue
        side = "bullish" if item["net_score"] > 0 else "bearish"
        explanations.append(
            f"{int(item['strike'])}: {side} pressure from CE {item['call']['positioning']} and PE {item['put']['positioning']}."
        )

    return {
        "atm": atm,
        "strike_step": step,
        "rows": strike_rows,
        "bullish_score": round2(totals["bullish"]),
        "bearish_score": round2(totals["bearish"]),
        "explanations": explanations,
    }


def compute_pcr(rows):
    call_oi = sum(safe_num(row.get("call_oi")) for row in rows)
    put_oi = sum(safe_num(row.get("put_oi")) for row in rows)
    return {
        "total_call_oi": round2(call_oi),
        "total_put_oi": round2(put_oi),
        "pcr": round2(put_oi / call_oi) if call_oi > 0 else None,
    }


def compute_max_pain(rows):
    if not rows:
        return None
    strikes = sorted({safe_num(row.get("strike")) for row in rows if safe_num(row.get("strike")) > 0})
    if not strikes:
        return None
    best = None
    for expiry_strike in strikes:
        pain = 0.0
        for row in rows:
            strike = safe_num(row.get("strike"))
            pain += max(0.0, expiry_strike - strike) * safe_num(row.get("call_oi"))
            pain += max(0.0, strike - expiry_strike) * safe_num(row.get("put_oi"))
        if best is None or pain < best["pain"]:
            best = {"strike": expiry_strike, "pain": pain}
    return int(best["strike"]) if best else None


def support_resistance(rows, atm, previous_levels=None):
    below = [row for row in rows if safe_num(row.get("strike")) <= safe_num(atm)]
    above = [row for row in rows if safe_num(row.get("strike")) >= safe_num(atm)]
    support = max(below or rows, key=lambda row: safe_num(row.get("put_oi")), default={})
    resistance = max(above or rows, key=lambda row: safe_num(row.get("call_oi")), default={})
    prev_support = safe_num((previous_levels or {}).get("support"))
    prev_resistance = safe_num((previous_levels or {}).get("resistance"))
    support_value = safe_num(support.get("strike"))
    resistance_value = safe_num(resistance.get("strike"))
    return {
        "support": int(support_value) if support_value else None,
        "support_oi": round2(safe_num(support.get("put_oi"))),
        "resistance": int(resistance_value) if resistance_value else None,
        "resistance_oi": round2(safe_num(resistance.get("call_oi"))),
        "support_shift": round2(support_value - prev_support) if prev_support else 0,
        "resistance_shift": round2(resistance_value - prev_resistance) if prev_resistance else 0,
    }


def aggregate_trend(history, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    if len(history) < 2:
        return {
            "direction": "INSUFFICIENT DATA",
            "confidence": 0,
            "bullish_score": 0,
            "bearish_score": 0,
            "explanations": ["Need at least two aligned snapshots for trend bias."],
        }
    base = history[0]
    latest = history[-1]
    strike = build_strike_analysis(latest, base, weights)
    direction, confidence = bias_from_scores(strike["bullish_score"], strike["bearish_score"])
    return {
        "direction": direction,
        "confidence": confidence,
        "bullish_score": strike["bullish_score"],
        "bearish_score": strike["bearish_score"],
        "explanations": strike["explanations"][:4],
    }


def detect_market_events(snapshot, previous_snapshot, levels, previous_levels):
    events = []
    spot = safe_num(snapshot.get("spot"))
    prev_spot = safe_num((previous_snapshot or {}).get("spot"))
    if not spot or not prev_spot:
        return events
    if levels.get("resistance") and prev_spot <= levels["resistance"] < spot:
        events.append(f"Breakout watch: NIFTY moved above call resistance {levels['resistance']}.")
    if levels.get("support") and prev_spot >= levels["support"] > spot:
        events.append(f"Breakdown watch: NIFTY slipped below put support {levels['support']}.")
    if previous_levels:
        if levels.get("support_shift"):
            direction = "higher" if levels["support_shift"] > 0 else "lower"
            events.append(f"Support shifted {direction} by {abs(int(levels['support_shift']))} points.")
        if levels.get("resistance_shift"):
            direction = "higher" if levels["resistance_shift"] > 0 else "lower"
            events.append(f"Resistance shifted {direction} by {abs(int(levels['resistance_shift']))} points.")
    return events


def overall_bias(live, trend, snapshot, previous_snapshot, pcr_data, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    bullish = safe_num(live["bullish_score"]) * weights["live_weight"]
    bearish = safe_num(live["bearish_score"]) * weights["live_weight"]
    bullish += safe_num(trend["bullish_score"]) * weights["trend_weight"]
    bearish += safe_num(trend["bearish_score"]) * weights["trend_weight"]
    explanations = []

    pcr = pcr_data.get("pcr")
    if pcr is not None:
        if pcr >= 1.15:
            bullish += weights["pcr_weight"]
            explanations.append(f"PCR {pcr:.2f} shows stronger put OI cushion.")
        elif pcr <= 0.85:
            bearish += weights["pcr_weight"]
            explanations.append(f"PCR {pcr:.2f} shows call OI dominance.")

    spot = safe_num(snapshot.get("spot"))
    prev_spot = safe_num((previous_snapshot or {}).get("spot"))
    if spot and prev_spot:
        spot_change = spot - prev_spot
        if spot_change > 0:
            bullish += weights["spot_momentum"]
            explanations.append(f"NIFTY spot is up {spot_change:.2f} from the prior snapshot.")
        elif spot_change < 0:
            bearish += weights["spot_momentum"]
            explanations.append(f"NIFTY spot is down {abs(spot_change):.2f} from the prior snapshot.")

    spot_vwap = safe_num(snapshot.get("spot_vwap"))
    if spot and spot_vwap:
        if spot > spot_vwap:
            bullish += weights["vwap_weight"]
            explanations.append("Spot is trading above VWAP.")
        elif spot < spot_vwap:
            bearish += weights["vwap_weight"]
            explanations.append("Spot is trading below VWAP.")

    direction, confidence = bias_from_scores(bullish, bearish, min_total=4.0)
    if live["direction"] != "INSUFFICIENT DATA" and trend["direction"] != "INSUFFICIENT DATA":
        if live["direction"] != trend["direction"] and live["direction"] not in {"MIXED", "SIDEWAYS"}:
            direction = "MIXED" if direction not in {"BULLISH", "BEARISH"} else direction
            confidence = max(20, confidence - 12)
            explanations.append(f"Live bias ({live['direction']}) conflicts with trend bias ({trend['direction']}).")

    return {
        "direction": direction,
        "confidence": confidence,
        "bullish_score": round2(bullish),
        "bearish_score": round2(bearish),
        "explanations": explanations,
    }


def analyze_options_market(current_snapshot, history=None, config=None):
    weights = merge_weights(config)
    history = list(history or [])
    previous = history[-1] if history else None
    rows = current_snapshot.get("rows") or []
    timestamp = current_snapshot.get("timestamp") or iso_now()

    if not rows:
        return {
            "timestamp": timestamp,
            "direction": "INSUFFICIENT DATA",
            "confidence": 0,
            "error": "No option-chain rows available.",
            "live_bias": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "trend_bias": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "overall_bias": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "strikes": [],
        }

    pcr = compute_pcr(rows)
    atm = current_snapshot.get("atm") or nearest_atm(current_snapshot.get("spot"), rows)
    previous_levels = (previous or {}).get("levels") or {}
    levels = support_resistance(rows, atm, previous_levels)
    current_snapshot = deepcopy(current_snapshot)
    current_snapshot["atm"] = atm
    current_snapshot["levels"] = levels
    max_pain = compute_max_pain(rows)

    if previous:
        live_strikes = build_strike_analysis(current_snapshot, previous, weights)
        live_direction, live_confidence = bias_from_scores(
            live_strikes["bullish_score"],
            live_strikes["bearish_score"],
        )
    else:
        live_strikes = build_strike_analysis(current_snapshot, None, weights)
        live_direction, live_confidence = "INSUFFICIENT DATA", 0

    trend_window = (history + [current_snapshot])[-5:]
    trend = aggregate_trend(trend_window, weights)
    live = {
        "direction": live_direction,
        "confidence": live_confidence,
        "bullish_score": live_strikes["bullish_score"],
        "bearish_score": live_strikes["bearish_score"],
        "explanations": live_strikes["explanations"][:5],
    }
    overall = overall_bias(live, trend, current_snapshot, previous, pcr, weights)
    events = detect_market_events(current_snapshot, previous, levels, previous_levels)

    stale_rows = [
        row.get("strike")
        for row in rows
        if row.get("is_stale") or row.get("call_stale") or row.get("put_stale")
    ]
    conflicts = []
    if live["direction"] != "INSUFFICIENT DATA" and trend["direction"] != "INSUFFICIENT DATA":
        if live["direction"] != trend["direction"]:
            conflicts.append(f"Live bias is {live['direction']} while trend bias is {trend['direction']}.")
    if stale_rows:
        conflicts.append(f"{len(stale_rows)} strikes have stale or partial ticks.")

    explanations = []
    explanations.extend(overall["explanations"])
    explanations.extend(live["explanations"][:3])
    explanations.extend(trend["explanations"][:2])
    explanations.extend(events)
    if not explanations:
        explanations.append("Signals are balanced or still building; wait for clearer OI and premium confirmation.")

    return {
        "timestamp": timestamp,
        "instrument": current_snapshot.get("instrument", "NIFTY"),
        "expiry": current_snapshot.get("expiry"),
        "spot": current_snapshot.get("spot"),
        "atm": int(safe_num(atm)) if atm else None,
        "direction": overall["direction"] if overall["direction"] in DIRECTION_VALUES else "MIXED",
        "confidence": overall["confidence"],
        "live_bias": live,
        "trend_bias": trend,
        "overall_bias": overall,
        "bullish_score": overall["bullish_score"],
        "bearish_score": overall["bearish_score"],
        "pcr": pcr.get("pcr"),
        "total_call_oi": pcr.get("total_call_oi"),
        "total_put_oi": pcr.get("total_put_oi"),
        "max_pain": max_pain,
        "support_resistance": levels,
        "atm_iv": current_snapshot.get("atm_iv"),
        "iv_percentile": current_snapshot.get("iv_percentile"),
        "iv_note": current_snapshot.get("iv_note") or "IV is unavailable unless supplied by the data source or a separate IV model.",
        "vwap": current_snapshot.get("spot_vwap"),
        "strikes": live_strikes["rows"],
        "events": events,
        "conflicts": conflicts,
        "explanations": explanations[:10],
        "data_quality": {
            "snapshot_count": len(history) + 1,
            "has_previous_snapshot": previous is not None,
            "stale_strikes": stale_rows[:12],
            "status": "ok" if not stale_rows else "partial",
        },
    }
