"""Vrotex Bot V1 - Central Strategy Authorization Engine.

Integration 4: independent strategy authorization routes.

This module deliberately contains no Master SMC imports, SMC scoring,
SMC evidence adapters, or strategy-to-strategy dependencies. ORB is
validated from ORB-owned breakout/M1/retest evidence only.

Authorization here means strategy approval only. The shared Risk Manager
(Integration 5) must still approve the candidate before execution.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, Iterable, Optional, Tuple


class CentralAuthorizationError(ValueError):
    """Raised when an authorization request is malformed."""


class CentralAuthorizationEngine:
    VERSION = "1.0"
    ORB_SYMBOLS = ("EURUSD", "GBPUSD", "BTCUSD")
    ORB_SESSIONS = ("ASIAN", "LONDON", "NEW_YORK")
    ORB_DIRECTIONS = ("BULLISH", "BEARISH")
    ORB_ENTRY_MODELS = ("LIMIT", "CONFIRMATION")
    ORB_ZONE_TYPES = ("ORB_RANGE_BOUNDARY",)

    def __init__(self, allowed_orb_symbols: Optional[Iterable[str]] = None):
        symbols = allowed_orb_symbols or self.ORB_SYMBOLS
        self.allowed_orb_symbols = frozenset(
            str(symbol).strip().upper() for symbol in symbols
        )
        self._lock = RLock()
        self._orb_approvals: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._orb_rejections: Dict[Tuple[str, str], Dict[str, Any]] = {}

    @staticmethod
    def _dict(value: Any) -> dict:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number == number and abs(number) != float("inf") else None

    @staticmethod
    def _timestamp(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            stamp = value
        elif isinstance(value, str):
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc)

    @staticmethod
    def _result(approved: bool, reason: str, **details: Any) -> dict:
        return {
            "success": approved,
            "strategy": "ORB",
            "authorization_status": (
                "STRATEGY_APPROVED_PENDING_RISK"
                if approved else "STRATEGY_REJECTED"
            ),
            "strategy_authorized": approved,
            # Risk Manager and Execution are later integration stages.
            "execution_authorized": False,
            "reason": reason,
            "authorized_at": datetime.now(timezone.utc).isoformat(),
            **details,
        }

    def authorize_orb_candidate(
        self,
        candidate: dict,
        breakout: dict,
        opening_range: Optional[dict] = None,
    ) -> dict:
        """Authorize an ORB retest using only the approved ORB rule set.

        A completed M1 close beyond the fixed first-session M5 range candle
        confirms the breakout. A later M1 retest of that same boundary plus
        the selected entry model produces the candidate. No SMC, BOS/CHoCH,
        displacement, OB/FVG, or A+ score is required here.
        """
        candidate = self._dict(candidate)
        breakout = self._dict(breakout)
        opening_range = self._dict(opening_range)

        strategy = str(candidate.get("strategy", "")).strip().upper()
        session = str(candidate.get("session", "")).strip().upper()
        symbol = str(candidate.get("symbol", "")).strip().upper()
        direction = str(candidate.get("direction", "")).strip().upper()
        entry_model = str(candidate.get("entry_model", "")).strip().upper()
        order_type = str(candidate.get("order_type", "")).strip().upper()
        zone_type = str(candidate.get("zone_type", "")).strip().upper()

        def reject(reason: str) -> dict:
            result = self._result(False, reason, session=session, symbol=symbol)
            with self._lock:
                if session and symbol:
                    self._orb_rejections[(session, symbol)] = deepcopy(result)
            return result

        if strategy != "ORB":
            return reject("STRATEGY_MISMATCH_ORB_ROUTE_ONLY")
        if session not in self.ORB_SESSIONS:
            return reject("UNAPPROVED_ORB_SESSION")
        if symbol not in self.allowed_orb_symbols:
            return reject("UNAPPROVED_ORB_SYMBOL")
        if direction not in self.ORB_DIRECTIONS:
            return reject("INVALID_ORB_DIRECTION")
        if entry_model not in self.ORB_ENTRY_MODELS:
            return reject("UNAPPROVED_ORB_ENTRY_MODEL")
        if zone_type != "ORB_RANGE_BOUNDARY":
            return reject("ENTRY_ZONE_MUST_BE_ORB_RANGE_BOUNDARY")
        if candidate.get("success") is not True:
            return reject("ENTRY_CANDIDATE_NOT_SUCCESSFUL")

        expected_orders = (
            {"BUY", "BUY_LIMIT"} if direction == "BULLISH"
            else {"SELL", "SELL_LIMIT"}
        )
        if order_type not in expected_orders:
            return reject("ORDER_SIDE_DOES_NOT_MATCH_BREAKOUT_DIRECTION")
        if entry_model == "CONFIRMATION" and order_type not in {"BUY", "SELL"}:
            return reject("CONFIRMATION_ENTRY_MUST_BE_MARKET_SIDE")
        if entry_model == "LIMIT" and order_type not in {"BUY_LIMIT", "SELL_LIMIT"}:
            return reject("LIMIT_ENTRY_MUST_USE_LIMIT_ORDER_SIDE")

        if breakout.get("detected") is not True or breakout.get("breakout_confirmed") is not True:
            return reject("ORB_RANGE_BREAKOUT_NOT_CONFIRMED")
        if str(breakout.get("direction", "")).strip().upper() != direction:
            return reject("BREAKOUT_DIRECTION_MISMATCH")
        if str(breakout.get("session", session)).strip().upper() != session:
            return reject("BREAKOUT_SESSION_MISMATCH")
        if str(breakout.get("symbol", symbol)).strip().upper() != symbol:
            return reject("BREAKOUT_SYMBOL_MISMATCH")

        zones = breakout.get("entry_zones")
        if not isinstance(zones, (list, tuple)):
            return reject("ORB_RANGE_BOUNDARY_ZONE_MISSING")
        matching_zones = [
            zone for zone in zones
            if isinstance(zone, dict)
            and str(zone.get("type", "")).strip().upper() == "ORB_RANGE_BOUNDARY"
            and str(zone.get("direction", "")).strip().upper() == direction
            and zone.get("validated") is True
            and self._number(zone.get("low")) is not None
            and self._number(zone.get("high")) is not None
            and abs(self._number(zone.get("high")) - self._number(zone.get("low"))) <= 1e-10
        ]
        if not matching_zones:
            return reject("VALIDATED_ORB_RANGE_BOUNDARY_MISSING")

        entry = self._number(candidate.get("entry_price"))
        stop = self._number(candidate.get("stop_loss"))
        target = self._number(candidate.get("take_profit"))
        zone_low = self._number(candidate.get("zone_low"))
        zone_high = self._number(candidate.get("zone_high"))
        if None in (entry, stop, target, zone_low, zone_high):
            return reject("ENTRY_STOP_TARGET_OR_ZONE_PRICE_MISSING")
        if min(entry, stop, target, zone_low, zone_high) <= 0:
            return reject("TRADE_LEVELS_MUST_BE_POSITIVE")
        if abs(zone_high - zone_low) > 1e-10:
            return reject("ORB_RANGE_BOUNDARY_MUST_BE_A_SINGLE_PRICE")
        if not any(
            abs(self._number(zone.get("low")) - zone_low) <= 1e-10
            and abs(self._number(zone.get("high")) - zone_high) <= 1e-10
            for zone in matching_zones
        ):
            return reject("CANDIDATE_ZONE_DOES_NOT_MATCH_CONFIRMED_ORB_BOUNDARY")
        if direction == "BULLISH" and not (stop < entry < target):
            return reject("BULLISH_TRADE_LEVELS_INVALID")
        if direction == "BEARISH" and not (target < entry < stop):
            return reject("BEARISH_TRADE_LEVELS_INVALID")
        if str(candidate.get("target_type", "")).strip().upper() != "OPPOSING_LIQUIDITY":
            return reject("TARGET_MUST_BE_OPPOSING_LIQUIDITY")

        retest = self._dict(candidate.get("retest_candle"))
        retest_high = self._number(retest.get("high"))
        retest_low = self._number(retest.get("low"))
        if retest_high is None or retest_low is None or retest_high < retest_low:
            return reject("VALID_RETEST_CANDLE_MISSING")
        boundary = zone_low
        if retest_high < boundary or retest_low > boundary:
            return reject("RETEST_CANDLE_DID_NOT_TOUCH_ORB_BOUNDARY")

        # If an opening range is supplied, verify its high/low and ensure the
        # selected boundary is exactly the breakout side of that fixed range.
        if opening_range:
            range_data = opening_range.get("opening_range", opening_range)
            range_data = self._dict(range_data)
            range_high = self._number(range_data.get("high"))
            range_low = self._number(range_data.get("low"))
            if range_high is None or range_low is None or range_high <= range_low:
                return reject("OPENING_RANGE_INVALID")
            expected_boundary = range_high if direction == "BULLISH" else range_low
            if abs(boundary - expected_boundary) > 1e-10:
                return reject("BOUNDARY_DOES_NOT_MATCH_BREAKOUT_SIDE_OF_OPENING_RANGE")

        breakout_time = self._timestamp(breakout.get("detected_at"))
        # The completed M1 close itself is the breakout confirmation; there is
        # deliberately no separate confirmed_at / structure-confirmation event.
        candidate_time = self._timestamp(candidate.get("created_at"))
        retest_time = self._timestamp(retest.get("timestamp"))
        if breakout_time is None or candidate_time is None or retest_time is None:
            return reject("ORB_EVENT_TIMESTAMPS_MISSING_OR_INVALID")
        if retest_time <= breakout_time or candidate_time < retest_time:
            return reject("ORB_EVENT_SEQUENCE_INVALID")

        key = (session, symbol)
        with self._lock:
            if key in self._orb_approvals:
                return self._result(
                    False,
                    "ORB_SESSION_SYMBOL_ALREADY_AUTHORIZED",
                    session=session,
                    symbol=symbol,
                    existing_approval=deepcopy(self._orb_approvals[key]),
                )
            approved = self._result(
                True,
                "ORB_INDEPENDENT_BREAKOUT_RETEST_CHECKS_PASSED_PENDING_SHARED_RISK",
                session=session,
                symbol=symbol,
                direction=direction,
                entry_model=entry_model,
                order_type=order_type,
                execution_order_type=("MARKET" if order_type in {"BUY", "SELL"} else "LIMIT"),
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                zone_type=zone_type,
                confirmation_source="COMPLETED_M1_RANGE_BREAKOUT_AND_LATER_M1_RETEST",
                risk_manager_required=True,
            )
            self._orb_approvals[key] = deepcopy(approved)
            self._orb_rejections.pop(key, None)
            return approved

    def get_orb_authorization(self, session: str, symbol: str) -> Optional[dict]:
        key = (str(session).upper(), str(symbol).upper())
        with self._lock:
            value = self._orb_approvals.get(key)
            return deepcopy(value) if value else None

    def get_orb_rejection(self, session: str, symbol: str) -> Optional[dict]:
        key = (str(session).upper(), str(symbol).upper())
        with self._lock:
            value = self._orb_rejections.get(key)
            return deepcopy(value) if value else None

    def reset_orb_session(self, session: str, symbol: str) -> None:
        """Clear only this in-memory session authorization state."""
        key = (str(session).upper(), str(symbol).upper())
        with self._lock:
            self._orb_approvals.pop(key, None)
            self._orb_rejections.pop(key, None)


central_authorization_engine = CentralAuthorizationEngine()
