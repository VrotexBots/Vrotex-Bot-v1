
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

        self.strategy_status[key] = {
            "strategy": "ORB",
            "session": key[0],
            "symbol": key[1],
            "status": status,
            "details": details or {},
            "updated_at": self._utc_now(),
        }

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
            "BREAKOUT_DETECTED_WAITING_FOR_SMC",
            {
                "direction": result["direction"],
                "breakout_level": result["breakout_level"],
            },
        )

        return {
            "detected": True,
            "reason": "BREAKOUT_WAITING_FOR_SMC_CONFIRMATION",
            "breakout": result.copy(),
        }

    # --------------------------------------------------------
    # SMC BREAKOUT EVIDENCE
    # --------------------------------------------------------

    @staticmethod
    def _validate_smc_evidence(
        evidence,
        direction,
    ):

        if not isinstance(evidence, dict):
            return False, "SMC_EVIDENCE_MISSING"

        displacement = (
            evidence.get("displacement_confirmed") is True
        )

        structure_event = str(
            evidence.get("structure_event", "")
        ).upper()

        structure_direction = str(
            evidence.get("structure_direction", "")
        ).upper()

        structure_valid = (
            structure_event in ("CHOCH", "BOS")
            and structure_direction == direction
        )

        if not displacement:
            return False, "DISPLACEMENT_NOT_CONFIRMED"

        if not structure_valid:
            return False, "CHOCH_OR_BOS_NOT_CONFIRMED"

        zones = evidence.get("entry_zones")

        if not isinstance(zones, (list, tuple)):
            return False, "ENTRY_ZONES_MISSING"

        valid_ob = False
        valid_fvg = False

        for zone in zones:

            if not isinstance(zone, dict):
                continue

            if zone.get("validated") is not True:
                continue

            zone_type = str(
                zone.get("type", "")
            ).upper()

            zone_direction = str(
                zone.get("direction", "")
            ).upper()

            try:

                zone_high = float(zone["high"])
                zone_low = float(zone["low"])

            except (KeyError, TypeError, ValueError):
                continue

            if (
                zone_direction != direction
                or zone_low <= 0
                or zone_high <= zone_low
            ):
                continue

            if zone_type == "OB":
                valid_ob = True

            elif zone_type == "FVG":
                valid_fvg = True

        if not valid_ob:
            return False, "VALID_ORDER_BLOCK_MISSING"

        if not valid_fvg:
            return False, "VALID_FVG_MISSING"

        return True, "SMC_BREAKOUT_CONFIRMED"

    # --------------------------------------------------------
    # CONFIRM BREAKOUT WITH M1 SMC EVIDENCE
    # --------------------------------------------------------

    def confirm_breakout(
        self,
        session,
        symbol,
        smc_evidence,
    ):

        session = str(session).upper()
        symbol = str(symbol).upper()

        key = self._key(session, symbol)

        breakout = self.detected_breakouts.get(key)

        if breakout is None:
            return {
                "success": False,
                "reason": "BREAKOUT_NOT_DETECTED",
            }

        if key in self.confirmed_breakouts:
            return {
                "success": False,
                "reason": "BREAKOUT_ALREADY_CONFIRMED",
            }

        valid, reason = self._validate_smc_evidence(
            smc_evidence,
            breakout["direction"],
        )

        if not valid:

            self._set_status(
                session,
                symbol,
                reason,
            )

            return {
                "success": False,
                "reason": reason,
            }

        confirmed = {
            **breakout,
            "smc_confirmed": True,
            "displacement_confirmed": True,
            "structure_event": str(
                smc_evidence["structure_event"]
            ).upper(),
            "structure_direction": str(
                smc_evidence["structure_direction"]
            ).upper(),
            "entry_zones": [
                dict(zone)
                for zone in smc_evidence["entry_zones"]
                if isinstance(zone, dict)
            ],
            "confirmed_at": self._utc_now(),
        }

        self.confirmed_breakouts[key] = confirmed

        self._set_status(
            session,
            symbol,
            "SMC_BREAKOUT_CONFIRMED_WAITING_FOR_RETEST",
            {
                "direction": confirmed["direction"],
                "structure_event": confirmed["structure_event"],
            },
        )

        return {
            "success": True,
            "reason": "SMC_BREAKOUT_CONFIRMED",
            "breakout": confirmed.copy(),
        }

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
                "reason": "WAITING_FOR_CONFIRMED_SMC_BREAKOUT",
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
