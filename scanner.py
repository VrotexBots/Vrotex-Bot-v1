
"""
Vrotex Bot V1 - Market Scanner
Version: 3.2

Approved instruments:
    EURUSD
    GBPUSD
    BTCUSD

Strategy timeframes:
    H1 -> M5 -> M1

Responsibilities:
    - Continuous instrument scanning
    - Async market-data collection
    - Technical analysis
    - Fundamental analysis
    - Risk-check collection
    - Evidence collection
    - Master SMC analysis
    - Setup-state reporting

This module does NOT execute orders.
"""

import asyncio
import inspect
import logging
import threading
import time
import traceback

from datetime import datetime, timezone

logger = logging.getLogger("vrotex.market_scanner")


class MarketScanner:

    VERSION = "3.2"

    INSTRUMENTS = (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    )

    TIMEFRAMES = (
        "H1",
        "M5",
        "M1",
    )

    CANDLE_COUNT = 1000
    DEFAULT_SCAN_INTERVAL = 30

    def __init__(
        self,
        market_data_engine=None,
        technical_analysis_engine=None,
        fundamental_analysis_engine=None,
        risk_management_engine=None,
        smc_engine=None,
        scan_interval=None,
    ):

        self.market_data_engine = market_data_engine
        self.technical_analysis_engine = technical_analysis_engine
        self.fundamental_analysis_engine = fundamental_analysis_engine
        self.risk_management_engine = risk_management_engine
        self.smc_engine = smc_engine

        self.scan_interval = (
            scan_interval or self.DEFAULT_SCAN_INTERVAL
        )

        self.running = False
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        self.last_scan_time = None
        self.last_scan_results = {}
        self.scan_count = 0
        self.error_count = 0

        self.instrument_states = {
            symbol: {
                "symbol": symbol,
                "status": "INITIALIZING",
                "last_scan": None,
                "last_price": None,
                "last_error": None,
                "setup_found": False,
                "setup_direction": None,
                "setup_type": None,
                "a_plus_score": 0,
                "execution_authorized": False,
                "fundamental_status": "NOT_ANALYZED",
                "risk_status": "NOT_ANALYZED",
            }
            for symbol in self.INSTRUMENTS
        }

        self._initialize_engines()

        logger.info(
            "Market Scanner V%s initialized | "
            "Instruments=%s | Timeframes=%s",
            self.VERSION,
            self.INSTRUMENTS,
            self.TIMEFRAMES,
        )

    # =========================================================
    # ASYNC COMPATIBILITY
    # =========================================================

    @staticmethod
    async def _invoke(method, *args, **kwargs):
        """
        Safely execute either an async or synchronous engine method.

        Async methods execute on the current event loop.
        Synchronous methods execute in a worker thread.
        If a synchronous method returns an awaitable,
        that awaitable is also awaited.
        """

        if not callable(method):
            raise RuntimeError("Engine method is not callable")

        if inspect.iscoroutinefunction(method):

            return await method(
                *args,
                **kwargs,
            )

        result = await asyncio.to_thread(
            method,
            *args,
            **kwargs,
        )

        if inspect.isawaitable(result):

            return await result

        return result

    # =========================================================
    # ENGINE INITIALIZATION
    # =========================================================

    @staticmethod
    def _load_engine(module_name, names):

        try:

            module = __import__(
                module_name,
                fromlist=list(names),
            )

            for name in names:

                engine = getattr(
                    module,
                    name,
                    None,
                )

                if engine is not None:
                    return engine

        except Exception as exc:

            logger.warning(
                "Engine import failed | %s | %s",
                module_name,
                exc,
            )

        return None

    def _initialize_engines(self):

        if self.market_data_engine is None:

            self.market_data_engine = (
                self._load_engine(
                    "market_data_engine",
                    ("market_data_engine",),
                )
            )

        if self.technical_analysis_engine is None:

            self.technical_analysis_engine = (
                self._load_engine(
                    "technical_analysis_engine",
                    ("technical_analysis_engine",),
                )
            )

        if self.fundamental_analysis_engine is None:

            self.fundamental_analysis_engine = (
                self._load_engine(
                    "fundamental_analysis_engine",
                    (
                        "fundamental_analysis_engine",
                        "fundamental_engine",
                    ),
                )
            )

        if self.risk_management_engine is None:

            self.risk_management_engine = (
                self._load_engine(
                    "risk_management_engine",
                    (
                        "risk_management_engine",
                        "risk_manager",
                    ),
                )
            )

            if self.risk_management_engine is None:

                self.risk_management_engine = (
                    self._load_engine(
                        "risk_manager",
                        (
                            "risk_manager",
                            "risk_management_engine",
                        ),
                    )
                )

        if self.smc_engine is None:

            self.smc_engine = (
                self._load_engine(
                    "smc_engine",
                    (
                        "smc_engine",
                        "master_smc_engine",
                    ),
                )
            )

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _utc_now():

        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _safe_float(value, default=None):

        try:

            if value is None:
                return default

            result = float(value)

            if not result == result:
                return default

            return result

        except (ValueError, TypeError, OverflowError):

            return default

    @staticmethod
    def _safe_dict(value):

        if isinstance(value, dict):
            return value

        return {}

    @staticmethod
    def _safe_list(value):

        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        return []

    @staticmethod
    def _supports_keyword(method, keyword):
        """
        Determine whether a callable accepts a keyword,
        including callables that accept **kwargs.
        """

        try:

            signature = inspect.signature(method)

            parameters = signature.parameters

            if keyword in parameters:
                return True

            return any(
                parameter.kind
                == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )

        except (TypeError, ValueError):

            # Unknown signature: assume keyword is supported.
            return True

    # =========================================================
    # MARKET DATA - ASYNC FIX
    # =========================================================

    async def _get_candles(
        self,
        symbol,
        timeframe,
        count=None,
    ):

        count = count or self.CANDLE_COUNT

        engine = self.market_data_engine

        if engine is None:

            raise RuntimeError(
                "Market Data Engine unavailable"
            )

        method = getattr(
            engine,
            "get_recent_candles",
            None,
        )

        if not callable(method):

            raise RuntimeError(
                "get_recent_candles() unavailable"
            )

        # Determine whether price_type is supported
        # without swallowing TypeErrors raised internally
        # by the market-data engine.

        supports_price_type = (
            self._supports_keyword(
                method,
                "price_type",
            )
        )

        if supports_price_type:

            candles = await self._invoke(
                method,
                symbol,
                timeframe,
                count,
                price_type="bid",
            )

        else:

            candles = await self._invoke(
                method,
                symbol,
                timeframe,
                count,
            )

        if candles is None:
            return []

        if isinstance(candles, dict):

            candles = candles.get(
                "candles",
                candles.get(
                    "data",
                    [],
                ),
            )

        candles = self._safe_list(candles)

        return candles

    # =========================================================
    # LIVE PRICE - ASYNC COMPATIBLE
    # =========================================================

    async def _get_live_price(self, symbol):

        engine = self.market_data_engine

        if engine is None:
            return None

        possible_methods = (
            "get_live_tick",
            "get_latest_tick",
            "get_tick",
            "get_current_price",
        )

        for method_name in possible_methods:

            method = getattr(
                engine,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:

                tick = await self._invoke(
                    method,
                    symbol,
                )

                if tick is None:
                    continue

                if isinstance(tick, (int, float)):

                    return self._safe_float(
                        tick
                    )

                if isinstance(tick, dict):

                    bid = self._safe_float(
                        tick.get("bid")
                    )

                    ask = self._safe_float(
                        tick.get("ask")
                    )

                    last = self._safe_float(
                        tick.get("last")
                    )

                    mid = self._safe_float(
                        tick.get("mid")
                    )

                    if bid is not None and ask is not None:

                        return (
                            bid + ask
                        ) / 2.0

                    if bid is not None:
                        return bid

                    if ask is not None:
                        return ask

                    if last is not None:
                        return last

                    if mid is not None:
                        return mid

            except Exception:

                logger.debug(
                    "Live-price method failed: %s",
                    method_name,
                    exc_info=True,
                )

        return None

    # =========================================================
    # TECHNICAL ANALYSIS - ASYNC COMPATIBLE
    # =========================================================

    async def _analyse_timeframe(
        self,
        symbol,
        timeframe,
        candles,
    ):

        engine = self.technical_analysis_engine

        if engine is None:

            raise RuntimeError(
                "Technical Analysis Engine unavailable"
            )

        if not candles:

            return {
                "status": "NO_DATA",
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": 0,
            }

        method = getattr(
            engine,
            "analyze",
            None,
        )

        if not callable(method):

            method = getattr(
                engine,
                "analyse",
                None,
            )

        if not callable(method):

            raise RuntimeError(
                "Technical Analysis method unavailable"
            )

        try:

            supports_kwargs = (
                self._supports_keyword(
                    method,
                    "symbol",
                )
                and self._supports_keyword(
                    method,
                    "timeframe",
                )
            )

            if supports_kwargs:

                result = await self._invoke(
                    method,
                    candles,
                    symbol=symbol,
                    timeframe=timeframe,
                )

            else:

                result = await self._invoke(
                    method,
                    candles,
                )

        except TypeError:

            result = await self._invoke(
                method,
                candles,
            )

        if not isinstance(result, dict):

            raise RuntimeError(
                "Technical Analysis returned invalid result"
            )

        result.setdefault("symbol", symbol)
        result.setdefault("timeframe", timeframe)
        result.setdefault("candles", len(candles))
        result.setdefault("status", "ANALYZED")

        return result

    # =========================================================
    # MARKET DATA COLLECTION - ASYNC
    # =========================================================

    async def _collect_market_data(self, symbol):

        result = {}

        for timeframe in self.TIMEFRAMES:

            if self._stop_event.is_set():
                break

            try:

                candles = await self._get_candles(
                    symbol,
                    timeframe,
                    self.CANDLE_COUNT,
                )

            except Exception as exc:

                logger.error(
                    "%s | %s | Candle retrieval failed: %s",
                    symbol,
                    timeframe,
                    exc,
                    exc_info=True,
                )

                result[timeframe] = {
                    "candles": [],
                    "technical": {
                        "status": "CANDLE_RETRIEVAL_ERROR",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "candles": 0,
                        "error": str(exc),
                    },
                }

                continue

            candle_count = len(candles)

            logger.info(
                "%s | %s | Candle retrieval successful | Count=%s",
                symbol,
                timeframe,
                candle_count,
            )

            if candle_count < 50:

                logger.warning(
                    "%s | %s | Insufficient candles: %s",
                    symbol,
                    timeframe,
                    candle_count,
                )

                result[timeframe] = {
                    "candles": candles,
                    "technical": {
                        "status": "INSUFFICIENT_DATA",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "candles": candle_count,
                    },
                }

                continue

            try:

                technical = await self._analyse_timeframe(
                    symbol,
                    timeframe,
                    candles,
                )

            except Exception as exc:

                logger.error(
                    "%s | %s | Technical analysis failed: %s",
                    symbol,
                    timeframe,
                    exc,
                    exc_info=True,
                )

                technical = {
                    "status": "TECHNICAL_ANALYSIS_ERROR",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "candles": candle_count,
                    "error": str(exc),
                }

            result[timeframe] = {
                "candles": candles,
                "technical": technical,
            }

        return result

    # =========================================================
    # EVIDENCE COLLECTION
    # =========================================================

    def _extract_entry_evidence(self, market_data):

        m1 = market_data.get("M1", {})

        technical = self._safe_dict(
            m1.get("technical")
        )

        candidates = (
            technical.get("entry_models"),
            technical.get("entry_evidence"),
            technical.get("confirmed_entry_models"),
            technical.get("signals"),
        )

        for candidate in candidates:

            if candidate:
                return candidate

        return None

    def _extract_poi_evidence(self, market_data):

        evidence = {}

        for timeframe in self.TIMEFRAMES:

            tf_data = market_data.get(
                timeframe,
                {},
            )

            technical = self._safe_dict(
                tf_data.get("technical")
            )

            candidates = (
                technical.get("poi_evidence"),
                technical.get("points_of_interest"),
                technical.get("order_blocks"),
                technical.get("ob_candidates"),
                technical.get("fvg"),
                technical.get("fvgs"),
                technical.get("fair_value_gaps"),
            )

            found = []

            for candidate in candidates:

                if candidate:

                    if isinstance(candidate, list):
                        found.extend(candidate)

                    elif isinstance(candidate, dict):
                        found.append(candidate)

            evidence[timeframe] = found

        if not any(evidence.values()):
            return None

        return evidence

    def _extract_displacement_evidence(
        self,
        market_data,
    ):

        evidence = {}

        for timeframe in self.TIMEFRAMES:

            technical = self._safe_dict(
                market_data.get(
                    timeframe,
                    {},
                ).get("technical")
            )

            displacement = technical.get(
                "displacement",
                technical.get(
                    "displacement_evidence"
                ),
            )

            if displacement:
                evidence[timeframe] = displacement

        return evidence or None

    def _extract_fvg_evidence(self, market_data):

        evidence = {}

        for timeframe in self.TIMEFRAMES:

            technical = self._safe_dict(
                market_data.get(
                    timeframe,
                    {},
                ).get("technical")
            )

            fvg = technical.get(
                "fvg",
                technical.get(
                    "fvgs",
                    technical.get(
                        "fair_value_gaps"
                    ),
                ),
            )

            if fvg:
                evidence[timeframe] = fvg

        return evidence or None

    # =========================================================
    # FUNDAMENTAL ENGINE - ASYNC COMPATIBLE
    # =========================================================

    async def _collect_fundamentals(
        self,
        symbol,
        market_data,
        current_price,
    ):

        engine = self.fundamental_analysis_engine

        if engine is None:

            return {
                "status": "FUNDAMENTAL_ENGINE_UNAVAILABLE",
                "available": False,
                "symbol": symbol,
                "data": None,
            }

        method = None
        method_name = None

        for name in (
            "analyze_instrument",
            "analyse_instrument",
            "analyze",
            "analyse",
        ):

            candidate = getattr(
                engine,
                name,
                None,
            )

            if callable(candidate):

                method = candidate
                method_name = name
                break

        if method is None:

            return {
                "status": "FUNDAMENTAL_METHOD_UNAVAILABLE",
                "available": False,
                "symbol": symbol,
                "data": None,
            }

        try:

            try:

                result = await self._invoke(
                    method,
                    symbol=symbol,
                    market_data=market_data,
                    current_price=current_price,
                )

            except TypeError:

                try:

                    result = await self._invoke(
                        method,
                        symbol,
                        market_data=market_data,
                        current_price=current_price,
                    )

                except TypeError:

                    try:

                        result = await self._invoke(
                            method,
                            symbol,
                        )

                    except TypeError:

                        result = await self._invoke(
                            method,
                            instrument=symbol,
                        )

            if isinstance(result, dict):

                return {
                    "status": result.get(
                        "status",
                        "ANALYZED",
                    ),
                    "available": True,
                    "symbol": symbol,
                    "data": result,
                    "engine_method": method_name,
                }

            if result is not None:

                return {
                    "status": "ANALYZED",
                    "available": True,
                    "symbol": symbol,
                    "data": result,
                    "engine_method": method_name,
                }

            return {
                "status": "NO_FUNDAMENTAL_RESULT",
                "available": False,
                "symbol": symbol,
                "data": None,
            }

        except Exception as exc:

            logger.error(
                "%s | Fundamental analysis failed: %s",
                symbol,
                exc,
                exc_info=True,
            )

            return {
                "status": "FUNDAMENTAL_ANALYSIS_ERROR",
                "available": False,
                "symbol": symbol,
                "error": str(exc),
                "data": None,
            }

    # =========================================================
    # RISK MANAGEMENT ENGINE - ASYNC COMPATIBLE
    # =========================================================

    async def _collect_risk_checks(
        self,
        symbol,
        market_data,
        current_price,
    ):

        engine = self.risk_management_engine

        if engine is None:

            return {
                "status": "RISK_ENGINE_UNAVAILABLE",
                "available": False,
                "checks": None,
            }

        method = None
        method_name = None

        possible_methods = (
            "check_trade",
            "validate_trade",
            "validate_risk",
            "check_risk",
            "analyze_risk",
            "analyse_risk",
            "get_risk_checks",
        )

        for name in possible_methods:

            candidate = getattr(
                engine,
                name,
                None,
            )

            if callable(candidate):

                method = candidate
                method_name = name
                break

        if method is None:

            return {
                "status": "RISK_METHOD_UNAVAILABLE",
                "available": False,
                "checks": None,
            }

        try:

            try:

                result = await self._invoke(
                    method,
                    symbol=symbol,
                    market_data=market_data,
                    current_price=current_price,
                )

            except TypeError:

                try:

                    result = await self._invoke(
                        method,
                        symbol,
                        market_data=market_data,
                        current_price=current_price,
                    )

                except TypeError:

                    try:

                        result = await self._invoke(
                            method,
                            symbol,
                            current_price,
                        )

                    except TypeError:

                        result = await self._invoke(
                            method,
                            symbol,
                        )

            if isinstance(result, dict):

                return {
                    "status": result.get(
                        "status",
                        "CHECKS_RETURNED",
                    ),
                    "available": True,
                    "checks": result,
                    "engine_method": method_name,
                }

            return {
                "status": "INVALID_RISK_RESULT",
                "available": False,
                "checks": None,
            }

        except Exception as exc:

            logger.error(
                "%s | Risk validation failed: %s",
                symbol,
                exc,
                exc_info=True,
            )

            return {
                "status": "RISK_VALIDATION_ERROR",
                "available": False,
                "error": str(exc),
                "checks": None,
            }

    # =========================================================
    # MASTER SMC ANALYSIS - ASYNC COMPATIBLE
    # =========================================================

    async def _run_smc_analysis(
        self,
        symbol,
        market_data,
        current_price,
        fundamentals,
        risk_checks,
    ):

        engine = self.smc_engine

        if engine is None:

            return {
                "status": "SMC_ENGINE_UNAVAILABLE",
                "a_plus": False,
                "execution_authorized": False,
            }

        method = getattr(
            engine,
            "analyse",
            None,
        )

        if not callable(method):

            method = getattr(
                engine,
                "analyze",
                None,
            )

        if not callable(method):

            return {
                "status": "SMC_METHOD_UNAVAILABLE",
                "a_plus": False,
                "execution_authorized": False,
            }

        arguments = {
            "market_data": market_data,
            "current_price": current_price,
            "entry_evidence": self._extract_entry_evidence(
                market_data
            ),
            "poi_evidence": self._extract_poi_evidence(
                market_data
            ),
            "displacement_evidence": (
                self._extract_displacement_evidence(
                    market_data
                )
            ),
            "fvg_evidence": self._extract_fvg_evidence(
                market_data
            ),
            "risk_checks": risk_checks,
            "category_scores": None,
            "fundamentals": fundamentals,
        }

        try:

            decision = await self._invoke(
                method,
                **arguments,
            )

            if not isinstance(decision, dict):

                return {
                    "status": "INVALID_SMC_RESPONSE",
                    "a_plus": False,
                    "execution_authorized": False,
                }

            return decision

        except Exception as exc:

            logger.error(
                "%s | SMC analysis failed: %s",
                symbol,
                exc,
                exc_info=True,
            )

            return {
                "status": "SMC_ANALYSIS_ERROR",
                "error": str(exc),
                "a_plus": False,
                "execution_authorized": False,
            }

    # =========================================================
    # SCAN ONE INSTRUMENT - ASYNC
    # =========================================================

    async def scan_instrument(self, symbol):

        if symbol not in self.INSTRUMENTS:

            raise ValueError(
                "Instrument not approved for V1: "
                + str(symbol)
            )

        scan_started = time.time()

        logger.info(
            "Scanning %s",
            symbol,
        )

        try:

            current_price = await self._get_live_price(
                symbol
            )

            market_data = await self._collect_market_data(
                symbol
            )

            valid_timeframes = []

            for timeframe in self.TIMEFRAMES:

                tf_data = market_data.get(
                    timeframe,
                    {},
                )

                candles = tf_data.get(
                    "candles",
                    [],
                )

                technical = self._safe_dict(
                    tf_data.get("technical")
                )

                invalid_statuses = (
                    "INSUFFICIENT_DATA",
                    "NO_DATA",
                    "ERROR",
                    "FAILED",
                    "CANDLE_RETRIEVAL_ERROR",
                    "TECHNICAL_ANALYSIS_ERROR",
                )

                if (
                    len(candles) >= 50
                    and technical.get("status")
                    not in invalid_statuses
                ):

                    valid_timeframes.append(
                        timeframe
                    )

            if len(valid_timeframes) != 3:

                result = {
                    "symbol": symbol,
                    "status": "INSUFFICIENT_MARKET_DATA",
                    "timestamp": self._utc_now(),
                    "scan_duration": (
                        time.time() - scan_started
                    ),
                    "current_price": current_price,
                    "valid_timeframes": valid_timeframes,
                    "market_data": market_data,
                    "setup_found": False,
                    "a_plus": False,
                    "execution_authorized": False,
                }

                self._update_instrument_state(
                    symbol,
                    result,
                )

                return result

            if current_price is None:

                result = {
                    "symbol": symbol,
                    "status": "LIVE_PRICE_UNAVAILABLE",
                    "timestamp": self._utc_now(),
                    "scan_duration": (
                        time.time() - scan_started
                    ),
                    "market_data": market_data,
                    "setup_found": False,
                    "a_plus": False,
                    "execution_authorized": False,
                }

                self._update_instrument_state(
                    symbol,
                    result,
                )

                return result

            # Fundamental analysis

            fundamentals = await self._collect_fundamentals(
                symbol,
                market_data,
                current_price,
            )

            # Actual risk engine validation

            risk_checks = await self._collect_risk_checks(
                symbol,
                market_data,
                current_price,
            )

            # Master SMC engine

            decision = await self._run_smc_analysis(
                symbol,
                market_data,
                current_price,
                fundamentals,
                risk_checks,
            )

            status = decision.get(
                "status",
                "UNKNOWN",
            )

            a_plus = (
                status == "A_PLUS_SETUP"
                and decision.get("a_plus") is True
            )

            execution_authorized = (
                decision.get(
                    "execution_authorized",
                    False,
                )
                is True
            )

            result = {
                "symbol": symbol,
                "status": status,
                "timestamp": self._utc_now(),
                "scan_duration": (
                    time.time() - scan_started
                ),
                "current_price": current_price,
                "market_data": market_data,

                # Fundamental evidence
                "fundamentals": fundamentals,

                # Risk evidence
                "risk_checks": risk_checks,

                # SMC decision
                "smc_decision": decision,

                "setup_found": a_plus,
                "a_plus": a_plus,

                "a_plus_score": decision.get(
                    "a_plus_score",
                    decision.get(
                        "score",
                        0,
                    ),
                ),

                "setup_direction": decision.get(
                    "direction"
                ),

                "setup_type": decision.get(
                    "pathway",
                    decision.get(
                        "setup_type"
                    ),
                ),

                "execution_authorized": (
                    execution_authorized
                ),

                # Pass-through only; scanner does not execute.
                "execution_payload": decision.get(
                    "execution_payload"
                ),
            }

            self._update_instrument_state(
                symbol,
                result,
            )

            if a_plus:

                logger.warning(
                    "A+ SETUP | %s | Direction=%s "
                    "| Pathway=%s | Score=%s "
                    "| ExecutionAuthorized=%s",
                    symbol,
                    result["setup_direction"],
                    result["setup_type"],
                    result["a_plus_score"],
                    execution_authorized,
                )

            else:

                logger.info(
                    "%s | Status=%s | No A+ setup",
                    symbol,
                    status,
                )

            return result

        except asyncio.CancelledError:

            raise

        except Exception as exc:

            self.error_count += 1

            logger.error(
                "Scan failed for %s: %s",
                symbol,
                exc,
                exc_info=True,
            )

            result = {
                "symbol": symbol,
                "status": "SCAN_ERROR",
                "timestamp": self._utc_now(),
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "setup_found": False,
                "a_plus": False,
                "execution_authorized": False,
            }

            self._update_instrument_state(
                symbol,
                result,
            )

            return result

    # =========================================================
    # STATE MANAGEMENT
    # =========================================================

    def _update_instrument_state(
        self,
        symbol,
        result,
    ):

        with self._lock:

            fundamentals = self._safe_dict(
                result.get("fundamentals")
            )

            risk = self._safe_dict(
                result.get("risk_checks")
            )

            self.instrument_states[symbol].update(
                {
                    "status": result.get("status"),
                    "last_scan": result.get("timestamp"),
                    "last_price": result.get("current_price"),
                    "last_error": result.get("error"),
                    "setup_found": result.get("setup_found", False),
                    "setup_direction": result.get("setup_direction"),
                    "setup_type": result.get("setup_type"),
                    "a_plus_score": result.get("a_plus_score", 0),
                    "execution_authorized": result.get(
                        "execution_authorized",
                        False,
                    ),
                    "fundamental_status": fundamentals.get(
                        "status",
                        "NOT_ANALYZED",
                    ),
                    "risk_status": risk.get(
                        "status",
                        "NOT_ANALYZED",
                    ),
                }
            )

            self.last_scan_results[symbol] = result

    # =========================================================
    # SCAN ALL INSTRUMENTS - ASYNC
    # =========================================================

    async def scan_all(self):

        scan_started = time.time()

        results = {}

        logger.info(
            "Starting Vrotex V1 full scan"
        )

        # Sequential scanning preserves phone/runtime resources.
        # Candle requests are now properly awaited.

        for symbol in self.INSTRUMENTS:

            if self._stop_event.is_set():
                break

            results[symbol] = await self.scan_instrument(
                symbol
            )

        with self._lock:

            self.scan_count += 1

            self.last_scan_time = self._utc_now()

        duration = time.time() - scan_started

        logger.info(
            "Full scan completed | "
            "Instruments=%s | Duration=%.2fs",
            len(results),
            duration,
        )

        return {
            "timestamp": self._utc_now(),
            "scan_number": self.scan_count,
            "duration": duration,
            "instruments_scanned": len(results),
            "results": results,
        }

    # =========================================================
    # CONTINUOUS SCANNER - ASYNC
    # =========================================================

    async def run(self):

        if self.running:

            logger.warning(
                "Scanner is already running"
            )

            return

        self.running = True

        self._stop_event.clear()

        logger.info(
            "Market Scanner started | "
            "Interval=%ss",
            self.scan_interval,
        )

        try:

            while not self._stop_event.is_set():

                scan_started = time.time()

                try:

                    # IMPORTANT:
                    # No asyncio.to_thread(scan_all).
                    #
                    # scan_all is async and candle retrieval
                    # must remain on the current event loop.

                    await self.scan_all()

                except asyncio.CancelledError:

                    raise

                except Exception:

                    self.error_count += 1

                    logger.error(
                        "Full scan cycle failed",
                        exc_info=True,
                    )

                elapsed = (
                    time.time() - scan_started
                )

                remaining = max(
                    0,
                    self.scan_interval - elapsed,
                )

                if remaining > 0:

                    try:

                        await asyncio.wait_for(
                            asyncio.to_thread(
                                self._stop_event.wait
                            ),
                            timeout=remaining,
                        )

                    except asyncio.TimeoutError:

                        pass

        finally:

            self.running = False

            logger.info(
                "Market Scanner stopped"
            )

    # =========================================================
    # STOP
    # =========================================================

    async def stop(self):

        logger.info(
            "Stopping Market Scanner"
        )

        self._stop_event.set()

        self.running = False

    # =========================================================
    # STATUS
    # =========================================================

    def get_status(self):

        with self._lock:

            return {
                "version": self.VERSION,
                "running": self.running,
                "scan_interval": self.scan_interval,
                "instruments": self.INSTRUMENTS,
                "timeframes": self.TIMEFRAMES,
                "scan_count": self.scan_count,
                "error_count": self.error_count,
                "last_scan_time": self.last_scan_time,
                "instrument_states": {
                    symbol: state.copy()
                    for symbol, state
                    in self.instrument_states.items()
                },
            }

    # =========================================================
    # LAST RESULTS
    # =========================================================

    def get_last_scan_results(self):

        with self._lock:

            return {
                symbol: result.copy()
                for symbol, result
                in self.last_scan_results.items()
            }


# =============================================================
# SINGLETON — PRESERVE EXISTING ENGINE INTERFACE
# =============================================================

market_scanner = MarketScanner()

# Existing engine.py requires:
#     from scanner import scanner

scanner = market_scanner
