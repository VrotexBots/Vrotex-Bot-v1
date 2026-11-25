"""
Vrotex Bot V1 — Technical Analysis Counter-Trend
================================================
Standalone analysis/evidence module. No broker orders or position management.

Layers:
  1. H1 Counter-Trend -> M5 external CHoCH/POI -> existing M1 entry evidence.
  2. M5 Counter-Trend -> existing M1 entry evidence.

The module deliberately does not import or modify Pro-Trend. It does not
implement or replace M1 entry models. Live facts (live price, inducement sweep,
POI tap, expansion/news flags, and existing entry-model evidence) must be
provided by the caller when they cannot be established from completed candles.

Candle input: chronological mappings with open/high/low/close. Supply only
completed candles. All price comparisons use raw instrument prices; no pip,
tick, spread, or tolerance is invented.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import math

VERSION = "1.1.0"
STRATEGY_NAME = "Technical Analysis Counter-Trend"
ACCEPTED_ENTRY_MODELS = {
    "CHOCH_FVG", "SWEEP_ENGULFING", "BREAKER",
    "MSS_SWEEP_DISPLACEMENT", "FLIP_S2D_D2S",
}


def _finite(v: Any) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _number(v: Any) -> Optional[float]:
    return float(v) if _finite(v) else None


def normalize_candles(rows: Optional[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TypeError("Candles must be a chronological sequence of OHLC mappings")
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"Candle {i} must be an OHLC mapping")
        vals = {k: _number(row.get(k)) for k in ("open", "high", "low", "close")}
        if any(v is None for v in vals.values()):
            raise ValueError(f"Candle {i} has missing or invalid OHLC values")
        o, h, l, c = vals["open"], vals["high"], vals["low"], vals["close"]
        if h < max(o, c, l) or l > min(o, c, h):
            raise ValueError(f"Invalid OHLC relationships at candle {i}")
        out.append({
            "index": i, **vals,
            "time": row.get("time", row.get("timestamp")),
            "volume": _number(row.get("volume")),
        })
    return out


def _body(c: Mapping[str, Any]) -> int:
    return 1 if c["close"] > c["open"] else (-1 if c["close"] < c["open"] else 0)


def _pivots(candles: Sequence[Mapping[str, Any]], window: int = 2):
    """Strict confirmed pivots; right-side candles confirm the pivot."""
    highs, lows = [], []
    for i in range(window, len(candles) - window):
        c = candles[i]
        left, right = candles[i-window:i], candles[i+1:i+window+1]
        if all(c["high"] > x["high"] for x in left + right):
            highs.append({"index": i, "price": c["high"], "time": c.get("time")})
        if all(c["low"] < x["low"] for x in left + right):
            lows.append({"index": i, "price": c["low"], "time": c.get("time")})
    return highs, lows


def _last_before(items, idx):
    found = [dict(x) for x in items if x["index"] < idx]
    return found[-1] if found else None


def _structure(candles, window):
    highs, lows = _pivots(candles, window)
    events = []
    for i, c in enumerate(candles):
        ph = [x for x in highs if x["index"] < i and c["close"] > x["price"]]
        pl = [x for x in lows if x["index"] < i and c["close"] < x["price"]]
        if ph:
            broken = max(ph, key=lambda x: (x["price"], x["index"]))
            anchor = _last_before(lows, i)
            if anchor:
                events.append({"direction": "BULLISH", "bos_index": i,
                               "broken_level": broken["price"], "broken_swing": broken,
                               "strong": anchor})
        if pl:
            broken = min(pl, key=lambda x: (x["price"], -x["index"]))
            anchor = _last_before(highs, i)
            if anchor:
                events.append({"direction": "BEARISH", "bos_index": i,
                               "broken_level": broken["price"], "broken_swing": broken,
                               "strong": anchor})
    if not events:
        return {"highs": highs, "lows": lows, "external": None}
    # Latest confirmed body-close structure break defines the active leg.
    event = max(events, key=lambda x: x["bos_index"])
    start = event["bos_index"]
    if event["direction"] == "BULLISH":
        later = [x for x in highs if x["index"] >= start]
        weak = max(later, key=lambda x: (x["price"], x["index"])) if later else {
            "index": max(range(start, len(candles)), key=lambda j: candles[j]["high"]),
            "price": max(candles[j]["high"] for j in range(start, len(candles)))}
        if event["strong"]["price"] >= weak["price"]:
            return {"highs": highs, "lows": lows, "external": None}
    else:
        later = [x for x in lows if x["index"] >= start]
        weak = min(later, key=lambda x: (x["price"], -x["index"])) if later else {
            "index": min(range(start, len(candles)), key=lambda j: candles[j]["low"]),
            "price": min(candles[j]["low"] for j in range(start, len(candles)))}
        if event["strong"]["price"] <= weak["price"]:
            return {"highs": highs, "lows": lows, "external": None}
    event["weak"] = dict(weak)
    event["range_low"] = min(event["strong"]["price"], weak["price"])
    event["range_high"] = max(event["strong"]["price"], weak["price"])
    event["equilibrium"] = (event["range_low"] + event["range_high"]) / 2
    event["range_start_index"] = event["strong"]["index"]
    event["weak_index"] = weak["index"]
    return {"highs": highs, "lows": lows, "external": event}


def _location(price, low, high):
    if high <= low:
        return {"valid": False, "percent": None}
    pct = (price-low)/(high-low)*100
    return {"valid": True, "percent": pct, "equilibrium": (low+high)/2,
            "premium": pct > 50, "discount": pct < 50,
            "deep_premium": 70 <= pct <= 100,
            "deep_discount": 0 <= pct <= 30}


def _sweep(candles, levels, side, start=0, tolerance=0.0):
    """Sweep a level: pierce it and close back through it on same completed bar."""
    unique = []
    for item in levels:
        price = _number(item.get("price"))
        if price is not None and not any(abs(price-x) <= tolerance for x in unique):
            unique.append(price)
    for c in reversed(candles):
        if c["index"] < start:
            break
        for level in unique:
            if side == "SHORT" and c["high"] > level and c["close"] < level:
                return {"index": c["index"], "level": level, "wick": c["high"],
                        "close": c["close"], "direction": side}
            if side == "LONG" and c["low"] < level and c["close"] > level:
                return {"index": c["index"], "level": level, "wick": c["low"],
                        "close": c["close"], "direction": side}
    return None


def _internal_swing(highs, lows, trend, start, weak):
    if trend == "BULLISH":
        candidates = [x for x in lows if start < x["index"] < weak]
        if not candidates:
            return None
        chosen = candidates[-1]
        prev = [x for x in lows if start <= x["index"] < chosen["index"]]
        if prev and chosen["price"] <= prev[-1]["price"]:
            return None
    else:
        candidates = [x for x in highs if start < x["index"] < weak]
        if not candidates:
            return None
        chosen = candidates[-1]
        prev = [x for x in highs if start <= x["index"] < chosen["index"]]
        if prev and chosen["price"] >= prev[-1]["price"]:
            return None
    return dict(chosen)


def _close_break(candles, level, side, after=-1):
    for c in reversed(candles):
        if c["index"] <= after:
            break
        if (side == "BELOW" and c["close"] < level) or (side == "ABOVE" and c["close"] > level):
            return {"index": c["index"], "close": c["close"], "level": level}
    return None


def _fvg(candles):
    out = []
    for i in range(2, len(candles)):
        a, c = candles[i-2], candles[i]
        if a["high"] < c["low"]:
            out.append({"type": "FVG", "direction": "BULLISH", "low": a["high"],
                        "high": c["low"], "formation_index": i})
        if a["low"] > c["high"]:
            out.append({"type": "FVG", "direction": "BEARISH", "low": c["high"],
                        "high": a["low"], "formation_index": i})
    return out


def _order_blocks(candles):
    out = []
    for i in range(1, len(candles)):
        prev, cur = candles[i-1], candles[i]
        if _body(cur) == 1 and _body(prev) == -1:
            out.append({"type": "OB", "direction": "BULLISH", "low": prev["low"],
                        "high": prev["high"], "formation_index": i, "source_index": i-1})
        elif _body(cur) == -1 and _body(prev) == 1:
            out.append({"type": "OB", "direction": "BEARISH", "low": prev["low"],
                        "high": prev["high"], "formation_index": i, "source_index": i-1})
    return out


def _poi_candidates(candles, side, low, high, equilibrium, start):
    wanted = "BULLISH" if side == "LONG" else "BEARISH"
    zones = _fvg(candles) + _order_blocks(candles)
    result = []
    for z in zones:
        i = z["formation_index"]
        if z["direction"] != wanted or i < start:
            continue
        # Mitigation means a later candle trades into any part of the zone.
        if any(c["low"] <= z["high"] and c["high"] >= z["low"] for c in candles[i+1:]):
            continue
        if z["low"] < low or z["high"] > high:
            continue
        mid = (z["low"]+z["high"])/2
        if side == "SHORT" and mid <= equilibrium:
            continue
        if side == "LONG" and mid >= equilibrium:
            continue
        result.append({**z, "midpoint": mid, "mitigated": False})
    return sorted(result, key=lambda z: z["formation_index"], reverse=True)


def _displacement(candles, side, start):
    wanted = 1 if side == "LONG" else -1
    fvgs = [z for z in _fvg(candles) if z["formation_index"] >= start and
            z["direction"] == ("BULLISH" if side == "LONG" else "BEARISH")]
    directional = [c for c in candles if c["index"] >= start and _body(c) == wanted]
    return {"directional_body_present": bool(directional), "fvg_present": bool(fvgs),
            "fvg": fvgs[-1] if fvgs else None,
            "detected": bool(directional and fvgs),
            "note": "Uses directional body plus same-direction FVG; no arbitrary size threshold."}


def _empty_layer(name):
    return {"layer": name, "direction": None, "status": "NOT_READY",
            "trade_setup_ready": False, "checks": {}, "structure": {}, "poi": {},
            "entry_model": None, "entry_evidence": None, "risk_targets": {}, "blockers": []}


def _validate_entry(evidence, direction):
    if not isinstance(evidence, Mapping):
        return False, None
    model = str(evidence.get("model", "")).upper()
    d = str(evidence.get("direction", "")).upper()
    valid = (model in ACCEPTED_ENTRY_MODELS and evidence.get("confirmed") is True
             and d == direction and _finite(evidence.get("entry_price"))
             and _finite(evidence.get("stop_loss")))
    result = dict(evidence)
    result.update({"model": model, "direction": d,
                   "accepted_model": model in ACCEPTED_ENTRY_MODELS,
                   "direction_matches": d == direction,
                   "confirmed": evidence.get("confirmed") is True,
                   "entry_and_sl_supplied": _finite(evidence.get("entry_price")) and
                                            _finite(evidence.get("stop_loss"))})
    return bool(valid), result


def _targets(direction, entry, target_poi, equilibrium, inducement):
    result = {"entry_price": _number(entry.get("entry_price")) if entry else None,
              "stop_loss": _number(entry.get("stop_loss")) if entry else None,
              "tp1_equilibrium_50": _number(equilibrium),
              "tp1_inducement": _number(inducement),
              "tp1_action": "At TP1 close 50% and move stop loss to breakeven",
              "tp2_pro_trend_poi": None,
              "tp2_action": "Close 100% of the remaining position at TP2"}
    if isinstance(target_poi, Mapping):
        lo, hi = _number(target_poi.get("low")), _number(target_poi.get("high"))
        if lo is not None and hi is not None and hi >= lo:
            result["tp2_pro_trend_poi"] = {
                "zone_low": lo, "zone_high": hi,
                "reference_exit": hi if direction == "SHORT" else lo,
                "buffer": None,
                "buffer_note": "Exact beyond-zone buffer requires instrument point/tick size."}
    return result


class TechnicalAnalysisCounterTrend:
    def __init__(self, swing_window: int = 2, equal_level_tolerance: float = 0.0):
        if not isinstance(swing_window, int) or swing_window < 1:
            raise ValueError("swing_window must be an integer >= 1")
        if not _finite(equal_level_tolerance) or float(equal_level_tolerance) < 0:
            raise ValueError("equal_level_tolerance must be a non-negative number")
        self.swing_window = swing_window
        self.equal_level_tolerance = float(equal_level_tolerance)

    def _prepare(self, rows):
        candles = normalize_candles(rows)
        s = _structure(candles, self.swing_window)
        return candles, s["highs"], s["lows"], s["external"]

    def analyze_h1_to_m5(self, h1_candles, m5_candles, *,
                         h1_live_price=None, m5_live_price=None,
                         h1_explosive_momentum=None, h1_news_driven_expansion=None,
                         h1_session_open_expansion=None, m5_displacement_evidence=None,
                         m5_inducement_swept=None, m5_poi_live_tap=None,
                         entry_model_evidence=None, m5_pro_trend_target_poi=None):
        out = _empty_layer("H1_COUNTER_TREND_TO_M5")
        hc, hh, hl, he = self._prepare(h1_candles)
        mc, mh, ml, me = self._prepare(m5_candles)
        if not he or len(hc) < 5 or len(mc) < 5:
            out["blockers"].append("Insufficient confirmed H1/M5 structure or no active H1 external BOS.")
            out["checks"]["h1_external_range_confirmed"] = False
            return out
        trend = he["direction"]
        side = "SHORT" if trend == "BULLISH" else "LONG"
        out["direction"] = side
        price = _number(h1_live_price)
        if price is None:
            # Last completed candle close is a location proxy, not a live quote.
            price = hc[-1]["close"]
            price_source = "last_completed_h1_close"
        else:
            price_source = "caller_live_price"
        loc = _location(price, he["range_low"], he["range_high"])
        extreme = loc.get("deep_premium" if side == "SHORT" else "deep_discount", False)
        internal = _internal_swing(hh, hl, trend, he["range_start_index"], he["weak_index"])
        internal_break = (_close_break(hc, internal["price"],
                          "BELOW" if side == "SHORT" else "ABOVE", he["weak_index"])
                          if internal else None)
        sweep_levels = [{"price": he["weak"]["price"], "kind": "weak_extreme"}]
        # Equal highs/lows are clustered using caller-provided price tolerance.
        same_side = hh if side == "SHORT" else hl
        for pivot in same_side:
            if pivot["index"] < he["weak_index"] and abs(pivot["price"]-he["weak"]["price"]) <= self.equal_level_tolerance:
                sweep_levels.append({"price": pivot["price"], "kind": "equal_extreme"})
        sweep = _sweep(hc, sweep_levels, side, he["weak_index"], self.equal_level_tolerance)
        exhaustion = bool(sweep or internal_break)
        continuation = _close_break(hc, he["weak"]["price"],
                                     "ABOVE" if trend == "BULLISH" else "BELOW",
                                     he["weak_index"])
        explosive = any(x is True for x in (h1_explosive_momentum,
                          h1_news_driven_expansion, h1_session_open_expansion))
        out["structure"]["h1"] = {"trend": trend, "strong": he["strong"], "weak": he["weak"],
            "range_low": he["range_low"], "range_high": he["range_high"],
            "equilibrium_50": he["equilibrium"], "location": loc, "location_source": price_source,
            "internal_exhaustion_swing": internal, "exhaustion_sweep": sweep,
            "internal_choch": internal_break, "continuation_invalidation": continuation}
        out["checks"].update({"h1_external_bos_confirmed": True, "h1_extreme_zone": extreme,
            "h1_signal_a_sweep_or_equal_extreme": bool(sweep),
            "h1_signal_b_internal_choch": bool(internal_break),
            "h1_exhaustion_confirmed": exhaustion, "h1_no_continuation_invalidation": not continuation,
            "h1_not_explosive_news_or_session_expansion": not explosive})
        if not extreme: out["blockers"].append("H1 price is not in the required deep 70%-100% Premium / 0%-30% Discount zone.")
        if not exhaustion: out["blockers"].append("No completed H1 Weak Extreme sweep or internal CHoCH.")
        if continuation: out["blockers"].append("A later H1 body close beyond the active Weak Extreme invalidated the setup.")
        if explosive: out["blockers"].append("Explosive/news/session expansion blocks Counter-Trend.")

        expected = "BEARISH" if side == "SHORT" else "BULLISH"
        m5_external_ok = bool(me and me["direction"] == expected)
        out["structure"]["m5"] = {"external": me}
        out["checks"]["m5_external_choch_against_h1"] = m5_external_ok
        if not m5_external_ok:
            out["blockers"].append("M5 external structure has not confirmed CHoCH against H1.")
            return out
        # The external event itself is a full body-close break of a confirmed pivot.
        displacement = _displacement(mc, side, me["bos_index"])
        displacement_ok = m5_displacement_evidence is True or displacement["detected"]
        choch_ok = displacement_ok
        out["structure"]["m5"]["displacement"] = displacement
        out["checks"]["m5_body_close_beyond_external_line"] = True
        out["checks"]["m5_displacement"] = displacement_ok

        # Lock range from the relevant pre-break extreme to the actual post-break
        # impulse extreme. A pullback/stall must exist after the impulse extreme.
        if side == "SHORT":
            pre = [c for c in mc[:me["bos_index"]+1] if c["high"] >= he["weak"]["price"]]
            strong = {"index": pre[-1]["index"], "price": pre[-1]["high"]} if pre else {
                "index": he["weak_index"], "price": he["weak"]["price"]}
            segment = mc[me["bos_index"]:]
            weak = {"index": min(segment, key=lambda c:c["low"])["index"],
                    "price": min(c["low"] for c in segment)}
            post_extreme = [c for c in segment if c["index"] > weak["index"]]
            pullback_seen = any(c["high"] > weak["price"] for c in post_extreme)
        else:
            pre = [c for c in mc[:me["bos_index"]+1] if c["low"] <= he["weak"]["price"]]
            strong = {"index": pre[-1]["index"], "price": pre[-1]["low"]} if pre else {
                "index": he["weak_index"], "price": he["weak"]["price"]}
            segment = mc[me["bos_index"]:]
            weak = {"index": max(segment, key=lambda c:c["high"])["index"],
                    "price": max(c["high"] for c in segment)}
            post_extreme = [c for c in segment if c["index"] > weak["index"]]
            pullback_seen = any(c["low"] < weak["price"] for c in post_extreme)
        lo, hi = min(strong["price"], weak["price"]), max(strong["price"], weak["price"])
        eq = (lo+hi)/2
        range_valid = hi > lo and pullback_seen
        pois = _poi_candidates(mc, side, lo, hi, eq, me["bos_index"])
        poi = pois[0] if pois else None
        if side == "SHORT":
            idms = [p for p in mh if weak["index"] < p["index"] < len(mc)-self.swing_window]
            idm = idms[0] if idms else None
            idm_front = bool(idm and poi and idm["price"] > poi["high"])
        else:
            idms = [p for p in ml if weak["index"] < p["index"] < len(mc)-self.swing_window]
            idm = idms[0] if idms else None
            idm_front = bool(idm and poi and idm["price"] < poi["low"])
        tap = m5_poi_live_tap is True
        if m5_poi_live_tap is None and poi and _number(m5_live_price) is not None:
            tap = poi["low"] <= float(m5_live_price) <= poi["high"]
        swept_idm = m5_inducement_swept is True
        out["structure"]["m5"]["counter_trend_range"] = {"strong": strong, "weak": weak,
            "range_low": lo, "range_high": hi, "equilibrium_50": eq,
            "pullback_after_impulse_extreme": pullback_seen, "locked": choch_ok and range_valid}
        out["poi"] = {"candidates": pois, "selected": poi, "inducement": idm,
            "inducement_in_front_of_poi": idm_front, "inducement_swept": swept_idm,
            "live_poi_tap": tap, "alert_at_poi_edge": poi}
        out["checks"].update({"m5_range_locked": choch_ok and range_valid,
            "m5_poi_selected_unmitigated_correct_location": poi is not None,
            "m5_clear_inducement_in_front": idm_front,
            "m5_inducement_swept": swept_idm, "m5_physical_poi_tap": tap})
        if not choch_ok: out["blockers"].append("M5 external CHoCH displacement is not confirmed.")
        if not range_valid: out["blockers"].append("M5 impulse range lacks a confirmed post-extreme pullback/stall.")
        if not poi: out["blockers"].append("No unmitigated M5 OB/FVG POI in the required range half.")
        if not idm_front: out["blockers"].append("No qualifying inducement ahead of the selected POI.")
        if not swept_idm: out["blockers"].append("M5 inducement sweep has not been confirmed.")
        if not tap: out["blockers"].append("Live price has not physically tapped the selected M5 POI.")
        entry_ok, entry = _validate_entry(entry_model_evidence, side)
        out["entry_model"], out["entry_evidence"] = (entry.get("model") if entry else None), entry
        out["checks"]["existing_m1_entry_model_confirmed"] = entry_ok
        if not entry_ok: out["blockers"].append("Existing M1 entry-model engine has not supplied a confirmed matching entry.")
        out["risk_targets"] = _targets(side, entry, m5_pro_trend_target_poi, eq,
                                      idm.get("price") if idm else None)
        gates = all((extreme, exhaustion, not continuation, not explosive, m5_external_ok,
                     choch_ok, range_valid, poi is not None, idm_front, swept_idm, tap, entry_ok))
        out["trade_setup_ready"] = bool(gates)
        out["status"] = "SETUP_READY_FOR_EXECUTION_MODULE" if gates else "NOT_READY"
        out["checks"]["all_required_gates_pass"] = bool(gates)
        return out

    def analyze_m5_to_m1(self, m5_candles, m1_candles, *,
                         m5_live_price=None, m5_h1_context_explosive=None,
                         m5_news_driven_expansion=None, m5_session_open_expansion=None,
                         entry_model_evidence=None, m5_pro_trend_target_poi=None,
                         m5_inducement_price=None, m5_inducement_swept=None):
        out = _empty_layer("M5_COUNTER_TREND_TO_M1")
        c5, h5, l5, ext = self._prepare(m5_candles)
        c1, h1, l1, _ = self._prepare(m1_candles)
        if not ext or len(c5) < 5 or len(c1) < 5:
            out["blockers"].append("Insufficient confirmed M5/M1 structure or no active M5 external BOS.")
            out["checks"]["m5_external_range_confirmed"] = False
            return out
        trend = ext["direction"]
        side = "SHORT" if trend == "BULLISH" else "LONG"
        out["direction"] = side
        price = _number(m5_live_price)
        price_source = "caller_live_price"
        if price is None:
            price, price_source = c5[-1]["close"], "last_completed_m5_close"
        loc = _location(price, ext["range_low"], ext["range_high"])
        extreme = loc.get("deep_premium" if side == "SHORT" else "deep_discount", False)
        internal = _internal_swing(h5, l5, trend, ext["range_start_index"], ext["weak_index"])
        internal_break = (_close_break(c5, internal["price"],
                          "BELOW" if side == "SHORT" else "ABOVE", ext["weak_index"])
                          if internal else None)
        pivots = h5 if side == "SHORT" else l5
        levels = [{"price": ext["weak"]["price"], "kind": "weak_extreme"}]
        for p in pivots:
            if p["index"] < ext["weak_index"] and abs(p["price"]-ext["weak"]["price"]) <= self.equal_level_tolerance:
                levels.append({"price": p["price"], "kind": "equal_extreme"})
        sweep = _sweep(c5, levels, side, ext["weak_index"], self.equal_level_tolerance)
        exhaustion = bool(sweep or internal_break)
        continuation = _close_break(c5, ext["weak"]["price"],
                                     "ABOVE" if trend == "BULLISH" else "BELOW",
                                     ext["weak_index"])
        explosive = any(x is True for x in (m5_h1_context_explosive,
                          m5_news_driven_expansion, m5_session_open_expansion))
        # M1 external CHoCH: break of the M1 swing that led into the M5 extreme.
        m1_pre = [p for p in (l1 if side == "SHORT" else h1)
                  if p["index"] < len(c1)-self.swing_window]
        m1_line = None
        if m1_pre:
            # Use the latest confirmed counter-direction pivot preceding the
            # most recent M1 extreme in the same direction as the M5 weak extreme.
            m1_line = m1_pre[-1]
        m1_break = (_close_break(c1, m1_line["price"],
                     "BELOW" if side == "SHORT" else "ABOVE") if m1_line else None)
        displacement = _displacement(c1, side, m1_break["index"] if m1_break else len(c1))
        m1_trigger = bool(m1_break and displacement["detected"])
        entry_ok, entry = _validate_entry(entry_model_evidence, side)
        out["structure"]["m5"] = {"trend": trend, "strong": ext["strong"], "weak": ext["weak"],
            "range_low": ext["range_low"], "range_high": ext["range_high"],
            "equilibrium_50": ext["equilibrium"], "location": loc, "location_source": price_source,
            "internal_exhaustion_swing": internal, "exhaustion_sweep": sweep,
            "internal_choch": internal_break, "continuation_invalidation": continuation}
        out["structure"]["m1"] = {"external_choch_line": m1_line, "external_choch": m1_break,
                                  "displacement": displacement, "trigger_confirmed": m1_trigger}
        out["checks"].update({"m5_external_bos_confirmed": True, "m5_extreme_zone": extreme,
            "m5_signal_a_sweep_or_equal_extreme": bool(sweep),
            "m5_signal_b_internal_choch": bool(internal_break), "m5_exhaustion_confirmed": exhaustion,
            "m5_no_continuation_invalidation": not continuation,
            "h1_not_explosive_news_or_session_expansion": not explosive,
            "m1_external_choch_body_close": bool(m1_break),
            "m1_displacement": displacement["detected"], "m1_entry_trigger_confirmed": m1_trigger,
            "existing_m1_entry_model_confirmed": entry_ok})
        if not extreme: out["blockers"].append("M5 price is not in the required deep extreme zone.")
        if not exhaustion: out["blockers"].append("No completed M5 Weak Extreme sweep or internal CHoCH.")
        if continuation: out["blockers"].append("M5 continuation body close invalidates Counter-Trend.")
        if explosive: out["blockers"].append("Explosive H1/news/session expansion blocks Counter-Trend.")
        if not m1_break: out["blockers"].append("M1 external CHoCH body close is not confirmed.")
        if not displacement["detected"]: out["blockers"].append("M1 displacement with same-direction FVG is not confirmed.")
        if not entry_ok: out["blockers"].append("Existing M1 entry-model engine has not supplied a confirmed matching entry.")
        inducement = _number(m5_inducement_price)
        swept_idm = m5_inducement_swept is True
        out["poi"] = {"m5_inducement_price": inducement, "m5_inducement_swept": swept_idm,
                      "m5_pro_trend_target_poi": dict(m5_pro_trend_target_poi)
                      if isinstance(m5_pro_trend_target_poi, Mapping) else None}
        out["checks"]["m5_inducement_swept"] = swept_idm
        if not swept_idm: out["blockers"].append("M5 inducement sweep is not confirmed.")
        if inducement is None: out["blockers"].append("M5 inducement price is unavailable for TP1.")
        out["entry_model"], out["entry_evidence"] = (entry.get("model") if entry else None), entry
        out["risk_targets"] = _targets(side, entry, m5_pro_trend_target_poi,
                                      ext["equilibrium"], inducement)
        gates = all((extreme, exhaustion, not continuation, not explosive,
                     m1_trigger, entry_ok, swept_idm, inducement is not None))
        out["trade_setup_ready"] = bool(gates)
        out["status"] = "SETUP_READY_FOR_EXECUTION_MODULE" if gates else "NOT_READY"
        out["checks"]["all_required_gates_pass"] = bool(gates)
        return out

    def analyze(self, *, h1_candles, m5_candles, m1_candles,
                h1_live_price=None, m5_live_price=None,
                h1_explosive_momentum=None, h1_news_driven_expansion=None,
                h1_session_open_expansion=None, m5_displacement_evidence=None,
                m5_inducement_swept=None, m5_poi_live_tap=None,
                m5_h1_context_explosive=None, m5_news_driven_expansion=None,
                m5_session_open_expansion=None, entry_model_evidence=None,
                m5_pro_trend_target_poi=None, m5_inducement_price=None):
        h1 = self.analyze_h1_to_m5(h1_candles, m5_candles,
            h1_live_price=h1_live_price, m5_live_price=m5_live_price,
            h1_explosive_momentum=h1_explosive_momentum,
            h1_news_driven_expansion=h1_news_driven_expansion,
            h1_session_open_expansion=h1_session_open_expansion,
            m5_displacement_evidence=m5_displacement_evidence,
            m5_inducement_swept=m5_inducement_swept,
            m5_poi_live_tap=m5_poi_live_tap,
            entry_model_evidence=entry_model_evidence,
            m5_pro_trend_target_poi=m5_pro_trend_target_poi)
        m5 = self.analyze_m5_to_m1(m5_candles, m1_candles,
            m5_live_price=m5_live_price, m5_h1_context_explosive=m5_h1_context_explosive,
            m5_news_driven_expansion=m5_news_driven_expansion,
            m5_session_open_expansion=m5_session_open_expansion,
            entry_model_evidence=entry_model_evidence,
            m5_pro_trend_target_poi=m5_pro_trend_target_poi,
            m5_inducement_price=m5_inducement_price,
            m5_inducement_swept=m5_inducement_swept)
        ready = h1["trade_setup_ready"] or m5["trade_setup_ready"]
        return {"strategy": STRATEGY_NAME, "version": VERSION, "analysis_only": True,
                "orders_placed": False,
                "status": "SETUP_READY_FOR_EXECUTION_MODULE" if ready else "NO_COUNTER_TREND_SETUP_READY",
                "trade_setup_ready": ready,
                "layers": {"H1_COUNTER_TREND_TO_M5": h1, "M5_COUNTER_TREND_TO_M1": m5},
                "active_ready_layers": [k for k, v in (
                    ("H1_COUNTER_TREND_TO_M5", h1), ("M5_COUNTER_TREND_TO_M1", m5))
                    if v["trade_setup_ready"]],
                "note": "Evidence only. No orders, position changes, or broker authorization."}


technical_analysis_counter_trend = TechnicalAnalysisCounterTrend()


def analyze_counter_trend(**kwargs):
    return technical_analysis_counter_trend.analyze(**kwargs)


def get_strategy_metadata():
    return {"name": STRATEGY_NAME, "version": VERSION,
            "filename": "technical_analysis_counter_trend.py",
            "layers": ["H1_COUNTER_TREND_TO_M5", "M5_COUNTER_TREND_TO_M1"],
            "entry_models": sorted(ACCEPTED_ENTRY_MODELS),
            "analysis_only": True, "places_orders": False}


__all__ = ["TechnicalAnalysisCounterTrend", "technical_analysis_counter_trend",
           "analyze_counter_trend", "get_strategy_metadata", "normalize_candles", "VERSION"]
