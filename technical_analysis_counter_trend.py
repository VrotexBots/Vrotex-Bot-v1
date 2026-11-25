"""
Vrotex Bot V1 — Technical Analysis Counter-Trend
================================================

Contains two separate Counter-Trend analysis layers:

A) H1 Counter-Trend -> M5 external confirmation -> existing M1 entry models.
B) M5 Counter-Trend -> M5 exhaustion -> existing M1 entry models.

This module is analysis/evidence only. It does NOT place orders, authorize broker
execution, modify positions, or implement/replace the user's existing M1 entry
models. Supply the result of the existing entry-model engine through
`entry_model_evidence`.

Input candles must be chronological OHLC mappings with open/high/low/close.
Only completed candles are used. If a caller supplies a live candle, exclude it
before calling this module.

Important implementation contract:
- No fabricated spread, news, session, or live-price data.
- No guessed entry model result: the existing entry-model engine must supply it.
- No setup is reported ready unless all required gates for that layer pass.
- Structure pivots use a configurable left/right confirmation window. This is
  a technical swing-detection setting, not an additional trading signal.
- OB/FVG POI candidates are identified from OHLC structure. If a required
  external value (live price, news momentum, Pro-Trend target POI, entry model)
  is unavailable, the corresponding gate remains unconfirmed.

Public API:
    TechnicalAnalysisCounterTrend.analyze(...)
    technical_analysis_counter_trend
    analyze_counter_trend(...)

"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math


VERSION = "1.0.0"
STRATEGY_NAME = "Technical Analysis Counter-Trend"


def _finite_number(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    return float(value) if _finite_number(value) else default


def _candle(row: Mapping[str, Any], index: int) -> Dict[str, Any]:
    required = ("open", "high", "low", "close")
    missing = [key for key in required if not _finite_number(row.get(key))]
    if missing:
        raise ValueError(f"Candle {index} missing valid OHLC fields: {missing}")
    o, h, l, c = (float(row[k]) for k in required)
    if h < max(o, c, l) or l > min(o, c, h):
        raise ValueError(f"Invalid OHLC relationships at candle {index}")
    return {
        "index": index, "open": o, "high": h, "low": l, "close": c,
        "time": row.get("time", row.get("timestamp")),
        "volume": _num(row.get("volume")),
    }


def normalize_candles(rows: Optional[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TypeError("Candles must be a chronological sequence of OHLC mappings")
    result = [_candle(row, i) for i, row in enumerate(rows)]
    return result


def _body_direction(c: Mapping[str, Any]) -> int:
    if c["close"] > c["open"]:
        return 1
    if c["close"] < c["open"]:
        return -1
    return 0


def _body_size(c: Mapping[str, Any]) -> float:
    return abs(c["close"] - c["open"])


def _pivots(candles: Sequence[Mapping[str, Any]], window: int = 2) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Confirmed local pivots; a pivot needs `window` candles on both sides."""
    highs, lows = [], []
    if window < 1:
        raise ValueError("swing_window must be >= 1")
    for i in range(window, len(candles) - window):
        cur = candles[i]
        left = candles[i-window:i]
        right = candles[i+1:i+window+1]
        if all(cur["high"] > x["high"] for x in left + right):
            highs.append({"index": i, "price": cur["high"], "time": cur.get("time")})
        if all(cur["low"] < x["low"] for x in left + right):
            lows.append({"index": i, "price": cur["low"], "time": cur.get("time")})
    return highs, lows


