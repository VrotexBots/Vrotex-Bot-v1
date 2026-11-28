
"""
VROTEX BOT V1 - ORB STRATEGY ENGINE
File: orb_strategy_engine.py

Main coordinator for the independent ORB strategy.

Workflow:
1. Detect the configured trading session.
2. Capture that session's first completed M5 opening candle.
3. Detect a completed M1 candle close beyond the opening-range high or low.
4. Wait for price to retest the broken opening-range boundary.
5. Generate a limit or rejection/confirmation entry candidate.
6. Pass candidates to central authorization and shared risk systems.

No separate M1 CHoCH/BOS, displacement, OB/FVG or SMC confirmation is required.

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
from central_authorization_engine import (
    CentralAuthorizationEngine,
    central_authorization_engine as default_central_authorization_engine,
)
from orb_risk_integration import (
    ORBSharedRiskGate,
    orb_shared_risk_gate as default_orb_shared_risk_gate,
)


class ORBStrategyEngine:

    def __init__(
        self,
        session_engine=None,
        analysis_engine=None,
        entry_engine=None,
        authorization_engine=None,
        risk_gate=None,
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

        self.authorization_engine = (
            authorization_engine
            if authorization_engine is not None
            else default_central_authorization_engine
        )

        self.risk_gate = (
            risk_gate
            if risk_gate is not None
            else default_orb_shared_risk_gate
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

        # The range-close breakout is the complete breakout confirmation.
        # Store it directly as the active breakout; there is no second
        # M1 structure-confirmation gate.
        boundary = float(result["breakout_level"])
        eligible_breakout = {
            **result,
            "breakout_confirmed": True,
            "confirmation_method": "M1_CLOSE_BEYOND_SESSION_M5_OPENING_RANGE",
            "orb_m1_confirmation_required": False,
            "entry_zones": [{
                "type": "ORB_RANGE_BOUNDARY",
                "direction": result["direction"],
                "low": boundary,
                "high": boundary,
                "entry_price": boundary,
                "validated": True,
            }],
        }
        self.confirmed_breakouts[key] = eligible_breakout

        self._set_status(
            session,
            symbol,
            "BREAKOUT_CONFIRMED_WAITING_FOR_RANGE_RETEST",
            {
                "direction": result["direction"],
                "breakout_level": boundary,
                "confirmation_method": eligible_breakout["confirmation_method"],
            },
        )

        return {
            "detected": True,
            "reason": "BREAKOUT_CONFIRMED_WAITING_FOR_RANGE_RETEST",
            "breakout": eligible_breakout.copy(),
        }

    # --------------------------------------------------------
    # SIMPLE ORB BREAKOUT ACCEPTANCE
    # --------------------------------------------------------

    # A completed M1 candle closing beyond the first completed M5
    # session-opening candle confirms the range breakout. No separate
    # M1 CHoCH/BOS, displacement, OB, FVG or SMC confirmation is used.

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
                "reason": "WAITING_FOR_SESSION_OPENING_RANGE_BREAKOUT",
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
    # CENTRAL AUTHORIZATION - ORB-OWNED ROUTE
    # --------------------------------------------------------

    def authorize_entry_candidate(self, session, symbol, direction):
        """Submit this ORB candidate to the central ORB authorization route.

        This method uses only ORB's confirmed breakout, selected opening
        range, and ORB entry candidate. It does not call or inspect Master SMC,
        ProTrend, or CounterTrend authorization results. Shared risk approval
        remains a separate downstream step.
        """
        session = str(session).upper()
        symbol = str(symbol).upper()
        direction = str(direction).upper()

        candidate = self.get_entry_candidate(
            session, symbol, direction
        )
        if not isinstance(candidate, dict):
            return {
                "success": False,
                "strategy": "ORB",
                "strategy_authorized": False,
                "execution_authorized": False,
                "reason": "ORB_ENTRY_CANDIDATE_NOT_FOUND",
            }

        breakout = self.get_breakout(session, symbol)
        if not isinstance(breakout, dict):
            return {
                "success": False,
                "strategy": "ORB",
                "strategy_authorized": False,
                "execution_authorized": False,
                "reason": "ORB_CONFIRMED_BREAKOUT_NOT_FOUND",
            }

        opening_range = self.get_opening_range(session, symbol)
        result = self.authorization_engine.authorize_orb_candidate(
            candidate=candidate,
            breakout=breakout,
            opening_range=opening_range,
        )

        if result.get("strategy_authorized") is True:
            self._set_status(
                session,
                symbol,
                "ORB_STRATEGY_AUTHORIZED_PENDING_SHARED_RISK",
                {
                    "direction": direction,
                    "authorization_status": result.get("authorization_status"),
                    "reason": result.get("reason"),
                },
            )
        else:
            self._set_status(
                session,
                symbol,
                result.get("reason", "ORB_CENTRAL_AUTHORIZATION_REJECTED"),
            )

        return result

    # --------------------------------------------------------
    # SHARED RISK - ORB ROUTE
    # --------------------------------------------------------

    def authorize_and_check_risk(
        self,
        session,
        symbol,
        direction,
        risk_snapshot,
        *,
        loss_per_lot_at_stop=None,
    ):
        """Run ORB strategy authorization, then the shared Vrotex risk gate.

        This method never places an order. It requires a fresh ORB candidate,
        the ORB-owned central authorization route, and a live RiskSnapshot
        supplied by the account/runtime layer.
        """
        authorization = self.authorize_entry_candidate(
            session, symbol, direction
        )
        if authorization.get("strategy_authorized") is not True:
            return {
                **authorization,
                "risk_approved": False,
                "execution_authorized": False,
                "risk_reason": "ORB_STRATEGY_AUTHORIZATION_NOT_GRANTED",
            }

        risk_result = self.risk_gate.evaluate_authorized_candidate(
            authorization,
            risk_snapshot,
            loss_per_lot_at_stop=loss_per_lot_at_stop,
        )
        return {
            **authorization,
            "risk": risk_result,
            "risk_approved": risk_result.get("risk_approved") is True,
            "execution_authorized": False,
            "reason": risk_result.get("reason", authorization.get("reason")),
        }

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
