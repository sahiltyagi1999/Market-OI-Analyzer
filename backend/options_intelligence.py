from __future__ import annotations

import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


DIRECTION_VALUES = {"BULLISH", "BEARISH", "SIDEWAYS", "MIXED", "INSUFFICIENT DATA", "NEUTRAL"}
ACTIVE_DIRECTIONS = {"BULLISH", "BEARISH"}

DEFAULT_WEIGHTS = {
    "call_long_buildup": 2.4,
    "call_short_buildup": 2.6,
    "call_short_covering": 1.8,
    "call_long_unwinding": 1.6,
    "put_long_buildup": 2.4,
    "put_short_buildup": 2.6,
    "put_short_covering": 1.8,
    "put_long_unwinding": 1.6,
    "atm": 1.5,
    "near_1": 1.25,
    "near_2": 1.0,
    "volume_confirmation": 0.25,
    "premium_threshold_pct": 0.35,
    "premium_threshold_abs": 0.05,
    "oi_threshold_contracts": 1,
    "oi_threshold_pct": 0.05,
    "spot_momentum": 0.8,
    "trend_weight": 1.05,
    "live_weight": 1.0,
    "pcr_weight": 0.45,
    "vwap_weight": 0.45,
    "conflict_penalty": 18,
}

POSITION_MATRIX = {
    (1, 1): "Long Build-up",
    (1, -1): "Short Build-up",
    (-1, 1): "Short Covering",
    (-1, -1): "Long Unwinding",
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
    return round(safe_num(value), 2)


def percent_change(current, previous):
    current = safe_num(current)
    previous = safe_num(previous)
    if previous <= 0:
        return 0.0
    return ((current - previous) / previous) * 100


def parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snapshot_time(snapshot):
    return parse_timestamp((snapshot or {}).get("timestamp"))


def seconds_between(current, previous):
    current_time = snapshot_time(current)
    previous_time = snapshot_time(previous)
    if not current_time or not previous_time:
        return None
    return max(0, int((current_time - previous_time).total_seconds()))


def normalize_history(snapshots, current_snapshot=None):
    current_time = snapshot_time(current_snapshot)
    keyed = {}
    fallback = []
    for item in snapshots or []:
        if not item:
            continue
        item_time = snapshot_time(item)
        if current_time and item_time and item_time >= current_time:
            continue
        if item_time:
            keyed[item_time.isoformat()] = item
        else:
            fallback.append(item)
    ordered = [keyed[key] for key in sorted(keyed)]
    return fallback + ordered


def movement_sign(value, abs_threshold=0.0):
    value = safe_num(value)
    threshold = abs(safe_num(abs_threshold))
    if abs(value) < threshold:
        return 0
    return 1 if value > 0 else -1


def classify_position(price_change, oi_change, premium_threshold_pct=0.0, oi_threshold=0):
    oi_sign = movement_sign(oi_change, oi_threshold)
    price_sign = movement_sign(price_change, premium_threshold_pct)
    if oi_sign == 0 or price_sign == 0:
        return "Neutral"
    return POSITION_MATRIX.get((oi_sign, price_sign), "Neutral")


def interpret_position(side, positioning, weight=1.0, volume_confirmed=False, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    side = str(side or "").upper()
    positioning = positioning or "Neutral"
    volume_bonus = weights["volume_confirmation"] if volume_confirmed else 0.0
    table = {
        ("CE", "Long Build-up"): ("BULLISH", weights["call_long_buildup"], 0.0, "Call buyers added OI while CE premium rose."),
        ("CE", "Short Build-up"): ("BEARISH", 0.0, weights["call_short_buildup"], "Call writers added OI while CE premium fell."),
        ("CE", "Short Covering"): ("BULLISH", weights["call_short_covering"], 0.0, "Call shorts covered while CE premium rose."),
        ("CE", "Long Unwinding"): ("BEARISH", 0.0, weights["call_long_unwinding"], "Call longs exited while CE premium fell."),
        ("PE", "Long Build-up"): ("BEARISH", 0.0, weights["put_long_buildup"], "Put buyers added OI while PE premium rose."),
        ("PE", "Short Build-up"): ("BULLISH", weights["put_short_buildup"], 0.0, "Put writers added OI while PE premium fell."),
        ("PE", "Short Covering"): ("BEARISH", 0.0, weights["put_short_covering"], "Put shorts covered while PE premium rose."),
        ("PE", "Long Unwinding"): ("BULLISH", weights["put_long_unwinding"], 0.0, "Put longs exited while PE premium fell."),
    }
    bias, bull, bear, reason = table.get((side, positioning), ("NEUTRAL", 0.0, 0.0, "No meaningful premium and OI change."))
    if bull:
        bull += volume_bonus
    if bear:
        bear += volume_bonus
    return SideSignal(positioning, bias, bull * weight, bear * weight, reason)


def normalized_bias(bullish_score, bearish_score, observations=0, stale_penalty=0, min_total=1.8):
    bullish_score = safe_num(bullish_score)
    bearish_score = safe_num(bearish_score)
    total = bullish_score + bearish_score
    if observations <= 0 or total < min_total:
        return "INSUFFICIENT DATA", 0
    diff = bullish_score - bearish_score
    ratio = abs(diff) / total if total else 0
    if ratio < 0.14:
        return "NEUTRAL", max(12, int(round(30 - stale_penalty)))
    confidence = 30 + min(52, ratio * 52)
    agreement_bonus = min(12, observations * 1.6)
    confidence = max(10, min(88, confidence + agreement_bonus - stale_penalty))
    return ("BULLISH" if diff > 0 else "BEARISH"), int(round(confidence))


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


def strike_label(strike, atm, step):
    strike = safe_num(strike)
    atm = safe_num(atm)
    step = safe_num(step) or 50
    offset = int(round((strike - atm) / step))
    if offset == 0:
        return "ATM"
    return f"ATM{offset:+d}"


def select_focus_rows(snapshot):
    rows = snapshot.get("rows") or []
    if not rows:
        return [], [], None, infer_step(rows)
    atm = snapshot.get("atm") or nearest_atm(snapshot.get("spot"), rows)
    step = snapshot.get("strike_step") or infer_step(rows)
    target_strikes = [safe_num(atm) + offset * safe_num(step) for offset in (-2, -1, 0, 1, 2)]
    row_map = rows_by_strike(snapshot)
    focus = []
    for strike in target_strikes:
        row = row_map.get(safe_num(strike))
        if row:
            item = dict(row)
            item["strike_label"] = strike_label(strike, atm, step)
            focus.append(item)
    return focus, target_strikes, atm, step


def strike_weight(label, weights):
    if label == "ATM":
        return weights["atm"]
    if label in {"ATM-1", "ATM+1"}:
        return weights["near_1"]
    return weights["near_2"]


def analyze_side(row, previous_row, side, label, weights):
    prefix = "call" if side == "CE" else "put"
    ltp = safe_num(row.get(f"{prefix}_ltp"))
    previous_ltp = safe_num((previous_row or {}).get(f"{prefix}_ltp"))
    oi = safe_num(row.get(f"{prefix}_oi"))
    previous_oi = safe_num((previous_row or {}).get(f"{prefix}_oi"))
    volume = safe_num(row.get(f"{prefix}_volume"))
    previous_volume = safe_num((previous_row or {}).get(f"{prefix}_volume"))
    premium_change = ltp - previous_ltp
    oi_change = oi - previous_oi
    premium_pct = percent_change(ltp, previous_ltp)
    oi_pct = percent_change(oi, previous_oi)
    volume_change = max(0.0, volume - previous_volume)
    has_previous = previous_row is not None and previous_ltp > 0 and previous_oi > 0
    premium_threshold = max(weights["premium_threshold_abs"], previous_ltp * weights["premium_threshold_pct"] / 100)
    oi_threshold = max(weights["oi_threshold_contracts"], previous_oi * weights["oi_threshold_pct"] / 100)
    position = "Insufficient Data"
    signal = SideSignal(position, "NEUTRAL", 0.0, 0.0, "Need previous aligned snapshot.")
    if has_previous:
        position = classify_position(premium_change, oi_change, premium_threshold, oi_threshold)
        signal = interpret_position(side, position, strike_weight(label, weights), volume_change > 0, weights)
    return {
        "ltp": round2(ltp),
        "oi": round2(oi),
        "exchange_change_oi": row.get(f"{prefix}_exchange_change_oi"),
        "volume": round2(volume),
        "interval_oi_change": round2(oi_change) if has_previous else None,
        "interval_premium_change": round2(premium_change) if has_previous else None,
        "interval_oi_change_pct": round2(oi_pct) if has_previous else None,
        "interval_premium_change_pct": round2(premium_pct) if has_previous else None,
        "volume_change": round2(volume_change) if has_previous else None,
        "positioning": position,
        "bias": signal.directional_bias,
        "score": round2(signal.bullish_score - signal.bearish_score),
        "_bullish": signal.bullish_score,
        "_bearish": signal.bearish_score,
    }


def public_side(side):
    return {key: value for key, value in side.items() if not key.startswith("_")}


def net_interpretation(bullish, bearish):
    diff = safe_num(bullish) - safe_num(bearish)
    total = safe_num(bullish) + safe_num(bearish)
    if total < 0.8 or abs(diff) / total < 0.15:
        return "NEUTRAL"
    return "BULLISH" if diff > 0 else "BEARISH"


def build_interval_analysis(current_snapshot, previous_snapshot=None, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    current = deepcopy(current_snapshot or {})
    previous = previous_snapshot or {}
    _, target_strikes, atm, step = select_focus_rows(current)
    current_rows = rows_by_strike(current)
    previous_rows = rows_by_strike(previous)
    totals = defaultdict(float)
    observations = 0
    rows = []
    missing = []

    for target in target_strikes:
        row = current_rows.get(safe_num(target))
        label = strike_label(target, atm, step)
        if not row:
            missing.append(int(target))
            continue
        previous_row = previous_rows.get(safe_num(target))
        call = analyze_side(row, previous_row, "CE", label, weights)
        put = analyze_side(row, previous_row, "PE", label, weights)
        bullish = call["_bullish"] + put["_bullish"]
        bearish = call["_bearish"] + put["_bearish"]
        if call["positioning"] not in {"Neutral", "Insufficient Data"}:
            observations += 1
        if put["positioning"] not in {"Neutral", "Insufficient Data"}:
            observations += 1
        totals["bullish"] += bullish
        totals["bearish"] += bearish
        rows.append({
            "label": label,
            "strike": int(safe_num(row.get("strike"))),
            "weight": round2(strike_weight(label, weights)),
            "call": public_side(call),
            "put": public_side(put),
            "net_score": round2(bullish - bearish),
            "net_interpretation": net_interpretation(bullish, bearish),
            "is_atm": label == "ATM",
        })

    direction, confidence = normalized_bias(totals["bullish"], totals["bearish"], observations)
    strongest = max(rows, key=lambda item: abs(safe_num(item.get("net_score"))), default=None)
    return {
        "atm": int(safe_num(atm)) if atm else None,
        "strike_step": int(safe_num(step)) if step else None,
        "target_strikes": [int(safe_num(strike)) for strike in target_strikes if safe_num(strike)],
        "rows": rows,
        "missing_strikes": missing,
        "direction": direction,
        "confidence": confidence,
        "bullish_score": round2(totals["bullish"]),
        "bearish_score": round2(totals["bearish"]),
        "observations": observations,
        "strongest_strike": strongest,
    }


def summarize_activity(rows, side):
    counter = Counter()
    bias_counter = Counter()
    for row in rows:
        item = row.get(side) or {}
        pos = item.get("positioning")
        if pos and pos not in {"Neutral", "Insufficient Data"}:
            counter[pos] += 1
            bias_counter[item.get("bias") or "NEUTRAL"] += 1
    if not counter:
        return "Neutral"
    position, count = counter.most_common(1)[0]
    bias = bias_counter.most_common(1)[0][0]
    side_name = "Call" if side == "call" else "Put"
    return f"{side_name} {position} ({bias.title()}) on {count} strike{'s' if count != 1 else ''}"


def interval_summary(interval, current_snapshot, previous_snapshot):
    rows = interval.get("rows") or []
    spot = safe_num(current_snapshot.get("spot"))
    prev_spot = safe_num((previous_snapshot or {}).get("spot"))
    spot_change = spot - prev_spot if spot and prev_spot else 0
    strongest = interval.get("strongest_strike") or {}
    strongest_text = "-"
    if strongest:
        strongest_text = f"{strongest.get('label')} {int(strongest.get('strike'))}: {strongest.get('net_interpretation')}"
    direction = interval.get("direction")
    if direction == "INSUFFICIENT DATA":
        changed = "Need one more synchronized 3-minute snapshot for live bias."
    elif direction == "NEUTRAL":
        changed = "No meaningful OI and premium shift across ATM +/-2."
    else:
        changed = f"{direction.title()} pressure increased across the five-strike window."
    return {
        "direction": direction,
        "confidence": interval.get("confidence", 0),
        "bullish_score": interval.get("bullish_score", 0),
        "bearish_score": interval.get("bearish_score", 0),
        "spot_change": round2(spot_change),
        "call_activity": summarize_activity(rows, "call"),
        "put_activity": summarize_activity(rows, "put"),
        "strongest_contributor": strongest_text,
        "what_changed": changed,
    }


def focus_totals(snapshot):
    rows, _, _, _ = select_focus_rows(snapshot or {})
    call_oi = sum(safe_num(row.get("call_oi")) for row in rows)
    put_oi = sum(safe_num(row.get("put_oi")) for row in rows)
    call_premium = sum(safe_num(row.get("call_ltp")) for row in rows)
    put_premium = sum(safe_num(row.get("put_ltp")) for row in rows)
    call_volume = sum(safe_num(row.get("call_volume")) for row in rows)
    put_volume = sum(safe_num(row.get("put_volume")) for row in rows)
    return {
        "spot": safe_num((snapshot or {}).get("spot")),
        "call_oi": call_oi,
        "put_oi": put_oi,
        "net_oi": put_oi - call_oi,
        "call_premium": call_premium,
        "put_premium": put_premium,
        "net_premium": call_premium - put_premium,
        "call_volume": call_volume,
        "put_volume": put_volume,
    }


def summarize_change(current_snapshot, previous_snapshot):
    current = focus_totals(current_snapshot)
    previous = focus_totals(previous_snapshot)
    fields = ("spot", "call_oi", "put_oi", "net_oi", "call_premium", "put_premium", "net_premium", "call_volume", "put_volume")
    summary = {}
    for field in fields:
        current_value = current[field]
        previous_value = previous[field]
        summary[field] = round2(current_value)
        summary[f"{field}_change"] = round2(current_value - previous_value)
        summary[f"{field}_change_pct"] = round2(percent_change(current_value, previous_value))
    return summary


def empty_window(key, label, reason):
    return {
        "key": key,
        "label": label,
        "available": False,
        "reason": reason,
        "direction": "INSUFFICIENT DATA",
        "confidence": 0,
        "bullish_score": 0,
        "bearish_score": 0,
        "rows": [],
        "change": {},
    }


def window_payload(key, label, current_snapshot, previous_snapshot, weights):
    if not previous_snapshot:
        return empty_window(key, label, "Need an older saved snapshot for this window.")
    interval = build_interval_analysis(current_snapshot, previous_snapshot, weights)
    elapsed = seconds_between(current_snapshot, previous_snapshot)
    return {
        "key": key,
        "label": label,
        "available": True,
        "direction": interval.get("direction"),
        "confidence": interval.get("confidence", 0),
        "bullish_score": interval.get("bullish_score", 0),
        "bearish_score": interval.get("bearish_score", 0),
        "observations": interval.get("observations", 0),
        "baseline_timestamp": previous_snapshot.get("timestamp"),
        "current_timestamp": current_snapshot.get("timestamp"),
        "elapsed_seconds": elapsed,
        "elapsed_minutes": round2(elapsed / 60) if elapsed is not None else None,
        "change": summarize_change(current_snapshot, previous_snapshot),
        "rows": interval.get("rows") or [],
        "missing_strikes": interval.get("missing_strikes") or [],
    }


def baseline_at_or_before(snapshots, current_snapshot, minutes):
    current_time = snapshot_time(current_snapshot)
    if not current_time:
        return None
    target_time = current_time - timedelta(minutes=minutes)
    candidates = [
        item for item in snapshots
        if item is not current_snapshot and snapshot_time(item) and snapshot_time(item) <= target_time
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: snapshot_time(item))


def build_change_windows(current_snapshot, history, day_snapshots, weights):
    history = list(history or [])
    day_snapshots = list(day_snapshots or [])
    previous = history[-1] if history else None
    trend_baseline = (history + [current_snapshot])[-5:][0] if history else None
    session_candidates = [item for item in day_snapshots if item is not current_snapshot]
    session_baseline = session_candidates[0] if session_candidates else None
    five_min_baseline = baseline_at_or_before(day_snapshots, current_snapshot, 5)
    return {
        "3m": window_payload("3m", "Last Snapshot", current_snapshot, previous, weights),
        "5m": window_payload("5m", "Last 5 Minutes", current_snapshot, five_min_baseline, weights),
        "15m": window_payload("15m", "Last 15 Minutes", current_snapshot, trend_baseline, weights),
        "session": window_payload("session", "Session Start", current_snapshot, session_baseline, weights),
    }


def aggregate_trend(history, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    snapshots = list(history or [])[-5:]
    if len(snapshots) < 2:
        return {
            "direction": "INSUFFICIENT DATA",
            "confidence": 0,
            "bullish_score": 0,
            "bearish_score": 0,
            "intervals": [],
            "trend_consistency": "Insufficient data",
            "momentum": "Unavailable",
            "dominant_positioning": "Need at least two snapshots.",
            "explanations": ["Need at least two aligned snapshots for 15-minute trend bias."],
        }
    intervals = []
    bullish = bearish = observations = 0.0
    directions = []
    positioning = Counter()
    net_abs = []
    for previous, current in zip(snapshots, snapshots[1:]):
        interval = build_interval_analysis(current, previous, weights)
        intervals.append(interval)
        bullish += safe_num(interval.get("bullish_score"))
        bearish += safe_num(interval.get("bearish_score"))
        observations += safe_num(interval.get("observations"))
        direction = interval.get("direction")
        if direction in ACTIVE_DIRECTIONS:
            directions.append(direction)
        net_abs.append(abs(safe_num(interval.get("bullish_score")) - safe_num(interval.get("bearish_score"))))
        for row in interval.get("rows") or []:
            for side in ("call", "put"):
                pos = (row.get(side) or {}).get("positioning")
                if pos and pos not in {"Neutral", "Insufficient Data"}:
                    positioning[pos] += 1
    direction, confidence = normalized_bias(bullish, bearish, observations, min_total=2.4)
    if directions:
        dominant = Counter(directions).most_common(1)[0]
        consistency_pct = round((dominant[1] / len(directions)) * 100)
        consistency = f"{consistency_pct}% {dominant[0].lower()} intervals"
    else:
        consistency = "Signals are balanced"
    if len(net_abs) >= 2:
        momentum = "Strengthening" if net_abs[-1] > net_abs[0] * 1.15 else "Weakening" if net_abs[-1] < net_abs[0] * 0.85 else "Stable"
    else:
        momentum = "Building"
    dominant_positioning = positioning.most_common(1)[0][0] if positioning else "Neutral"
    explanations = []
    if direction in ACTIVE_DIRECTIONS:
        explanations.append(f"15-minute trend is {direction.lower()} with {consistency}.")
    if momentum != "Unavailable":
        explanations.append(f"Momentum is {momentum.lower()} across aligned 3-minute intervals.")
    return {
        "direction": direction,
        "confidence": confidence,
        "bullish_score": round2(bullish),
        "bearish_score": round2(bearish),
        "intervals": compact_intervals(intervals),
        "trend_consistency": consistency,
        "momentum": momentum,
        "dominant_positioning": dominant_positioning,
        "explanations": explanations,
    }


def aggregate_day_trend(history, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    snapshots = list(history or [])
    if len(snapshots) < 2:
        return {
            "direction": "INSUFFICIENT DATA",
            "confidence": 0,
            "bullish_score": 0,
            "bearish_score": 0,
            "interval_count": 0,
            "trend_consistency": "Need more snapshots",
            "momentum": "Building",
            "dominant_positioning": "Insufficient data",
            "spot_change": 0,
            "buyers_vs_sellers": "Pending",
            "explanations": ["Day trend starts after at least two saved 3-minute snapshots."],
        }
    intervals = []
    bullish = bearish = observations = 0.0
    directions = []
    positioning = Counter()
    net_abs = []
    for previous, current in zip(snapshots, snapshots[1:]):
        interval = build_interval_analysis(current, previous, weights)
        intervals.append(interval)
        bullish += safe_num(interval.get("bullish_score"))
        bearish += safe_num(interval.get("bearish_score"))
        observations += safe_num(interval.get("observations"))
        direction = interval.get("direction")
        if direction in ACTIVE_DIRECTIONS:
            directions.append(direction)
        net_abs.append(abs(safe_num(interval.get("bullish_score")) - safe_num(interval.get("bearish_score"))))
        for row in interval.get("rows") or []:
            for side in ("call", "put"):
                pos = (row.get(side) or {}).get("positioning")
                if pos and pos not in {"Neutral", "Insufficient Data"}:
                    positioning[pos] += 1
    direction, confidence = normalized_bias(bullish, bearish, observations, min_total=3.0)
    if directions:
        dominant = Counter(directions).most_common(1)[0]
        consistency = f"{round((dominant[1] / len(directions)) * 100)}% {dominant[0].lower()} intervals"
    else:
        consistency = "Signals are balanced"
    recent = net_abs[-3:] if len(net_abs) >= 3 else net_abs
    early = net_abs[:3] if len(net_abs) >= 3 else net_abs
    recent_strength = sum(recent) / len(recent) if recent else 0
    early_strength = sum(early) / len(early) if early else 0
    momentum = "Strengthening" if recent_strength > early_strength * 1.15 else "Weakening" if recent_strength < early_strength * 0.85 else "Stable"
    first_spot = safe_num(snapshots[0].get("spot"))
    last_spot = safe_num(snapshots[-1].get("spot"))
    spot_change = last_spot - first_spot if first_spot and last_spot else 0
    if direction == "BULLISH":
        control = "Buyers gaining control"
    elif direction == "BEARISH":
        control = "Sellers gaining control"
    elif direction == "NEUTRAL":
        control = "Control balanced"
    else:
        control = "Pending"
    dominant_positioning = positioning.most_common(1)[0][0] if positioning else "Neutral"
    explanations = []
    if direction in ACTIVE_DIRECTIONS:
        explanations.append(f"Since market open, day trend is {direction.lower()} with {consistency}.")
    explanations.append(f"Session momentum is {momentum.lower()} across {len(intervals)} saved intervals.")
    if spot_change:
        explanations.append(f"NIFTY is {'up' if spot_change > 0 else 'down'} {abs(spot_change):.2f} from the first saved snapshot.")
    return {
        "direction": direction,
        "confidence": confidence,
        "bullish_score": round2(bullish),
        "bearish_score": round2(bearish),
        "interval_count": len(intervals),
        "trend_consistency": consistency,
        "momentum": momentum,
        "dominant_positioning": dominant_positioning,
        "spot_change": round2(spot_change),
        "buyers_vs_sellers": control,
        "first_snapshot_at": snapshots[0].get("timestamp"),
        "last_snapshot_at": snapshots[-1].get("timestamp"),
        "explanations": explanations[:4],
    }


def compact_intervals(intervals):
    return [{
        "direction": item.get("direction"),
        "confidence": item.get("confidence"),
        "bullish_score": item.get("bullish_score"),
        "bearish_score": item.get("bearish_score"),
        "observations": item.get("observations"),
    } for item in intervals]


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


def detect_market_events(snapshot, previous_snapshot, levels, previous_levels):
    events = []
    spot = safe_num(snapshot.get("spot"))
    prev_spot = safe_num((previous_snapshot or {}).get("spot"))
    if not spot or not prev_spot:
        return events
    if levels.get("resistance") and prev_spot <= levels["resistance"] < spot:
        events.append(f"NIFTY moved above resistance {levels['resistance']}.")
    if levels.get("support") and prev_spot >= levels["support"] > spot:
        events.append(f"NIFTY slipped below support {levels['support']}.")
    if previous_levels:
        if levels.get("support_shift"):
            direction = "higher" if levels["support_shift"] > 0 else "lower"
            events.append(f"Support shifted {direction} by {abs(int(levels['support_shift']))} points.")
        if levels.get("resistance_shift"):
            direction = "higher" if levels["resistance_shift"] > 0 else "lower"
            events.append(f"Resistance shifted {direction} by {abs(int(levels['resistance_shift']))} points.")
    return events


def data_quality(snapshot, status=None, previous=None):
    status = status or {}
    websocket = status.get("websocket") or {}
    stale_rows = [
        row.get("strike")
        for row in snapshot.get("rows", [])
        if row.get("is_stale") or row.get("call_stale") or row.get("put_stale")
    ]
    penalty = 0
    freshness = "Fresh"
    if stale_rows:
        freshness = "Stale"
        penalty += 14
    if websocket.get("enabled") and not websocket.get("connected"):
        freshness = "Stale" if freshness == "Fresh" else freshness
        penalty += 10
    if not snapshot.get("rows"):
        freshness = "Unavailable"
        penalty += 30
    if previous is None:
        penalty += 8
    return {
        "status": freshness,
        "penalty": penalty,
        "stale_strikes": stale_rows[:12],
        "websocket_connected": bool(websocket.get("connected")),
        "websocket_state": websocket.get("state") or ("disabled" if not websocket.get("enabled") else "unknown"),
        "last_tick_received_at": websocket.get("last_tick_received_at"),
        "last_successful_snapshot_at": status.get("last_snapshot_at") or snapshot.get("timestamp"),
        "has_previous_snapshot": previous is not None,
    }


def overall_bias(live, trend, snapshot, previous_snapshot, pcr_data, quality, weights=None):
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
            explanations.append(f"NIFTY spot is up {spot_change:.2f} from the previous snapshot.")
        elif spot_change < 0:
            bearish += weights["spot_momentum"]
            explanations.append(f"NIFTY spot is down {abs(spot_change):.2f} from the previous snapshot.")
    spot_vwap = safe_num(snapshot.get("spot_vwap"))
    if spot and spot_vwap:
        if spot > spot_vwap:
            bullish += weights["vwap_weight"]
            explanations.append("Spot is trading above VWAP.")
        elif spot < spot_vwap:
            bearish += weights["vwap_weight"]
            explanations.append("Spot is trading below VWAP.")
    direction, confidence = normalized_bias(
        bullish,
        bearish,
        safe_num(live.get("observations")) + len([item for item in trend.get("intervals", []) if item.get("observations")]),
        stale_penalty=quality.get("penalty", 0),
        min_total=3.0,
    )
    conflict = False
    if live["direction"] in ACTIVE_DIRECTIONS and trend["direction"] in ACTIVE_DIRECTIONS and live["direction"] != trend["direction"]:
        direction = "MIXED"
        confidence = max(18, confidence - weights["conflict_penalty"])
        conflict = True
        explanations.append(f"Live bias ({live['direction']}) conflicts with 15-minute trend ({trend['direction']}).")
    if quality.get("status") != "Fresh":
        confidence = max(0, confidence - quality.get("penalty", 0))
        explanations.append(f"Data quality is {quality.get('status').lower()}; confidence is penalized.")
    return {
        "direction": direction,
        "confidence": int(round(confidence)),
        "bullish_score": round2(bullish),
        "bearish_score": round2(bearish),
        "has_conflict": conflict,
        "explanations": explanations,
    }


def market_momentum(live, trend, snapshot, previous):
    spot = safe_num(snapshot.get("spot"))
    prev_spot = safe_num((previous or {}).get("spot"))
    if live.get("direction") == "INSUFFICIENT DATA":
        return "Building"
    if live.get("direction") in ACTIVE_DIRECTIONS and live.get("direction") == trend.get("direction"):
        return "Confirming"
    if live.get("direction") in ACTIVE_DIRECTIONS and trend.get("direction") in ACTIVE_DIRECTIONS and live.get("direction") != trend.get("direction"):
        return "Conflicting"
    if spot and prev_spot and abs(spot - prev_spot) > 0:
        return "Spot Up" if spot > prev_spot else "Spot Down"
    return "Sideways"


def observations(live, trend, overall, levels, events):
    items = []
    if live.get("direction") in ACTIVE_DIRECTIONS:
        items.append(live.get("what_changed"))
    if trend.get("direction") in ACTIVE_DIRECTIONS:
        items.append(f"15-minute trend is {trend['direction'].lower()} and momentum is {str(trend.get('momentum')).lower()}.")
    if overall.get("has_conflict"):
        items.append("Latest 3-minute movement contradicts the 15-minute trend; confirmation is pending.")
    if levels.get("support"):
        items.append(f"Immediate support is near {levels['support']}.")
    if levels.get("resistance"):
        items.append(f"Immediate resistance is near {levels['resistance']}.")
    items.extend(events)
    unique = []
    for item in items:
        if item and item not in unique:
            unique.append(item)
    return unique[:5] or ["Signals are still building; wait for aligned OI and premium confirmation."]


def analyze_options_market(current_snapshot, history=None, config=None, status=None, day_history=None):
    weights = merge_weights(config)
    rows = current_snapshot.get("rows") or []
    timestamp = current_snapshot.get("timestamp") or iso_now()
    history = normalize_history(history or [], current_snapshot)
    day_base = normalize_history(day_history if day_history is not None else history, current_snapshot)
    previous = history[-1] if history else None
    if not rows:
        return {
            "timestamp": timestamp,
            "direction": "INSUFFICIENT DATA",
            "confidence": 0,
            "error": "No option-chain rows available.",
            "live_bias": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "trend_bias": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "day_trend": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "overall_bias": {"direction": "INSUFFICIENT DATA", "confidence": 0},
            "strikes": [],
        }

    snapshot = deepcopy(current_snapshot)
    atm = snapshot.get("atm") or nearest_atm(snapshot.get("spot"), rows)
    snapshot["atm"] = atm
    previous_levels = (previous or {}).get("levels") or {}
    levels = support_resistance(rows, atm, previous_levels)
    snapshot["levels"] = levels
    pcr = compute_pcr(rows)
    max_pain = compute_max_pain(rows)
    quality = data_quality(snapshot, status, previous)
    interval = build_interval_analysis(snapshot, previous, weights)
    live = interval_summary(interval, snapshot, previous)
    live["target_strikes"] = interval.get("target_strikes")
    live["observations"] = interval.get("observations")
    live["bullish_score"] = interval.get("bullish_score")
    live["bearish_score"] = interval.get("bearish_score")
    trend_window = (history + [snapshot])[-5:]
    trend = aggregate_trend(trend_window, weights)
    day_snapshots = day_base + [snapshot]
    day_trend = aggregate_day_trend(day_snapshots, weights)
    change_windows = build_change_windows(snapshot, history, day_snapshots, weights)
    live["change"] = change_windows.get("3m", {}).get("change", {})
    trend["change"] = change_windows.get("15m", {}).get("change", {})
    day_trend["change"] = change_windows.get("session", {}).get("change", {})
    if live["direction"] in ACTIVE_DIRECTIONS and trend["direction"] in ACTIVE_DIRECTIONS:
        trend["agreement_with_live"] = "Agrees" if live["direction"] == trend["direction"] else "Conflicts"
    else:
        trend["agreement_with_live"] = "Pending"
    events = detect_market_events(snapshot, previous, levels, previous_levels)
    overall = overall_bias(live, trend, snapshot, previous, pcr, quality, weights)
    momentum = market_momentum(live, trend, snapshot, previous)
    explanation = overall["explanations"][:]
    if not explanation:
        explanation.append("Signals are balanced across ATM +/-2 strikes.")
    if levels.get("support"):
        explanation.append(f"Immediate support is {levels['support']}.")
    if levels.get("resistance"):
        explanation.append(f"Immediate resistance is {levels['resistance']}.")
    conflicts = []
    if overall.get("has_conflict"):
        conflicts.append(f"Live bias is {live['direction']} while 15-minute trend is {trend['direction']}.")
    if quality["status"] != "Fresh":
        conflicts.append(f"Data freshness is {quality['status']}.")
    return {
        "timestamp": timestamp,
        "instrument": snapshot.get("instrument", "NIFTY"),
        "expiry": snapshot.get("expiry"),
        "spot": snapshot.get("spot"),
        "spot_change": round2(safe_num(snapshot.get("spot")) - safe_num((previous or {}).get("spot"))) if previous else 0,
        "atm": int(safe_num(atm)) if atm else None,
        "direction": overall["direction"] if overall["direction"] in DIRECTION_VALUES else "MIXED",
        "confidence": overall["confidence"],
        "market_momentum": momentum,
        "live_bias": live,
        "trend_bias": trend,
        "day_trend": day_trend,
        "change_windows": change_windows,
        "overall_bias": overall,
        "bullish_score": overall["bullish_score"],
        "bearish_score": overall["bearish_score"],
        "pcr": pcr.get("pcr"),
        "total_call_oi": pcr.get("total_call_oi"),
        "total_put_oi": pcr.get("total_put_oi"),
        "max_pain": max_pain,
        "support_resistance": levels,
        "atm_iv": snapshot.get("atm_iv"),
        "iv_percentile": snapshot.get("iv_percentile"),
        "iv_note": snapshot.get("iv_note") or "IV is unavailable unless supplied by the data source or a separate IV model.",
        "vwap": snapshot.get("spot_vwap"),
        "strikes": interval["rows"],
        "events": events,
        "conflicts": conflicts,
        "explanations": explanation[:6],
        "observations": observations(live, trend, overall, levels, events),
        "data_quality": {
            **quality,
            "snapshot_count": len(history) + 1,
            "focus_strikes": interval.get("target_strikes"),
        },
    }