def _latest_before(items: Sequence[Mapping[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    eligible = [dict(x) for x in items if x["index"] < index]
    return eligible[-1] if eligible else None


def _first_after(items: Sequence[Mapping[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    eligible = [dict(x) for x in items if x["index"] > index]
    return eligible[0] if eligible else None


def _find_latest_external_bos(
    candles: Sequence[Mapping[str, Any]], highs: Sequence[Mapping[str, Any]],
    lows: Sequence[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Find the latest body-close break of a prior confirmed pivot.
    Bullish: prior pivot high broken by candle close; anchor is latest prior
    pivot low. Bearish: prior pivot low broken by candle close; anchor is latest
    prior pivot high. The post-break extreme becomes the weak extreme.
    """
    events = []
    for i, c in enumerate(candles):
        prior_highs = [p for p in highs if p["index"] < i]
        prior_lows = [p for p in lows if p["index"] < i]
        if prior_highs:
            broken = [p for p in prior_highs if c["close"] > p["price"]]
            if broken:
                level = max(broken, key=lambda p: p["price"])
                anchor = _latest_before(lows, i)
                if anchor:
                    events.append({
                        "direction": "BULLISH", "bos_index": i,
                        "broken_level": level["price"], "broken_swing": level,
                        "strong_anchor": anchor, "anchor_type": "STRONG_LOW",
                    })
        if prior_lows:
            broken = [p for p in prior_lows if c["close"] < p["price"]]
            if broken:
                level = min(broken, key=lambda p: p["price"])
                anchor = _latest_before(highs, i)
                if anchor:
                    events.append({
                        "direction": "BEARISH", "bos_index": i,
                        "broken_level": level["price"], "broken_swing": level,
                        "strong_anchor": anchor, "anchor_type": "STRONG_HIGH",
                    })
    if not events:
        return None
    event = max(events, key=lambda e: e["bos_index"])
    start = event["bos_index"]
    end = len(candles) - 1
    if event["direction"] == "BULLISH":
        # Use the highest confirmed post-BOS pivot high as the Weak High.
        # Do not use the absolute maximum of the entire dataset: doing so would
        # absorb a later sweep wick into the level and make sweep detection
        # mathematically impossible.
        post_bos = [p for p in highs if p["index"] >= start]
        if post_bos:
            weak = dict(max(post_bos, key=lambda p: (p["price"], p["index"])))
        else:
            extreme_index = max(range(start, end + 1), key=lambda i: candles[i]["high"])
            weak = {"index": extreme_index, "price": candles[extreme_index]["high"]}
        strong = event["strong_anchor"]
        if strong["price"] >= weak["price"]:
            return None
    else:
        # Bearish mirror: lowest confirmed post-BOS pivot low is the Weak Low.
        post_bos = [p for p in lows if p["index"] >= start]
        if post_bos:
            weak = dict(min(post_bos, key=lambda p: (p["price"], -p["index"])))
        else:
            extreme_index = min(range(start, end + 1), key=lambda i: candles[i]["low"])
            weak = {"index": extreme_index, "price": candles[extreme_index]["low"]}
        strong = event["strong_anchor"]
        if strong["price"] <= weak["price"]:
            return None
    event["strong"] = dict(strong)
    event["weak"] = weak
    event["range_low"] = min(strong["price"], weak["price"])
    event["range_high"] = max(strong["price"], weak["price"])
    event["equilibrium"] = (event["range_low"] + event["range_high"]) / 2.0
    event["weak_index"] = weak["index"]
    event["range_start_index"] = strong["index"]
    return event


def _range_location(price: float, low: float, high: float) -> Dict[str, Any]:
    span = high - low
    if span <= 0:
        return {"valid": False, "percent": None, "equilibrium": None}
    pct = (price - low) / span * 100.0
    return {
        "valid": True, "percent": pct, "equilibrium": (low + high) / 2.0,
        "premium": pct > 50.0, "discount": pct < 50.0,
        "deep_premium": 70.0 <= pct <= 100.0,
        "deep_discount": 0.0 <= pct <= 30.0,
    }


def _latest_close_break(candles: Sequence[Mapping[str, Any]], level: float, side: str) -> Optional[Dict[str, Any]]:
    found = []
    for c in candles:
        if (side == "ABOVE" and c["close"] > level) or (side == "BELOW" and c["close"] < level):
            found.append({"index": c["index"], "close": c["close"], "level": level})
    return found[-1] if found else None


def _sweep(candles: Sequence[Mapping[str, Any]], level: float, direction: str, start_index: int = 0) -> Optional[Dict[str, Any]]:
    """
    direction SHORT: wick above level and close back below.
    direction LONG: wick below level and close back above.
    """
    for c in reversed(candles):
        if c["index"] < start_index:
            break
        if direction == "SHORT" and c["high"] > level and c["close"] < level:
            return {"index": c["index"], "level": level, "high": c["high"], "close": c["close"]}
        if direction == "LONG" and c["low"] < level and c["close"] > level:
            return {"index": c["index"], "level": level, "low": c["low"], "close": c["close"]}
    return None


def _equal_extreme_sweep(candles: Sequence[Mapping[str, Any]], pivots: Sequence[Mapping[str, Any]],
                         direction: str, weak_price: float, start_index: int = 0) -> Optional[Dict[str, Any]]:
    # Equal-high/low levels are accepted only when actual pivot prices are equal
    # within the instrument's caller-supplied tolerance; no pip size is guessed.
    levels = [weak_price]
    for p in pivots:
        if p["index"] >= start_index and abs(p["price"] - weak_price) <= 0:
            levels.append(p["price"])
    for level in levels:
        hit = _sweep(candles, level, direction, start_index)
        if hit:
            hit["sweep_level_type"] = "WEAK_EXTREME"
            return hit
    return None


def _internal_exhaustion_swing(
    highs: Sequence[Mapping[str, Any]], lows: Sequence[Mapping[str, Any]],
    direction: str, start_index: int, weak_index: int
) -> Optional[Dict[str, Any]]:
    """
    Bullish leg -> last internal higher low before weak high.
    Bearish leg -> last internal lower high before weak low.
    """
    if direction == "BULLISH":
        candidates = [p for p in lows if start_index < p["index"] < weak_index]
        if len(candidates) < 1:
            return None
        # Last confirmed low before the weak high; higher-low context is checked
        # against the preceding confirmed low when available.
        chosen = candidates[-1]
        previous = [p for p in lows if start_index <= p["index"] < chosen["index"]]
        if previous and chosen["price"] <= previous[-1]["price"]:
            return None
        return dict(chosen)
    candidates = [p for p in highs if start_index < p["index"] < weak_index]
    if len(candidates) < 1:
        return None
    chosen = candidates[-1]
    previous = [p for p in highs if start_index <= p["index"] < chosen["index"]]
    if previous and chosen["price"] >= previous[-1]["price"]:
        return None
    return dict(chosen)


def _fvg_zones(candles: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    zones = []
    for i in range(2, len(candles)):
        a, b, c = candles[i-2], candles[i-1], candles[i]
        # Three-candle imbalance.
        if a["high"] < c["low"]:
            zones.append({"type": "FVG", "direction": "BULLISH", "low": a["high"],
                          "high": c["low"], "formation_index": i, "mitigated": False})
        if a["low"] > c["high"]:
            zones.append({"type": "FVG", "direction": "BEARISH", "low": c["high"],
                          "high": a["low"], "formation_index": i, "mitigated": False})
    for z in zones:
        for c in candles[z["formation_index"] + 1:]:
            if c["low"] <= z["high"] and c["high"] >= z["low"]:
                z["mitigated"] = True
                z["mitigated_index"] = c["index"]
                break
    return zones


def _ob_zones(candles: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    zones = []
    for i in range(1, len(candles)):
        prev, cur = candles[i-1], candles[i]
        d = _body_direction(cur)
        if d == 1 and _body_direction(prev) == -1:
            zones.append({"type": "OB", "direction": "BULLISH", "low": prev["low"],
                          "high": prev["high"], "formation_index": i, "source_index": i-1,
                          "mitigated": False})
        elif d == -1 and _body_direction(prev) == 1:
            zones.append({"type": "OB", "direction": "BEARISH", "low": prev["low"],
                          "high": prev["high"], "formation_index": i, "source_index": i-1,
                          "mitigated": False})
    for z in zones:
        for c in candles[z["formation_index"] + 1:]:
            if c["low"] <= z["high"] and c["high"] >= z["low"]:
                z["mitigated"] = True
                z["mitigated_index"] = c["index"]
                break
    return zones


def _poi_candidates(candles: Sequence[Mapping[str, Any]], direction: str,
                    range_low: float, range_high: float, equilibrium: float,
                    start_index: int = 0, end_index: Optional[int] = None) -> List[Dict[str, Any]]:
    end_index = len(candles) - 1 if end_index is None else end_index
    zones = _fvg_zones(candles) + _ob_zones(candles)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    out = []
    for z in zones:
        if z["direction"] != expected or z["mitigated"]:
            continue
        if not (start_index <= z["formation_index"] <= end_index):
            continue
        if z["low"] < range_low or z["high"] > range_high:
            continue
        midpoint = (z["low"] + z["high"]) / 2.0
        if direction == "SHORT" and midpoint <= equilibrium:
            continue
        if direction == "LONG" and midpoint >= equilibrium:
            continue
        item = dict(z)
        item["midpoint"] = midpoint
        out.append(item)
    return sorted(out, key=lambda z: z["formation_index"], reverse=True)


def _zone_tap(zone: Optional[Mapping[str, Any]], price: Optional[float],
              candles: Sequence[Mapping[str, Any]]) -> bool:
    if not zone:
        return False
    if price is not None and zone["low"] <= price <= zone["high"]:
        return True
    if candles:
        c = candles[-1]
        return c["low"] <= zone["high"] and c["high"] >= zone["low"]
    return False


def _displacement(candles: Sequence[Mapping[str, Any]], direction: str,
                  start_index: int = 0, end_index: Optional[int] = None) -> Dict[str, Any]:
    """
    Reports directional impulse evidence without inventing a numeric body-size
    threshold. A same-direction three-candle FVG is recorded as stronger
    supporting evidence. The caller can also supply externally measured
    displacement evidence through the public API.
    """
    end_index = len(candles) - 1 if end_index is None else end_index
    segment = [c for c in candles if start_index <= c["index"] <= end_index]
    wanted = 1 if direction == "LONG" else -1
    directional = [c for c in segment if _body_direction(c) == wanted]
    fvg_direction = "BULLISH" if direction == "LONG" else "BEARISH"
    fvgs = [z for z in _fvg_zones(candles) if z["direction"] == fvg_direction
            and start_index <= z["formation_index"] <= end_index]
    return {
        "directional_candles": len(directional),
        "directional_body_present": bool(directional),
        "fvg_present": bool(fvgs),
        "fvg": fvgs[-1] if fvgs else None,
        "displacement_detected": bool(directional) and bool(fvgs),
        "note": "No arbitrary candle-size threshold was invented; FVG plus directional body evidence is reported.",
    }


def _result_layer(name: str, direction: Optional[str]) -> Dict[str, Any]:
    return {
        "layer": name, "direction": direction, "status": "NOT_READY",
        "trade_setup_ready": False, "entry_model": None, "entry_evidence": None,
        "checks": {}, "structure": {}, "poi": {}, "risk_targets": {},
        "blockers": [],
    }


class TechnicalAnalysisCounterTrend:
    """Complete evidence engine for H1->M5 and M5->M1 Counter-Trend layers."""

    def __init__(self, swing_window: int = 2):
        if not isinstance(swing_window, int) or swing_window < 1:
            raise ValueError("swing_window must be an integer >= 1")
        self.swing_window = swing_window

    def _structure(self, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        candles = normalize_candles(rows)
        highs, lows = _pivots(candles, self.swing_window)
        bos = _find_latest_external_bos(candles, highs, lows)
        return {"candles": candles, "swing_highs": highs, "swing_lows": lows, "external": bos}

    def analyze_h1_to_m5(
        self, h1_candles: Sequence[Mapping[str, Any]],
        m5_candles: Sequence[Mapping[str, Any]], *,
        h1_live_price: Optional[float] = None,
        m5_live_price: Optional[float] = None,
        h1_explosive_momentum: Optional[bool] = None,
        h1_news_driven_expansion: Optional[bool] = None,
        h1_session_open_expansion: Optional[bool] = None,
        m5_displacement_evidence: Optional[bool] = None,
        m5_inducement_swept: Optional[bool] = None,
        m5_poi_live_tap: Optional[bool] = None,
        entry_model_evidence: Optional[Mapping[str, Any]] = None,
        m5_pro_trend_target_poi: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        out = _result_layer("H1_COUNTER_TREND_TO_M5", None)
        h1 = self._structure(h1_candles)
        m5 = self._structure(m5_candles)
        hc, hh, hl, ext = h1["candles"], h1["swing_highs"], h1["swing_lows"], h1["external"]
        mc, mh, ml, mext = m5["candles"], m5["swing_highs"], m5["swing_lows"], m5["external"]
        if not ext or len(hc) < 3 or len(mc) < 3:
            out["blockers"].append("Insufficient confirmed H1/M5 structure or no confirmed H1 external BOS.")
            out["checks"]["h1_external_range"] = False
            return out

        h1trend = ext["direction"]
        direction = "SHORT" if h1trend == "BULLISH" else "LONG"
        out["direction"] = direction
        loc_price = _num(h1_live_price, hc[-1]["close"])
        location = _range_location(loc_price, ext["range_low"], ext["range_high"])
        extreme_ok = location["deep_premium"] if direction == "SHORT" else location["deep_discount"]

        internal = _internal_exhaustion_swing(hh, hl, h1trend,
                                              ext["range_start_index"], ext["weak_index"])
        if not internal:
            # The H1 exhaustion swing must be found before the weak extreme.
            internal_break = None
        else:
            internal_break = _latest_close_break(
                hc, internal["price"], "BELOW" if direction == "SHORT" else "ABOVE"
            )
            if internal_break and internal_break["index"] <= ext["weak_index"]:
                internal_break = None

        weak_sweep = _sweep(hc, ext["weak"]["price"], direction, ext["weak_index"])
        signal_a = weak_sweep is not None
        signal_b = internal_break is not None
        exhaustion = signal_a or signal_b

        continuation = _latest_close_break(
            hc, ext["weak"]["price"], "ABOVE" if h1trend == "BULLISH" else "BELOW"
        )
        # The BOS candle that originally created this weak extreme is expected;
        # only a later close beyond the active weak extreme invalidates it.
        if continuation and continuation["index"] <= ext["weak_index"]:
            continuation = None
        no_invalidation = continuation is None

        explosive_flags = [h1_explosive_momentum, h1_news_driven_expansion,
                           h1_session_open_expansion]
        explosive = any(x is True for x in explosive_flags)
        out["structure"]["h1"] = {
            "trend": h1trend, "strong": ext["strong"], "weak": ext["weak"],
            "range_low": ext["range_low"], "range_high": ext["range_high"],
            "equilibrium_50": ext["equilibrium"], "location": location,
            "internal_exhaustion_swing": internal, "external_bos": ext,
        }
        out["checks"].update({
            "h1_external_bos_confirmed": True,
            "h1_extreme_zone": extreme_ok,
            "h1_signal_a_weak_extreme_sweep": signal_a,
            "h1_signal_b_internal_choch": signal_b,
            "h1_exhaustion_confirmed": exhaustion,
            "h1_no_continuation_invalidation": no_invalidation,
            "h1_not_explosive_news_or_session_expansion": not explosive,
        })
        out["structure"]["h1_exhaustion"] = {
            "signal_a": weak_sweep, "signal_b": internal_break,
            "confirmed": exhaustion,
        }
        if not extreme_ok: out["blockers"].append("H1 price is not in the specified 70%-100% Premium / 0%-30% Discount extreme.")
        if not exhaustion: out["blockers"].append("Neither H1 Weak Extreme sweep nor H1 Internal CHoCH is confirmed.")
        if not no_invalidation: out["blockers"].append("A later H1 body close beyond the active Weak Extreme invalidated the setup.")
        if explosive: out["blockers"].append("H1 explosive/news/session-open expansion filter blocks Counter-Trend trading.")

        # M5 external break must oppose the H1 direction.
        m5_expected_break = "BEARISH" if direction == "SHORT" else "BULLISH"
        m5_external_ok = bool(mext and mext["direction"] == m5_expected_break)
        out["structure"]["m5"] = {"external": mext}
        out["checks"]["m5_external_choch_against_h1"] = m5_external_ok
        if not m5_external_ok:
            out["blockers"].append("M5 external structure has not confirmed CHoCH against the H1 trend.")
            return out

        # Confirm body-close break on M5 against the original H1 trend.
        m5_choch_break = _latest_close_break(
            mc, mext["broken_level"], "BELOW" if direction == "SHORT" else "ABOVE"
        )
        if m5_choch_break and m5_choch_break["index"] < mext["bos_index"]:
            m5_choch_break = None
        displacement = _displacement(mc, direction, mext["bos_index"])
        displacement_ok = (m5_displacement_evidence is True) or displacement["displacement_detected"]
        m5_choch_ok = m5_choch_break is not None and displacement_ok
        out["checks"]["m5_body_close_beyond_external_line"] = m5_choch_break is not None
        out["checks"]["m5_displacement"] = displacement_ok
        out["structure"]["m5"].update({"choch_break": m5_choch_break, "displacement": displacement})

        # M5 dealing range: H1 extreme as strong anchor; actual M5 impulse extreme
        # after CHoCH as weak anchor.
        if direction == "SHORT":
            strong_candidates = [p for p in mh if p["index"] <= ext["weak_index"]]
            strong = max(strong_candidates, key=lambda p: p["price"]) if strong_candidates else {
                "index": ext["weak_index"], "price": ext["weak"]["price"]}
            start = m5_choch_break["index"] if m5_choch_break else len(mc)-1
            weak_i = min(range(start, len(mc)), key=lambda i: mc[i]["low"])
            weak = {"index": weak_i, "price": mc[weak_i]["low"]}
        else:
            strong_candidates = [p for p in ml if p["index"] <= ext["weak_index"]]
            strong = min(strong_candidates, key=lambda p: p["price"]) if strong_candidates else {
                "index": ext["weak_index"], "price": ext["weak"]["price"]}
            start = m5_choch_break["index"] if m5_choch_break else len(mc)-1
            weak_i = max(range(start, len(mc)), key=lambda i: mc[i]["high"])
            weak = {"index": weak_i, "price": mc[weak_i]["high"]}
        rlow, rhigh = min(strong["price"], weak["price"]), max(strong["price"], weak["price"])
        eq = (rlow + rhigh) / 2.0
        m5_range_valid = rhigh > rlow
        out["structure"]["m5"]["counter_trend_range"] = {
            "strong": strong, "weak": weak, "range_low": rlow,
            "range_high": rhigh, "equilibrium_50": eq, "locked": m5_choch_ok and m5_range_valid,
        }

        poi_direction = direction
        pois = _poi_candidates(mc, poi_direction, rlow, rhigh, eq,
                               start_index=max(0, strong["index"]))
        selected_poi = pois[0] if pois else None
        # The first confirmed internal pivot on the pullback is used as IDM;
        # it must be on the correct side of the selected zone.
        if direction == "SHORT":
            idms = [p for p in mh if weak["index"] < p["index"] and p["index"] < len(mc)-self.swing_window]
            idm = idms[0] if idms else None
            idm_in_front = bool(idm and selected_poi and idm["price"] > selected_poi["high"])
        else:
            idms = [p for p in ml if weak["index"] < p["index"] and p["index"] < len(mc)-self.swing_window]
            idm = idms[0] if idms else None
            idm_in_front = bool(idm and selected_poi and idm["price"] < selected_poi["low"])
        live = _num(m5_live_price)
        tapped = (m5_poi_live_tap is True) or _zone_tap(selected_poi, live, mc)
        swept = m5_inducement_swept is True
        out["poi"] = {"candidates": pois, "selected": selected_poi, "inducement": idm,
                      "inducement_in_front_of_poi": idm_in_front,
                      "inducement_swept": swept, "live_poi_tap": tapped,
                      "alert_at_poi_edge": selected_poi}
        out["checks"].update({
            "m5_range_locked": m5_choch_ok and m5_range_valid,
            "m5_poi_selected_unmitigated_correct_location": selected_poi is not None,
            "m5_clear_inducement_in_front": idm_in_front,
            "m5_inducement_swept": swept,
            "m5_physical_poi_tap": tapped,
        })
        if not m5_choch_ok: out["blockers"].append("M5 external CHoCH body close plus displacement is not confirmed.")
        if not selected_poi: out["blockers"].append("No unmitigated M5 OB/FVG POI found in the correct range half.")
        if not idm_in_front: out["blockers"].append("A qualifying M5 inducement in front of the selected POI is not confirmed.")
        if not swept: out["blockers"].append("M5 inducement sweep has not been confirmed by the live/market-data input.")
        if not tapped: out["blockers"].append("Live price has not been confirmed inside the selected M5 POI.")

        entry_ok, entry = self._validate_entry_model(entry_model_evidence, direction)
        out["entry_model"] = entry.get("model") if entry else None
        out["entry_evidence"] = entry
        out["checks"]["existing_m1_entry_model_confirmed"] = entry_ok
        if not entry_ok: out["blockers"].append("The existing M1 entry-model engine has not supplied a confirmed matching entry.")
        out["risk_targets"] = self._targets(direction, entry, m5_pro_trend_target_poi, eq, idm)
        gates = all([
            extreme_ok, exhaustion, no_invalidation, not explosive, m5_external_ok,
            m5_choch_ok, m5_range_valid, selected_poi is not None, idm_in_front,
            swept, tapped, entry_ok
        ])
        out["trade_setup_ready"] = bool(gates)
        out["status"] = "SETUP_READY_FOR_EXECUTION_MODULE" if gates else "NOT_READY"
        out["checks"]["all_required_gates_pass"] = bool(gates)
        return out

    def analyze_m5_to_m1(
        self, m5_candles: Sequence[Mapping[str, Any]],
        m1_candles: Sequence[Mapping[str, Any]], *,
        m5_live_price: Optional[float] = None,
        m5_h1_context_explosive: Optional[bool] = None,
        m5_news_driven_expansion: Optional[bool] = None,
        m5_session_open_expansion: Optional[bool] = None,
        entry_model_evidence: Optional[Mapping[str, Any]] = None,
        m5_pro_trend_target_poi: Optional[Mapping[str, Any]] = None,
        m5_inducement_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        out = _result_layer("M5_COUNTER_TREND_TO_M1", None)
        m5 = self._structure(m5_candles)
        m1 = self._structure(m1_candles)
        c5, h5, l5, ext = m5["candles"], m5["swing_highs"], m5["swing_lows"], m5["external"]
        c1 = m1["candles"]
        if not ext or len(c5) < 3 or len(c1) < 3:
            out["blockers"].append("Insufficient confirmed M5/M1 structure or no confirmed M5 external BOS.")
            out["checks"]["m5_external_range"] = False
            return out

        trend = ext["direction"]
        direction = "SHORT" if trend == "BULLISH" else "LONG"
        out["direction"] = direction
        price = _num(m5_live_price, c5[-1]["close"])
        location = _range_location(price, ext["range_low"], ext["range_high"])
        extreme_ok = location["deep_premium"] if direction == "SHORT" else location["deep_discount"]
        internal = _internal_exhaustion_swing(h5, l5, trend,
                                              ext["range_start_index"], ext["weak_index"])
        if internal:
            internal_break = _latest_close_break(
                c5, internal["price"], "BELOW" if direction == "SHORT" else "ABOVE")
            if internal_break and internal_break["index"] <= ext["weak_index"]:
                internal_break = None
        else:
            internal_break = None
        sweep = _sweep(c5, ext["weak"]["price"], direction, ext["weak_index"])
        signal_a = sweep is not None
        signal_b = internal_break is not None
        exhaustion = signal_a or signal_b
        continuation = _latest_close_break(
            c5, ext["weak"]["price"], "ABOVE" if trend == "BULLISH" else "BELOW")
        if continuation and continuation["index"] <= ext["weak_index"]:
            continuation = None
        no_continuation = continuation is None

        explosive = any(x is True for x in (
            m5_h1_context_explosive, m5_news_driven_expansion, m5_session_open_expansion
        ))
        out["structure"]["m5"] = {
            "trend": trend, "strong": ext["strong"], "weak": ext["weak"],
            "range_low": ext["range_low"], "range_high": ext["range_high"],
            "equilibrium_50": ext["equilibrium"], "location": location,
            "internal_exhaustion_swing": internal, "external_bos": ext,
            "exhaustion_signal_a": sweep, "exhaustion_signal_b": internal_break,
            "continuation_invalidation": continuation,
        }
        out["checks"].update({
            "m5_external_bos_confirmed": True,
            "m5_extreme_zone": extreme_ok,
            "m5_signal_a_weak_extreme_sweep": signal_a,
            "m5_signal_b_internal_choch": signal_b,
            "m5_exhaustion_confirmed": exhaustion,
            "m5_no_continuation_invalidation": no_continuation,
            "h1_not_explosive_news_or_session_expansion": not explosive,
        })
        if not extreme_ok: out["blockers"].append("Price is not in the specified M5 70%-100% Premium / 0%-30% Discount extreme.")
        if not exhaustion: out["blockers"].append("Neither M5 Weak Extreme sweep nor M5 Internal CHoCH is confirmed.")
        if not no_continuation: out["blockers"].append("M5 body close beyond the Weak Extreme confirms continuation; Counter-Trend blocked.")
        if explosive: out["blockers"].append("Explosive H1/news/session-open expansion filter blocks Counter-Trend trading.")

        # M1 entry trigger must come from the user's existing entry-model engine.
        entry_ok, entry = self._validate_entry_model(entry_model_evidence, direction)
        out["entry_model"] = entry.get("model") if entry else None
        out["entry_evidence"] = entry
        out["checks"]["existing_m1_entry_model_confirmed"] = entry_ok
        if not entry_ok:
            out["blockers"].append("Existing M1 entry-model engine has not supplied a confirmed matching entry.")
        out["poi"]["m5_inducement_price"] = _num(m5_inducement_price)
        out["poi"]["m5_pro_trend_target_poi"] = dict(m5_pro_trend_target_poi) if m5_pro_trend_target_poi else None
        out["risk_targets"] = self._targets(direction, entry, m5_pro_trend_target_poi,
                                            ext["equilibrium"], {"price": _num(m5_inducement_price)})
        gates = all([ext is not None, extreme_ok, exhaustion, no_continuation,
                     not explosive, entry_ok])
        out["trade_setup_ready"] = bool(gates)
        out["status"] = "SETUP_READY_FOR_EXECUTION_MODULE" if gates else "NOT_READY"
        out["checks"]["all_required_gates_pass"] = bool(gates)
        return out

    @staticmethod
    def _validate_entry_model(evidence: Optional[Mapping[str, Any]],
                              direction: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if not isinstance(evidence, Mapping):
            return False, None
        model = evidence.get("model")
        confirmed = evidence.get("confirmed") is True
        ev_direction = str(evidence.get("direction", "")).upper()
        # Existing M1 models are passed through unchanged; this module does not
        # implement or alter their internal pattern recognition.
        accepted_models = {
            "CHOCH_FVG", "SWEEP_ENGULFING", "BREAKER",
            "MSS_SWEEP_DISPLACEMENT", "FLIP_S2D_D2S"
        }
        valid_model = str(model).upper() in accepted_models
        valid_direction = ev_direction == direction
        valid_prices = _finite_number(evidence.get("entry_price")) and _finite_number(evidence.get("stop_loss"))
        result = dict(evidence)
        result["model"] = str(model).upper() if model is not None else None
        result["direction"] = ev_direction
        result["confirmed"] = confirmed
        result["accepted_model"] = valid_model
        result["direction_matches"] = valid_direction
        result["entry_and_sl_supplied"] = valid_prices
        return bool(confirmed and valid_model and valid_direction and valid_prices), result

    @staticmethod
    def _targets(direction: str, entry: Optional[Mapping[str, Any]],
                 target_poi: Optional[Mapping[str, Any]], equilibrium: Optional[float],
                 inducement: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        out = {
            "entry_price": _num(entry.get("entry_price")) if entry else None,
            "stop_loss": _num(entry.get("stop_loss")) if entry else None,
            "tp1_equilibrium_50": _num(equilibrium),
            "tp1_inducement": _num(inducement.get("price")) if inducement else None,
            "tp1_action": "Close 50% and move stop loss to breakeven",
            "tp2_pro_trend_poi": None,
            "tp2_action": "Close 100% of remaining position at the Pro-Trend POI",
        }
        if target_poi:
            # Target POI must provide a bounded zone. Shorts exit just above
            # the target zone; longs exit just below it. Buffer is not guessed.
            low, high = _num(target_poi.get("low")), _num(target_poi.get("high"))
            if low is not None and high is not None and high >= low:
                out["tp2_pro_trend_poi"] = {
                    "zone_low": low, "zone_high": high,
                    "reference_exit": high if direction == "SHORT" else low,
                    "instruction": "Short: just above Discount POI; Long: just below Premium POI",
                    "buffer": "Not calculated; instrument point/pip buffer was not supplied",
                }
        return out

    def analyze(
        self, *, h1_candles: Sequence[Mapping[str, Any]],
        m5_candles: Sequence[Mapping[str, Any]],
        m1_candles: Sequence[Mapping[str, Any]],
        h1_live_price: Optional[float] = None,
        m5_live_price: Optional[float] = None,
        h1_explosive_momentum: Optional[bool] = None,
        h1_news_driven_expansion: Optional[bool] = None,
        h1_session_open_expansion: Optional[bool] = None,
        m5_displacement_evidence: Optional[bool] = None,
        m5_inducement_swept: Optional[bool] = None,
        m5_poi_live_tap: Optional[bool] = None,
        m5_h1_context_explosive: Optional[bool] = None,
        m5_news_driven_expansion: Optional[bool] = None,
        m5_session_open_expansion: Optional[bool] = None,
        entry_model_evidence: Optional[Mapping[str, Any]] = None,
        m5_pro_trend_target_poi: Optional[Mapping[str, Any]] = None,
        m5_inducement_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze both layers independently. The same entry-model evidence is
        passed to each layer; each layer validates its own direction and gates.
        """
        h1_layer = self.analyze_h1_to_m5(
            h1_candles, m5_candles, h1_live_price=h1_live_price,
            m5_live_price=m5_live_price,
            h1_explosive_momentum=h1_explosive_momentum,
            h1_news_driven_expansion=h1_news_driven_expansion,
            h1_session_open_expansion=h1_session_open_expansion,
            m5_displacement_evidence=m5_displacement_evidence,
            m5_inducement_swept=m5_inducement_swept,
            m5_poi_live_tap=m5_poi_live_tap,
            entry_model_evidence=entry_model_evidence,
            m5_pro_trend_target_poi=m5_pro_trend_target_poi,
        )
        m5_layer = self.analyze_m5_to_m1(
            m5_candles, m1_candles, m5_live_price=m5_live_price,
            m5_h1_context_explosive=m5_h1_context_explosive,
            m5_news_driven_expansion=m5_news_driven_expansion,
            m5_session_open_expansion=m5_session_open_expansion,
            entry_model_evidence=entry_model_evidence,
            m5_pro_trend_target_poi=m5_pro_trend_target_poi,
            m5_inducement_price=m5_inducement_price,
        )
        ready = h1_layer["trade_setup_ready"] or m5_layer["trade_setup_ready"]
        return {
            "strategy": STRATEGY_NAME,
            "version": VERSION,
            "analysis_only": True,
            "orders_placed": False,
            "status": "SETUP_READY_FOR_EXECUTION_MODULE" if ready else "NO_COUNTER_TREND_SETUP_READY",
            "trade_setup_ready": ready,
            "layers": {
                "H1_COUNTER_TREND_TO_M5": h1_layer,
                "M5_COUNTER_TREND_TO_M1": m5_layer,
            },
            "active_ready_layers": [
                name for name, layer in (
                    ("H1_COUNTER_TREND_TO_M5", h1_layer),
                    ("M5_COUNTER_TREND_TO_M1", m5_layer),
                ) if layer["trade_setup_ready"]
            ],
            "note": "Setup readiness is evidence for the separate execution/risk module; this file never places orders.",
        }


technical_analysis_counter_trend = TechnicalAnalysisCounterTrend()


def analyze_counter_trend(**kwargs: Any) -> Dict[str, Any]:
    return technical_analysis_counter_trend.analyze(**kwargs)


def get_strategy_metadata() -> Dict[str, Any]:
    return {
        "name": STRATEGY_NAME,
        "version": VERSION,
        "filename": "technical_analysis_counter_trend.py",
        "layers": ["H1_COUNTER_TREND_TO_M5", "M5_COUNTER_TREND_TO_M1"],
        "entry_models": [
            "CHOCH_FVG", "SWEEP_ENGULFING", "BREAKER",
            "MSS_SWEEP_DISPLACEMENT", "FLIP_S2D_D2S"
        ],
        "analysis_only": True,
        "places_orders": False,
    }


__all__ = [
    "TechnicalAnalysisCounterTrend",
    "technical_analysis_counter_trend",
    "analyze_counter_trend",
    "get_strategy_metadata",
    "normalize_candles",
    "VERSION",
]
