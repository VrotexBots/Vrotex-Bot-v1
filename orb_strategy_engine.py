
"""
VROTEX BOT V1 - ORB STRATEGY ENGINE
File: orb_strategy_engine.py

Main coordinator for the independent ORB strategy.

Workflow:
1. Detect the configured trading session.
2. Capture the first completed M5 opening candle.
3. Detect a full-close M5/M1 breakout from the range.
4. Require M1 displacement and CHoCH/BOS evidence.
5. Require validated Order Block and FVG zones.
6. Wait for an OB/FVG retest.
7. Generate either a limit or confirmation entry candidate.
8. Pass candidates to central authorization and risk systems.

This module does NOT execute orders or bypass
the central Vrotex authorization and risk controls.
"""

from datetime import datetime, timezone
import logging

from orb_config import (
    ORB_ENABLED,
    ORB_SYMBOLS,
)

from orb_session_engine import ORBSessionEngine
from orb_analysis_engine import ORBAnalysisEngine
from orb_entry_engine import ORBEntryEngine


class ORBStrategyEngine:

    def __init__(
        self,
        session_engine=None,
        analysis_engine=None,
        entry_engine=None,
        m1_swing_lookback=2,
        m1_displacement_multiplier=1.5,
    ):

        self.session_engine = (
            session_engine or ORBSessionEngine()
        )

        self.analysis_engine = (
            analysis_engine or ORBAnalysisEngine(
                self.session_engine
            )
        )

        self.entry_engine = (
            entry_engine or ORBEntryEngine()
        )

        self.detected_breakouts = {}
        self.confirmed_breakouts = {}

        self.strategy_status = {}
        self._logged_active_sessions = set()

        self.logger = logging.getLogger(__name__)

        # ORB-owned M1 confirmation settings. These are configurable
        # and do not read or inherit Master SMC decisions.
        self.m1_swing_lookback = max(2, int(m1_swing_lookback))
        self.m1_displacement_multiplier = max(1.0, float(m1_displacement_multiplier))

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    @staticmethod
    def _utc_now():

        return datetime.now(timezone.utc)

    # --------------------------------------------------------
    # IDENTITY
    # --------------------------------------------------------

    @staticmethod
    def _key(session, symbol):

        return (
            str(session).upper(),
            str(symbol).upper(),
        )

    @staticmethod
    def _validate_symbol(symbol):

        return (
            str(symbol).upper() in ORB_SYMBOLS
        )

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    def _set_status(
        self,
        session,
        symbol,
        status,
        details=None,
    ):

        key = self._key(session, symbol)
        previous = self.strategy_status.get(key)
        previous_status = previous.get("status") if previous else None

        self.strategy_status[key] = {
            "strategy": "ORB",
            "session": key[0],
            "symbol": key[1],
            "status": status,
            "details": details or {},
            "updated_at": self._utc_now(),
        }

        # Log only on state transitions to avoid flooding the runtime logs
        # when the scanner checks the same condition repeatedly.
        if previous_status != status:
            event_names = {
                "OPENING_RANGE_CAPTURED": "ORB RANGE ESTABLISHED",
                "WAITING_FOR_BREAKOUT": "ORB WAITING FOR BREAKOUT",
                "BREAKOUT_DETECTED_WAITING_FOR_ORB_M1_CONFIRMATION": "ORB BREAKOUT DETECTED",
                "ORB_M1_CONFIRMED_WAITING_FOR_RETEST": "ORB WAITING FOR RETEST",
                "ENTRY_CANDIDATE_REQUIRES_CENTRAL_AUTHORIZATION": "ORB RETEST CONFIRMED",
            }
            event = event_names.get(status, f"ORB STATUS: {status}")
            self.logger.info(
                "%s | session=%s | symbol=%s | details=%s",
                event,
                key[0],
                key[1],
                details or {},
            )

    def get_status(self, session, symbol):

        result = self.strategy_status.get(
            self._key(session, symbol)
        )

        return result.copy() if result else None

    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    def get_session_status(
        self,
        session,
        now=None,
    ):

        if not ORB_ENABLED:
            return {
                "available": False,
                "reason": "ORB_DISABLED",
            }

        window = self.session_engine.get_session_window(
            str(session).upper(),
            now,
        )

        if window is None:
            return {
                "available": False,
                "reason": "SESSION_UNAVAILABLE",
            }

        active_key = (
            str(window["session"]).upper(),
            str(window["opening_time"]),
        )
        if active_key not in self._logged_active_sessions:
            self._logged_active_sessions.add(active_key)
            self.logger.info(
                "ORB SESSION ACTIVE | session=%s | timezone=%s | opening_time=%s | closing_time=%s",
                window["session"],
                window["timezone"],
                window["opening_time"],
                window["closing_time"],
            )

        return {
            "available": True,
            "session": window["session"],
            "timezone": window["timezone"],
            "opening_time": window["opening_time"],
            "closing_time": window["closing_time"],
            "status": window["status"],
        }

    # --------------------------------------------------------
    # CAPTURE M5 OPENING RANGE
    # --------------------------------------------------------

    def capture_opening_range(
        self,
        session,
        symbol,
        m5_candle,
        now=None,
    ):

        if not ORB_ENABLED:
            return {
                "success": False,
                "reason": "ORB_DISABLED",
            }

        session = str(session).upper()
        symbol = str(symbol).upper()

        if not self._validate_symbol(symbol):
            return {
                "success": False,
                "reason": "UNAPPROVED_SYMBOL",
            }

        result = self.analysis_engine.capture_opening_range(
            session_name=session,
            symbol=symbol,
            candle=m5_candle,
            now=now,
        )

        if not result.get("success"):

            self._set_status(
                session,
                symbol,
                result.get("reason", "RANGE_CAPTURE_FAILED"),
            )

            return result

        self._set_status(
            session,
            symbol,
            "OPENING_RANGE_CAPTURED",
            {
                "high": result["opening_range"]["high"],
                "low": result["opening_range"]["low"],
            },
        )

        return result

    # --------------------------------------------------------
    # BREAKOUT DETECTION
    # --------------------------------------------------------

    def detect_breakout(
        self,
        session,
        symbol,
        breakout_candle,
    ):

        if not ORB_ENABLED:
            return {
                "detected": False,
                "reason": "ORB_DISABLED",
            }

        session = str(session).upper()
        symbol = str(symbol).upper()

        if not self._validate_symbol(symbol):
            return {
                "detected": False,
                "reason": "UNAPPROVED_SYMBOL",
            }

        key = self._key(session, symbol)

        if key in self.detected_breakouts:
            return {
                "detected": False,
                "reason": "BREAKOUT_ALREADY_RECORDED",
            }

        result = self.analysis_engine.detect_breakout(
            session_name=session,
            symbol=symbol,
            candle=breakout_candle,
        )

        if not result.get("detected"):

            self._set_status(
                session,
                symbol,
                result.get("reason", "WAITING_FOR_BREAKOUT"),
            )

            return result

        self.detected_breakouts[key] = result.copy()

        self._set_status(
            session,
            symbol,
            "BREAKOUT_DETECTED_WAITING_FOR_ORB_M1_CONFIRMATION",
            {
                "direction": result["direction"],
                "breakout_level": result["breakout_level"],
            },
        )

        return {
            "detected": True,
            "reason": "BREAKOUT_WAITING_FOR_ORB_M1_CONFIRMATION",
            "breakout": result.copy(),
        }

    # --------------------------------------------------------
    # ORB-OWNED M1 STRUCTURE / DISPLACEMENT / ZONES
    # --------------------------------------------------------

    @staticmethod
    def _normalise_m1_candle(candle):
        if not isinstance(candle, dict):
            raise ValueError("M1 candle must be a dictionary.")
        values = {}
        for field in ("open", "high", "low", "close"):
            try:
                values[field] = float(candle[field])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"Invalid or missing M1 {field}.")
        if any(v <= 0 for v in values.values()):
            raise ValueError("M1 candle prices must be positive.")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("Invalid M1 candle high.")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("Invalid M1 candle low.")
        stamp = candle.get("timestamp", candle.get("time"))
        if stamp is None:
            raise ValueError("M1 candle requires timestamp or time.")
        if isinstance(stamp, str):
            try:
                stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("M1 candle time must be ISO datetime.")
        if isinstance(stamp, (int, float)):
            stamp = datetime.fromtimestamp(float(stamp), tz=timezone.utc)
        if not isinstance(stamp, datetime):
            raise ValueError("Unsupported M1 candle timestamp type.")
        if stamp.tzinfo is None:
            raise ValueError("M1 candle timestamp must be timezone-aware.")
        values["timestamp"] = stamp.astimezone(timezone.utc)
        return values

    def _detect_orb_m1_evidence(self, m1_candles, direction):
        if not isinstance(m1_candles, (list, tuple)):
            return False, "M1_CANDLES_REQUIRED", None
        try:
            candles = [self._normalise_m1_candle(c) for c in m1_candles]
        except ValueError as exc:
            return False, str(exc), None
        candles.sort(key=lambda c: c["timestamp"])
        lookback = self.m1_swing_lookback
        if len(candles) < max(5, (lookback * 2) + 1):
            return False, "INSUFFICIENT_M1_CANDLES", None

        # A pivot is confirmed only after candles exist on both sides.
        pivots_high, pivots_low = [], []
        for i in range(lookback, len(candles) - lookback):
            window = candles[i-lookback:i+lookback+1]
            current = candles[i]
            if current["high"] == max(x["high"] for x in window):
                pivots_high.append((i, current["high"]))
            if current["low"] == min(x["low"] for x in window):
                pivots_low.append((i, current["low"]))

        latest = candles[-1]
        prior = candles[:-1]
        if not prior or not pivots_high or not pivots_low:
            return False, "M1_SWING_POINTS_NOT_CONFIRMED", None

        if direction == "BULLISH":
            eligible = [(i, price) for i, price in pivots_high if i < len(candles)-1]
            if not eligible:
                return False, "M1_BULLISH_SWING_HIGH_MISSING", None
            swing_price = eligible[-1][1]
            structure_event = "BOS" if latest["close"] > swing_price else None
            body = latest["close"] - latest["open"]
        else:
            eligible = [(i, price) for i, price in pivots_low if i < len(candles)-1]
            if not eligible:
                return False, "M1_BEARISH_SWING_LOW_MISSING", None
            swing_price = eligible[-1][1]
            structure_event = "BOS" if latest["close"] < swing_price else None
            body = latest["open"] - latest["close"]

        # CHoCH/BOS authorization requires a full candle-body close past swing.
        if structure_event is None:
            return False, "M1_CHOCH_BOS_BODY_CLOSE_NOT_CONFIRMED", None

        ranges = [c["high"] - c["low"] for c in prior[-10:] if c["high"] > c["low"]]
        if not ranges:
            return False, "M1_DISPLACEMENT_BASELINE_MISSING", None
        average_range = sum(ranges) / len(ranges)
        if body <= 0 or body < average_range * self.m1_displacement_multiplier:
            return False, "M1_DISPLACEMENT_NOT_CONFIRMED", None

        zones = []
        # Three-candle fair value gap, aligned with the breakout direction.
        if len(candles) >= 3:
            left, right = candles[-3], candles[-1]
            if direction == "BULLISH" and right["low"] > left["high"]:
                zones.append({"type": "FVG", "direction": direction, "low": left["high"], "high": right["low"], "validated": True})
            elif direction == "BEARISH" and right["high"] < left["low"]:
                zones.append({"type": "FVG", "direction": direction, "low": right["high"], "high": left["low"], "validated": True})

        # Order block: last opposite-colour candle preceding the displacement candle.
        for candidate in reversed(candles[:-1][-5:]):
            opposite = (direction == "BULLISH" and candidate["close"] < candidate["open"]) or (direction == "BEARISH" and candidate["close"] > candidate["open"])
            if opposite:
                zones.append({"type": "OB", "direction": direction, "low": candidate["low"], "high": candidate["high"], "validated": True})
                break

        valid_zones = [z for z in zones if z["low"] > 0 and z["high"] > z["low"]]
        if not valid_zones:
            return False, "VALID_OB_OR_FVG_MISSING", None

        evidence = {
            "structure_event": structure_event,
            "structure_direction": direction,
            "structure_level": swing_price,
            "displacement_confirmed": True,
            "displacement_body": body,
            "displacement_average_range": average_range,
            "entry_zones": valid_zones,
            "confirmation_candle": latest,
            "confirmation_source": "ORB_INDEPENDENT_M1_ANALYSIS",
        }
        return True, "ORB_M1_CONFIRMATION_PASSED", evidence

    # --------------------------------------------------------
    # CONFIRM BREAKOUT USING ORB'S OWN M1 CANDLES
    # --------------------------------------------------------

    def confirm_breakout(
        self,
        session,
        symbol,
        m1_candles,
    ):
        session = str(session).upper()
        symbol = str(symbol).upper()
        key = self._key(session, symbol)
        breakout = self.detected_breakouts.get(key)
        if breakout is None:
            return {"success": False, "reason": "BREAKOUT_NOT_DETECTED"}
        if key in self.confirmed_breakouts:
            return {"success": False, "reason": "BREAKOUT_ALREADY_CONFIRMED"}

        valid, reason, evidence = self._detect_orb_m1_evidence(
            m1_candles, breakout["direction"]
        )
        if valid:
            breakout_time = breakout.get("detected_at")
            confirmation_time = evidence["confirmation_candle"]["timestamp"]
            if isinstance(breakout_time, datetime) and confirmation_time <= breakout_time:
                valid, reason, evidence = False, "M1_CONFIRMATION_MUST_FOLLOW_BREAKOUT", None
        if not valid:
            self._set_status(session, symbol, reason)
            return {"success": False, "reason": reason}

        confirmed = {
            **breakout,
            "smc_confirmed": False,
            "orb_m1_confirmed": True,
            "displacement_confirmed": True,
            "structure_event": evidence["structure_event"],
            "structure_direction": evidence["structure_direction"],
            "structure_level": evidence["structure_level"],
            "entry_zones": [dict(zone) for zone in evidence["entry_zones"]],
            "confirmation_candle": evidence["confirmation_candle"],
            "confirmation_source": evidence["confirmation_source"],
            "confirmed_at": self._utc_now(),
        }
        self.confirmed_breakouts[key] = confirmed
        self._set_status(
            session, symbol, "ORB_M1_CONFIRMED_WAITING_FOR_RETEST",
            {"direction": confirmed["direction"], "structure_event": confirmed["structure_event"]},
        )
        return {"success": True, "reason": "ORB_M1_CONFIRMATION_PASSED", "breakout": confirmed.copy()}

    # --------------------------------------------------------
    # RETEST AND ENTRY CANDIDATE
    # --------------------------------------------------------

    def evaluate_entry(
        self,
        session,
        symbol,
        m1_candle,
        entry_model,
        tolerance,
        stop_loss,
        liquidity_target,
    ):

        if not ORB_ENABLED:
            return {
                "success": False,
                "reason": "ORB_DISABLED",
            }

        session = str(session).upper()
        symbol = str(symbol).upper()

        key = self._key(session, symbol)

        if not self._validate_symbol(symbol):
            return {
                "success": False,
                "reason": "UNAPPROVED_SYMBOL",
            }

        breakout = self.confirmed_breakouts.get(key)

        if breakout is None:

            return {
                "success": False,
                "reason": "WAITING_FOR_ORB_M1_CONFIRMED_BREAKOUT",
            }

        result = self.entry_engine.evaluate_retest(
            breakout=breakout,
            candle=m1_candle,
            entry_zones=breakout["entry_zones"],
            entry_model=entry_model,
            tolerance=tolerance,
            stop_loss=stop_loss,
            liquidity_target=liquidity_target,
        )

        if not result.get("success"):

            self._set_status(
                session,
                symbol,
                result.get("reason", "WAITING_FOR_ENTRY"),
            )

            return result

        candidate = result["candidate"]

        self._set_status(
            session,
            symbol,
            "ENTRY_CANDIDATE_REQUIRES_CENTRAL_AUTHORIZATION",
            {
                "direction": candidate["direction"],
                "entry_model": candidate["entry_model"],
                "order_type": candidate["order_type"],
                "entry_price": candidate["entry_price"],
            },
        )

        return {
            "success": True,
            "reason": "ENTRY_CANDIDATE_REQUIRES_CENTRAL_AUTHORIZATION",
            "candidate": candidate,
            "execution_authorized": False,
        }

    # --------------------------------------------------------
    # STATE ACCESS
    # --------------------------------------------------------

    def get_opening_range(self, session, symbol):

        return self.analysis_engine.get_opening_range(
            str(session).upper(),
            str(symbol).upper(),
        )

    def get_breakout(self, session, symbol):

        result = self.confirmed_breakouts.get(
            self._key(session, symbol)
        )

        return result.copy() if result else None

    def get_detected_breakout(self, session, symbol):

        result = self.detected_breakouts.get(
            self._key(session, symbol)
        )

        return result.copy() if result else None

    def get_entry_candidate(
        self,
        session,
        symbol,
        direction,
    ):

        return self.entry_engine.get_candidate(
            str(session).upper(),
            str(symbol).upper(),
            str(direction).upper(),
        )

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    def reset_session(self, session, symbol):

        session = str(session).upper()
        symbol = str(symbol).upper()

        key = self._key(session, symbol)

        self.detected_breakouts.pop(key, None)
        self.confirmed_breakouts.pop(key, None)
        self.strategy_status.pop(key, None)

        self.analysis_engine.reset_session(
            session,
            symbol,
        )

        self.entry_engine.reset_session(
            session,
            symbol,
        )
