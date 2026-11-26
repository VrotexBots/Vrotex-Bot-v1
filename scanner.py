
"""
Vrotex Bot V1
Market Scanner V3.5
Autonomous Strategy Recognition Integration

H1 -> M5 -> M1
EURUSD, GBPUSD, BTCUSD

Recognizes:
- technical_analysis_pro_trend.py
- technical_analysis_counter_trend.py

Responsibilities:
- Collect market candles and live prices.
- Run both strategy engines independently.
- Preserve strategy evidence.
- Collect fundamental and risk information.
- Prepare evidence for the Master SMC Engine.
- Preserve Master SMC authorization.

This scanner does not independently authorize or execute trades.
"""

import asyncio
import inspect
import logging
import threading
import time
import math
import re

from datetime import datetime, timezone

logger = logging.getLogger("vrotex.market_scanner")


class MarketScanner:

    VERSION = "3.5"

    INSTRUMENTS = ("EURUSD", "GBPUSD", "BTCUSD")
    TIMEFRAMES = ("H1", "M5", "M1")

    CATEGORIES = (
        "structure",
        "poi",
        "liquidity",
        "entry_models",
        "timeframe_alignment",
        "fundamentals",
        "trade_quality_risk",
    )

    CANDLE_COUNT = 1000
    SCAN_INTERVAL = 30

    def __init__(
        self,
        market_data_engine=None,
        pro_trend_engine=None,
        counter_trend_engine=None,
        fundamental_analysis_engine=None,
        risk_management_engine=None,
        smc_engine=None,
        scan_interval=None,
    ):

        self.market_data_engine = market_data_engine
        self.pro_trend_engine = pro_trend_engine
        self.counter_trend_engine = counter_trend_engine

        self.fundamental_analysis_engine = (
            fundamental_analysis_engine
        )

        self.risk_management_engine = (
            risk_management_engine
        )

        self.smc_engine = smc_engine

        self.scan_interval = (
            scan_interval or self.SCAN_INTERVAL
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
                "category_scores": {},
                "execution_authorized": False,
                "pro_trend_status": "NOT_ANALYZED",
                "counter_trend_status": "NOT_ANALYZED",
            }
            for symbol in self.INSTRUMENTS
        }

        self._initialize_engines()

        logger.info(
            "Scanner V%s initialized | Symbols=%s | TF=%s",
            self.VERSION,
            self.INSTRUMENTS,
            self.TIMEFRAMES,
        )

    # =====================================================
    # GENERAL HELPERS
    # =====================================================

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _dict(value):
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _list(value):
        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        return []

    @staticmethod
    def _number(value, default=None):

        try:
            result = float(value)

            if math.isfinite(result):
                return result

        except (TypeError, ValueError, OverflowError):
            pass

        return default

    @staticmethod
    def _has(value):

        if value is None:
            return False

        if isinstance(value, (dict, list, tuple)):
            return len(value) > 0

        return bool(value)

    @staticmethod
    async def _invoke(method, *args, **kwargs):

        if inspect.iscoroutinefunction(method):
            return await method(*args, **kwargs)

        result = await asyncio.to_thread(
            method,
            *args,
            **kwargs,
        )

        if inspect.isawaitable(result):
            return await result

        return result

    @staticmethod
    def _filter_kwargs(method, kwargs):

        try:
            signature = inspect.signature(method)

            if any(
                parameter.kind
                == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                return kwargs

            return {
                key: value
                for key, value in kwargs.items()
                if key in signature.parameters
            }

        except (TypeError, ValueError):
            return kwargs

    @staticmethod
    def _load_engine(module_name, names):

        try:
            module = __import__(
                module_name,
                fromlist=list(names),
            )

            for name in names:

                obj = getattr(module, name, None)

                if obj is not None:
                    return obj

        except Exception as exc:

            logger.warning(
                "Engine import failed | %s | %s",
                module_name,
                exc,
            )

        return None

    # =====================================================
    # ENGINE INITIALIZATION
    # =====================================================

    def _initialize_engines(self):

        if self.market_data_engine is None:

            self.market_data_engine = self._load_engine(
                "market_data_engine",
                ("market_data_engine",),
            )

        if self.pro_trend_engine is None:

            self.pro_trend_engine = self._load_engine(
                "technical_analysis_pro_trend",
                (
                    "pro_trend_strategy",
                    "technical_analysis_pro_trend",
                ),
            )

        if self.counter_trend_engine is None:

            self.counter_trend_engine = self._load_engine(
                "technical_analysis_counter_trend",
                (
                    "technical_analysis_counter_trend",
                    "TechnicalAnalysisCounterTrend",
                ),
            )

            if inspect.isclass(self.counter_trend_engine):

                self.counter_trend_engine = (
                    self.counter_trend_engine()
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

            self.risk_management_engine = self._load_engine(
                "risk_manager",
                (
                    "risk_manager",
                    "risk_management_engine",
                ),
            )

        if self.smc_engine is None:

            self.smc_engine = self._load_engine(
                "smc_engine",
                (
                    "smc_engine",
                    "master_smc_engine",
                ),
            )

        logger.info(
            "Strategy initialization | "
            "Pro-Trend=%s | Counter-Trend=%s | "
            "MarketData=%s | MasterSMC=%s",
            self.pro_trend_engine is not None,
            self.counter_trend_engine is not None,
            self.market_data_engine is not None,
            self.smc_engine is not None,
        )

    # =====================================================
    # MARKET DATA
    # =====================================================

    async def _get_candles(self, symbol, timeframe):

        engine = self.market_data_engine

        if engine is None:
            raise RuntimeError(
                "Market data engine unavailable"
            )

        method = getattr(
            engine,
            "get_recent_candles",
            None,
        )

        if not callable(method):
            raise RuntimeError(
                "get_recent_candles method unavailable"
            )

        kwargs = self._filter_kwargs(
            method,
            {"price_type": "bid"},
        )

        candles = await self._invoke(
            method,
            symbol,
            timeframe,
            self.CANDLE_COUNT,
            **kwargs,
        )

        if isinstance(candles, dict):

            candles = candles.get(
                "candles",
                candles.get("data", []),
            )

        return self._list(candles)

    async def _get_live_price(self, symbol):

        engine = self.market_data_engine

        if engine is None:
            return None

        for name in (
            "get_live_tick",
            "get_latest_tick",
            "get_tick",
            "get_current_price",
        ):

            method = getattr(engine, name, None)

            if not callable(method):
                continue

            try:

                tick = await self._invoke(
                    method,
                    symbol,
                )

                if isinstance(tick, (int, float)):
                    return self._number(tick)

                if isinstance(tick, dict):

                    bid = self._number(tick.get("bid"))
                    ask = self._number(tick.get("ask"))

                    if bid is not None and ask is not None:
                        return (bid + ask) / 2

                    for key in (
                        "price",
                        "last",
                        "mid",
                        "close",
                    ):

                        value = self._number(
                            tick.get(key)
                        )

                        if value is not None:
                            return value

            except Exception:

                logger.debug(
                    "Price method failed: %s",
                    name,
                    exc_info=True,
                )

        return None

    async def _collect_market_data(self, symbol):

        data = {}

        # Sequential candle collection preserves phone resources.
        for timeframe in self.TIMEFRAMES:

            if self._stop_event.is_set():
                break

            try:

                candles = await self._get_candles(
                    symbol,
                    timeframe,
                )

                if len(candles) < 50:

                    data[timeframe] = {
                        "candles": candles,
                        "technical": {
                            "success": False,
                            "status": "INSUFFICIENT_DATA",
                            "candles_analyzed": len(candles),
                            "timeframe": timeframe,
                            "symbol": symbol,
                        },
                    }

                    logger.warning(
                        "%s | %s | Insufficient candles=%s",
                        symbol,
                        timeframe,
                        len(candles),
                    )

                    continue

                data[timeframe] = {
                    "candles": candles,
                    "technical": {
                        "success": True,
                        "status": "RAW_CANDLES_COLLECTED",
                        "candles_analyzed": len(candles),
                        "timeframe": timeframe,
                        "symbol": symbol,
                    },
                }

                logger.info(
                    "%s | %s | Candles collected=%s",
                    symbol,
                    timeframe,
                    len(candles),
                )

            except Exception as exc:

                logger.exception(
                    "%s | %s | Candle collection failed",
                    symbol,
                    timeframe,
                )

                data[timeframe] = {
                    "candles": [],
                    "technical": {
                        "success": False,
                        "status": "ERROR",
                        "error": str(exc),
                        "symbol": symbol,
                        "timeframe": timeframe,
                    },
                }

        return data

    # =====================================================
    # STRATEGY INVOCATION
    # =====================================================

    async def _run_pro_trend(self, market_data, symbol):

        engine = self.pro_trend_engine

        if engine is None:

            return {
                "available": False,
                "status": "PRO_TREND_UNAVAILABLE",
            }

        method = getattr(engine, "analyze", None)

        if not callable(method):

            method = getattr(
                engine,
                "analyze_pro_trend",
                None,
            )

        if not callable(method):

            return {
                "available": False,
                "status": "PRO_TREND_METHOD_UNAVAILABLE",
            }

        h1 = market_data["H1"]["candles"]
        m5 = market_data["M5"]["candles"]
        m1 = market_data["M1"]["candles"]

        kwargs = self._filter_kwargs(
            method,
            {
                "symbol": symbol,
            },
        )

        try:

            result = await self._invoke(
                method,
                h1,
                m5,
                m1,
                **kwargs,
            )

            if not isinstance(result, dict):
                raise RuntimeError(
                    "Invalid Pro-Trend response"
                )

            logger.info(
                "%s | Pro-Trend analysis completed",
                symbol,
            )

            return {
                "available": True,
                "status": "ANALYZED",
                "result": result,
            }

        except Exception as exc:

            logger.exception(
                "%s | Pro-Trend analysis failed",
                symbol,
            )

            return {
                "available": False,
                "status": "PRO_TREND_ERROR",
                "error": str(exc),
            }

    async def _run_counter_trend(
        self,
        market_data,
        symbol,
    ):

        engine = self.counter_trend_engine

        if engine is None:

            return {
                "available": False,
                "status": "COUNTER_TREND_UNAVAILABLE",
            }

        method = getattr(engine, "analyze", None)

        if not callable(method):

            method = getattr(
                engine,
                "analyze_counter_trend",
                None,
            )

        if not callable(method):

            return {
                "available": False,
                "status": "COUNTER_TREND_METHOD_UNAVAILABLE",
            }

        h1 = market_data["H1"]["candles"]
        m5 = market_data["M5"]["candles"]
        m1 = market_data["M1"]["candles"]

        values = {
            "h1_candles": h1,
            "m5_candles": m5,
            "m1_candles": m1,
            "h1": h1,
            "m5": m5,
            "m1": m1,
            "symbol": symbol,
        }

        try:

            signature = inspect.signature(method)

            parameters = signature.parameters

            accepts_kwargs = any(
                parameter.kind
                == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )

            if accepts_kwargs:

                kwargs = {
                    "h1_candles": h1,
                    "m5_candles": m5,
                    "m1_candles": m1,
                    "symbol": symbol,
                }

                result = await self._invoke(
                    method,
                    **kwargs,
                )

            else:

                kwargs = {
                    name: values[name]
                    for name in parameters
                    if name in values
                }

                required = [
                    parameter
                    for parameter in parameters.values()
                    if (
                        parameter.default
                        is inspect.Parameter.empty
                        and parameter.kind
                        in (
                            inspect.Parameter.POSITIONAL_ONLY,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        )
                    )
                ]

                if all(
                    parameter.name in kwargs
                    for parameter in required
                ):

                    result = await self._invoke(
                        method,
                        **kwargs,
                    )

                else:

                    # Compatibility with a three-positional-candle
                    # analyze(h1, m5, m1) interface.
                    positional = [
                        parameter
                        for parameter in parameters.values()
                        if parameter.kind
                        in (
                            inspect.Parameter.POSITIONAL_ONLY,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        )
                    ]

                    if len(positional) < 3:
                        raise RuntimeError(
                            "Counter-Trend method signature "
                            "does not accept H1/M5/M1 candles"
                        )

                    result = await self._invoke(
                        method,
                        h1,
                        m5,
                        m1,
                    )

            if not isinstance(result, dict):
                raise RuntimeError(
                    "Invalid Counter-Trend response"
                )

            logger.info(
                "%s | Counter-Trend analysis completed",
                symbol,
            )

            return {
                "available": True,
                "status": "ANALYZED",
                "result": result,
            }

        except Exception as exc:

            logger.exception(
                "%s | Counter-Trend analysis failed",
                symbol,
            )

            return {
                "available": False,
                "status": "COUNTER_TREND_ERROR",
                "error": str(exc),
            }

    async def _run_strategies(self, market_data, symbol):

        required = ("H1", "M5", "M1")

        missing = [
            timeframe
            for timeframe in required
            if (
                not isinstance(market_data.get(timeframe), dict)
                or len(
                    self._list(
                        market_data[timeframe].get("candles")
                    )
                ) < 50
            )
        ]

        if missing:

            return {
                "symbol": symbol,
                "status": "INCOMPLETE_STRATEGY_DATA",
                "missing_timeframes": missing,
                "pro_trend": {
                    "available": False,
                    "status": "INCOMPLETE_DATA",
                },
                "counter_trend": {
                    "available": False,
                    "status": "INCOMPLETE_DATA",
                },
                "both_strategies_available": False,
                "evidence_only": True,
            }

        # Both strategies receive the same market data.
        # They run independently and cannot authorize execution.
        pro_result, counter_result = await asyncio.gather(
            self._run_pro_trend(
                market_data,
                symbol,
            ),
            self._run_counter_trend(
                market_data,
                symbol,
            ),
        )

        result = {
            "symbol": symbol,
            "status": "ANALYZED",
            "pro_trend": pro_result,
            "counter_trend": counter_result,
            "both_strategies_available": (
                pro_result.get("available") is True
                and counter_result.get("available") is True
            ),
            "evidence_only": True,
        }

        logger.info(
            "%s | Strategy cycle | Pro=%s | Counter=%s",
            symbol,
            pro_result.get("status"),
            counter_result.get("status"),
        )

        return result

    # =====================================================
    # TECHNICAL EVIDENCE COMPATIBILITY
    # =====================================================

    def _ta(self, market_data, timeframe):

        return self._dict(
            self._dict(
                market_data.get(timeframe)
            ).get("technical")
        )

    def _structure_evidence(self, market_data):

        output = {}

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            structure = ta.get("structure", {})
            swings = ta.get("swings", {})

            output[timeframe] = {
                "bias": ta.get("bias"),
                "direction": ta.get("direction"),
                "structure": structure,
                "swings": swings,
                "breaks": self._list(
                    ta.get("breaks")
                ),
                "latest_swing_high": self._dict(
                    structure
                ).get("latest_swing_high"),
                "latest_swing_low": self._dict(
                    structure
                ).get("latest_swing_low"),
            }

        return output

    def _poi_evidence(self, market_data):

        output = {}

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            output[timeframe] = {
                "fvgs": self._list(
                    ta.get(
                        "fvgs",
                        ta.get("fair_value_gaps", []),
                    )
                ),
                "order_blocks": self._list(
                    ta.get(
                        "clean_order_blocks",
                        ta.get(
                            "order_block_candidates",
                            [],
                        ),
                    )
                ),
                "premium_discount": ta.get(
                    "premium_discount"
                ),
                "support_resistance": ta.get(
                    "support_resistance"
                ),
            }

        return output

    def _liquidity_evidence(self, market_data):

        output = {}

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            output[timeframe] = {
                "sweeps": self._list(
                    ta.get("liquidity_sweeps")
                ),
                "equal_highs": self._list(
                    ta.get("equal_highs")
                ),
                "equal_lows": self._list(
                    ta.get("equal_lows")
                ),
                "swings": ta.get("swings"),
            }

        return output

    def _displacement_evidence(self, market_data):

        output = {}

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            displacement = ta.get(
                "displacement",
                ta.get("displacement_evidence"),
            )

            if displacement is not None:
                output[timeframe] = displacement

        return output

    def _fvg_evidence(self, market_data):

        return {
            timeframe: self._list(
                self._ta(
                    market_data,
                    timeframe,
                ).get(
                    "fvgs",
                    self._ta(
                        market_data,
                        timeframe,
                    ).get(
                        "fair_value_gaps",
                        [],
                    ),
                )
            )
            for timeframe in self.TIMEFRAMES
        }

    def _entry_evidence(self, market_data):

        ta = self._ta(
            market_data,
            "M1",
        )

        return {
            "timeframe": "M1",
            "explicit_entry_models": ta.get(
                "entry_models",
                ta.get(
                    "entry_evidence",
                    ta.get("confirmed_entry_models"),
                ),
            ),
            "structure_breaks": self._list(
                ta.get("breaks")
            ),
            "liquidity_sweeps": self._list(
                ta.get("liquidity_sweeps")
            ),
            "displacement": ta.get(
                "displacement",
                ta.get("displacement_evidence"),
            ),
            "fvgs": self._list(
                ta.get("fvgs")
            ),
            "order_blocks": self._list(
                ta.get("clean_order_blocks")
            ),
            "candle_metrics": ta.get(
                "candle_metrics"
            ),
            "momentum": ta.get("momentum"),
            "bias": ta.get("bias"),
            "direction": ta.get("direction"),
        }

    def _alignment_evidence(self, market_data):

        biases = {}
        details = {}

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            bias = str(
                ta.get("bias", "UNKNOWN")
            ).upper()

            biases[timeframe] = bias

            details[timeframe] = {
                "bias": bias,
                "direction": ta.get("direction"),
                "structure": ta.get("structure"),
                "breaks": self._list(
                    ta.get("breaks")
                ),
                "momentum": ta.get("momentum"),
                "emas": ta.get("emas"),
            }

        h1 = biases["H1"]
        m5 = biases["M5"]
        m1 = biases["M1"]

        directional = ("BULLISH", "BEARISH")

        if (
            h1 in directional
            and m5 == h1
            and m1 == h1
        ):
            state = "FULL_ALIGNMENT"

        elif (
            h1 in directional
            and m5 == h1
        ):
            state = "H1_M5_ALIGNMENT"

        elif (
            h1 in directional
            and m5 in directional
            and h1 != m5
        ):
            state = "CONFLICT"

        else:
            state = "UNCONFIRMED"

        return {
            "strategy_timeframes": self.TIMEFRAMES,
            "biases": biases,
            "H1": details["H1"],
            "M5": details["M5"],
            "M1": details["M1"],
            "alignment_state": state,
            "aligned_direction": (
                h1 if state == "FULL_ALIGNMENT" else None
            ),
            "evidence_only": True,
        }

    # =====================================================
    # TRADE QUALITY / RISK EVIDENCE
    # =====================================================

    def _trade_quality_evidence(
        self,
        market_data,
        current_price,
        risk_checks,
    ):

        technical_metrics = {}

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            technical_metrics[timeframe] = {
                "atr": ta.get("atr"),
                "rsi": ta.get("rsi"),
                "emas": ta.get("emas"),
                "momentum": ta.get("momentum"),
                "candle_metrics": ta.get(
                    "candle_metrics"
                ),
                "support_resistance": ta.get(
                    "support_resistance"
                ),
                "premium_discount": ta.get(
                    "premium_discount"
                ),
            }

        return {
            "current_price": current_price,
            "technical_metrics": technical_metrics,
            "risk_validation": risk_checks,
            "risk_engine_available": (
                self.risk_management_engine is not None
            ),
            "evidence_only": True,
        }

    # =====================================================
    # FUNDAMENTALS
    # =====================================================

    async def _collect_fundamentals(
        self,
        symbol,
        market_data,
        current_price,
    ):

        engine = self.fundamental_analysis_engine

        if engine is None:

            return {
                "available": False,
                "status": "UNAVAILABLE",
                "symbol": symbol,
            }

        method = None

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
                break

        if method is None:

            return {
                "available": False,
                "status": "METHOD_UNAVAILABLE",
                "symbol": symbol,
            }

        kwargs = self._filter_kwargs(
            method,
            {
                "symbol": symbol,
                "market_data": market_data,
                "current_price": current_price,
            },
        )

        try:

            result = await self._invoke(
                method,
                **kwargs,
            )

            if isinstance(result, dict):

                return {
                    "available": True,
                    "status": result.get(
                        "status",
                        "ANALYZED",
                    ),
                    "symbol": symbol,
                    "data": result,
                    "score": result.get("score"),
                    "category_scores": result.get(
                        "category_scores",
                        {},
                    ),
                }

            return {
                "available": False,
                "status": "INVALID_RESULT",
                "symbol": symbol,
            }

        except Exception as exc:

            logger.exception(
                "%s | Fundamental analysis error",
                symbol,
            )

            return {
                "available": False,
                "status": "ERROR",
                "symbol": symbol,
                "error": str(exc),
            }

    # =====================================================
    # RISK MANAGER
    # =====================================================

    async def _collect_risk_checks(
        self,
        symbol,
        market_data,
        current_price,
    ):

        engine = self.risk_management_engine

        if engine is None:

            return {
                "available": False,
                "status": "UNAVAILABLE",
            }

        method = None

        for name in (
            "check_trade",
            "validate_trade",
            "validate_risk",
            "check_risk",
            "analyze_risk",
            "analyse_risk",
            "get_risk_checks",
        ):

            candidate = getattr(
                engine,
                name,
                None,
            )

            if callable(candidate):
                method = candidate
                break

        if method is None:

            return {
                "available": False,
                "status": "METHOD_UNAVAILABLE",
            }

        kwargs = self._filter_kwargs(
            method,
            {
                "symbol": symbol,
                "market_data": market_data,
                "current_price": current_price,
            },
        )

        try:

            result = await self._invoke(
                method,
                **kwargs,
            )

            if isinstance(result, dict):

                return {
                    "available": True,
                    "status": result.get(
                        "status",
                        "CHECKS_RETURNED",
                    ),
                    "checks": result,
                    "category_scores": result.get(
                        "category_scores",
                        {},
                    ),
                }

            return {
                "available": False,
                "status": "INVALID_RESULT",
            }

        except Exception as exc:

            logger.exception(
                "%s | Risk manager check error",
                symbol,
            )

            return {
                "available": False,
                "status": "ERROR",
                "error": str(exc),
            }

    # =====================================================
    # CATEGORY SCORES
    # =====================================================

    def _normalize_scores(self, source):

        source = self._dict(source)

        aliases = {
            "structure": (
                "structure",
                "structure_score",
            ),
            "poi": (
                "poi",
                "poi_score",
            ),
            "liquidity": (
                "liquidity",
                "liquidity_score",
            ),
            "entry_models": (
                "entry_models",
                "entry_models_score",
                "entry_score",
            ),
            "timeframe_alignment": (
                "timeframe_alignment",
                "timeframe_alignment_score",
                "alignment_score",
            ),
            "fundamentals": (
                "fundamentals",
                "fundamental_score",
                "fundamentals_score",
            ),
            "trade_quality_risk": (
                "trade_quality_risk",
                "trade_quality_score",
                "risk_quality_score",
            ),
        }

        scores = {}

        for category, names in aliases.items():

            for name in names:

                if name not in source:
                    continue

                value = source[name]

                if isinstance(value, dict):
                    value = value.get("score")

                value = self._number(value)

                if (
                    value is not None
                    and 0 <= value <= 100
                ):
                    scores[category] = value
                    break

        return scores

    @staticmethod
    def _valid_direction(value):
        return str(value or "").upper() in ("BULLISH", "BEARISH")

    @staticmethod
    def _price_in_zone(price, zone):
        if not isinstance(zone, dict):
            return False

        price = MarketScanner._number(price)
        low = MarketScanner._number(
            zone.get("lower", zone.get("low", zone.get("bottom")))
        )
        high = MarketScanner._number(
            zone.get("upper", zone.get("high", zone.get("top")))
        )

        return (
            price is not None
            and low is not None
            and high is not None
            and low <= price <= high
        )

    @staticmethod
    def _sweep_is_confirmed(sweep):
        if not isinstance(sweep, dict):
            return False

        if sweep.get("confirmed") is True:
            return True

        level = MarketScanner._number(sweep.get("level"))
        wick = MarketScanner._number(sweep.get("wick"))
        close = MarketScanner._number(sweep.get("close"))
        side = str(sweep.get("direction", "")).upper()

        if None in (level, wick, close):
            return False

        if side in ("BULLISH", "LONG"):
            return wick < level and close > level

        if side in ("BEARISH", "SHORT"):
            return wick > level and close < level

        return False

    @staticmethod
    def _accepted_entry_model(value):
        accepted = {
            "CHOCH_FVG",
            "SWEEP_ENGULFING",
            "BREAKER",
            "MSS_SWEEP_DISPLACEMENT",
            "FLIP_S2D_D2S",
        }

        if isinstance(value, dict):
            model = re.sub(
                r"[^A-Z0-9]+", "_",
                str(value.get("model", value.get("name", ""))).upper(),
            ).strip("_")

            confirmed = (
                value.get("confirmed") is True
                or value.get("valid") is True
            )
            direction = str(value.get("direction", "")).upper()

            if (
                model in accepted
                and confirmed
                and direction in ("BULLISH", "BEARISH", "LONG", "SHORT")
            ):
                return True

            for key, item in value.items():
                normalized = re.sub(
                    r"[^A-Z0-9]+", "_", str(key).upper()
                ).strip("_")

                if normalized in accepted and isinstance(item, dict):
                    if item.get("confirmed") is True or item.get("valid") is True:
                        item_direction = str(item.get("direction", "")).upper()

                        if item_direction in (
                            "BULLISH", "BEARISH", "LONG", "SHORT"
                        ):
                            return True

                if isinstance(item, (dict, list, tuple)):
                    if MarketScanner._accepted_entry_model(item):
                        return True

            return False

        if isinstance(value, (list, tuple)):
            return any(
                MarketScanner._accepted_entry_model(item)
                for item in value
            )

        return False

    @staticmethod
    def _score_criteria(criteria):
        score = 0
        observed_count = 0
        passed_count = 0
        details = {}

        for name, points, observed, passed in criteria:
            observed = bool(observed)
            passed = bool(passed) if observed else False

            if observed:
                observed_count += 1

                if passed:
                    score += points
                    passed_count += 1

            details[name] = {
                "points": points if passed else 0,
                "maximum_points": points,
                "observed": observed,
                "passed": passed,
            }

        return {
            "score": float(score) if observed_count else None,
            "observed_criteria": observed_count,
            "passed_criteria": passed_count,
            "status": (
                "MISSING" if not observed_count
                else "VALIDATED" if score == 100
                else "PARTIAL" if score > 0
                else "OBSERVED_NO_PASS"
            ),
            "criteria": details,
        }

    
    def _extract_category_scores(
        self,
        market_data,
        fundamentals,
        risk_checks,
    ):

        collected = {
            category: []
            for category in self.CATEGORIES
        }

        # Strategy score outputs are preserved separately.
        # They are not silently converted into SMC category scores.

        for timeframe in self.TIMEFRAMES:

            ta = self._ta(
                market_data,
                timeframe,
            )

            for key in (
                "category_scores",
                "smc_category_scores",
                "scoring",
            ):

                scores = self._normalize_scores(
                    ta.get(key)
                )

                for category, score in scores.items():
                    collected[category].append(score)

        fundamental_data = self._dict(
            fundamentals.get("data")
        )

        for source in (
            fundamentals.get("category_scores"),
            fundamental_data.get("category_scores"),
        ):

            scores = self._normalize_scores(source)

            if "fundamentals" in scores:

                collected["fundamentals"].append(
                    scores["fundamentals"]
                )

        fundamental_score = self._number(
            fundamentals.get(
                "score",
                fundamental_data.get("score"),
            )
        )

        if (
            fundamental_score is not None
            and 0 <= fundamental_score <= 100
            and not collected["fundamentals"]
        ):

            collected["fundamentals"].append(
                fundamental_score
            )

        risk_data = self._dict(
            risk_checks.get("checks")
        )

        for source in (
            risk_checks.get("category_scores"),
            risk_data.get("category_scores"),
            risk_data.get("scoring"),
        ):

            scores = self._normalize_scores(source)

            if "trade_quality_risk" in scores:

                collected["trade_quality_risk"].append(
                    scores["trade_quality_risk"]
                )

        final = {}

        for category, values in collected.items():

            if values:

                final[category] = round(
                    sum(values) / len(values),
                    2,
                )

        missing = [
            category
            for category in self.CATEGORIES
            if category not in final
        ]

        return {
            "scores": final,
            "category_count": len(final),
            "required_category_count": len(
                self.CATEGORIES
            ),
            "complete": not missing,
            "missing_categories": missing,
        }

    # =====================================================
    # EVIDENCE PACKAGE
    # =====================================================

    def _build_evidence_package(
        self,
        market_data,
        current_price,
        fundamentals,
        risk_checks,
        strategy_results,
    ):

        structure = self._structure_evidence(
            market_data
        )

        poi = self._poi_evidence(
            market_data
        )

        liquidity = self._liquidity_evidence(
            market_data
        )

        displacement = self._displacement_evidence(
            market_data
        )

        fvg = self._fvg_evidence(
            market_data
        )

        entry = self._entry_evidence(
            market_data
        )

        alignment = self._alignment_evidence(
            market_data
        )

        trade_quality_risk = (
            self._trade_quality_evidence(
                market_data,
                current_price,
                risk_checks,
            )
        )

        category_evidence = {
            "structure": structure,
            "poi": poi,
            "liquidity": liquidity,
            "entry_models": entry,
            "timeframe_alignment": alignment,
            "fundamentals": fundamentals,
            "trade_quality_risk": trade_quality_risk,
        }

        present = [
            category
            for category, item in category_evidence.items()
            if self._has(item)
        ]

        missing = [
            category
            for category in self.CATEGORIES
            if category not in present
        ]

        score_report = self._extract_category_scores(
            market_data,
            fundamentals,
            risk_checks,
        )

        return {
            "structure": structure,
            "poi": poi,
            "liquidity": liquidity,
            "entry_models": entry,
            "timeframe_alignment": alignment,
            "fundamentals": fundamentals,
            "trade_quality_risk": trade_quality_risk,

            "displacement": displacement,
            "fvg": fvg,

            "risk_checks": risk_checks,
            "category_scores": score_report,

            "strategy_analysis": strategy_results,

            "evidence_report": {
                "present_categories": present,
                "missing_categories": missing,
                "category_count": len(present),
                "required_category_count": 7,
                "complete": not missing,
            },
        }

    # =====================================================
    # MASTER SMC ENGINE
    # =====================================================

    async def _run_smc(
        self,
        symbol,
        market_data,
        current_price,
        fundamentals,
        risk_checks,
        evidence,
    ):

        engine = self.smc_engine

        if engine is None:

            return {
                "status": "SMC_ENGINE_UNAVAILABLE",
                "a_plus": False,
                "execution_authorized": False,
            }

        method = None

        for name in (
            "analyse",
            "analyze",
            "evaluate",
            "evaluate_setup",
        ):

            candidate = getattr(
                engine,
                name,
                None,
            )

            if callable(candidate):
                method = candidate
                break

        if method is None:

            return {
                "status": "SMC_METHOD_UNAVAILABLE",
                "a_plus": False,
                "execution_authorized": False,
            }

        market_payload = dict(market_data)

        market_payload["symbol"] = symbol
        market_payload["current_price"] = current_price

        market_payload["smc_analysis_evidence"] = evidence

        kwargs = {
            "symbol": symbol,
            "market_data": market_payload,
            "current_price": current_price,
            "entry_evidence": evidence["entry_models"],
            "poi_evidence": evidence["poi"],
            "displacement_evidence": evidence["displacement"],
            "fvg_evidence": evidence["fvg"],
            "liquidity_evidence": evidence["liquidity"],
            "structure_evidence": evidence["structure"],
            "timeframe_alignment": evidence["timeframe_alignment"],
            "trade_quality_risk": evidence["trade_quality_risk"],
            "risk_checks": risk_checks,
            "category_scores": evidence["category_scores"],
            "fundamentals": fundamentals,
            "evidence": evidence,
        }

        filtered_kwargs = self._filter_kwargs(
            method,
            kwargs,
        )

        try:

            result = await self._invoke(
                method,
                **filtered_kwargs,
            )

        except TypeError:

            # Compatibility with positional market-data interfaces.
            result = await self._invoke(
                method,
                market_payload,
            )

        if not isinstance(result, dict):

            result = {
                "status": "INVALID_SMC_RESULT",
                "raw_result": str(result),
            }

        result.setdefault("symbol", symbol)

        result["scanner_version"] = self.VERSION

        result["scanner_category_scores"] = (
            evidence["category_scores"]
        )

        result["scanner_evidence_report"] = (
            evidence["evidence_report"]
        )

        result["scanner_evidence"] = evidence

        return result

    # =====================================================
    # SCAN ONE INSTRUMENT
    # =====================================================

    async def scan_instrument(self, symbol):

        if symbol not in self.INSTRUMENTS:

            raise ValueError(
                "Instrument is not approved for V1: "
                + str(symbol)
            )

        started = time.time()

        state = self.instrument_states[symbol]

        state["status"] = "SCANNING"
        state["last_error"] = None
        state["last_scan"] = self._now()

        try:

            current_price = await self._get_live_price(
                symbol
            )

            market_data = await self._collect_market_data(
                symbol
            )

            missing_tf = [
                timeframe
                for timeframe in self.TIMEFRAMES
                if len(
                    self._list(
                        self._dict(
                            market_data.get(timeframe)
                        ).get("candles")
                    )
                ) < 50
            ]

            if missing_tf:

                result = {
                    "symbol": symbol,
                    "status": "INCOMPLETE_MARKET_DATA",
                    "missing_timeframes": missing_tf,
                    "current_price": current_price,
                    "market_data": market_data,
                    "a_plus": False,
                    "execution_authorized": False,
                    "timestamp": self._now(),
                }

                state.update({
                    "status": result["status"],
                    "setup_found": False,
                    "execution_authorized": False,
                })

                return result

            # Run both strategies before preparing SMC evidence.
            strategy_results = await self._run_strategies(
                market_data,
                symbol,
            )

            market_data["strategy_analysis"] = (
                strategy_results
            )

            fundamentals = await self._collect_fundamentals(
                symbol,
                market_data,
                current_price,
            )

            risk_checks = await self._collect_risk_checks(
                symbol,
                market_data,
                current_price,
            )

            evidence = self._build_evidence_package(
                market_data,
                current_price,
                fundamentals,
                risk_checks,
                strategy_results,
            )

            report = evidence["category_scores"]
            evidence_report = evidence["evidence_report"]

            logger.info(
                "%s | SMC evidence prepared | "
                "Evidence=%s/7 | Scores=%s/7 | "
                "Missing scores=%s",
                symbol,
                evidence_report["category_count"],
                report["category_count"],
                report["missing_categories"],
            )

            logger.info(
                "%s | Strategy availability | Pro=%s | Counter=%s",
                symbol,
                strategy_results["pro_trend"].get("available"),
                strategy_results["counter_trend"].get("available"),
            )

            smc_result = await self._run_smc(
                symbol,
                market_data,
                current_price,
                fundamentals,
                risk_checks,
                evidence,
            )

            status = str(
                smc_result.get(
                    "status",
                    "UNKNOWN",
                )
            ).upper()

            a_plus = (
                status == "A_PLUS_SETUP"
                and smc_result.get("a_plus") is True
            )

            authorization = (
                smc_result.get(
                    "execution_authorized",
                    smc_result.get(
                        "trade_authorized",
                        False,
                    ),
                )
                is True
            )

            # Do not treat strategy readiness as SMC authorization.
            if not authorization:
                a_plus = False

            result = {
                "symbol": symbol,
                "status": status,
                "timestamp": self._now(),
                "scan_duration": round(
                    time.time() - started,
                    3,
                ),
                "current_price": current_price,
                "market_data": market_data,
                "strategy_analysis": strategy_results,
                "fundamentals": fundamentals,
                "risk_checks": risk_checks,
                "evidence": evidence,
                "category_scores": report["scores"],
                "category_score_report": report,
                "evidence_report": evidence_report,
                "smc_result": smc_result,
                "a_plus": a_plus,
                "setup_found": a_plus,
                "execution_authorized": authorization,
            }

            state.update({
                "status": status,
                "last_scan": result["timestamp"],
                "last_price": current_price,
                "setup_found": a_plus,
                "setup_direction": smc_result.get(
                    "direction"
                ),
                "setup_type": smc_result.get(
                    "pathway",
                    smc_result.get("setup_type"),
                ),
                "a_plus_score": smc_result.get(
                    "score",
                    smc_result.get("a_plus_score", 0),
                ),
                "category_scores": report["scores"],
                "evidence_complete": evidence_report[
                    "complete"
                ],
                "execution_authorized": authorization,
                "pro_trend_status": strategy_results[
                    "pro_trend"
                ].get("status"),
                "counter_trend_status": strategy_results[
                    "counter_trend"
                ].get("status"),
                "last_error": None,
            })

            if a_plus:

                logger.info(
                    "%s | A+ SETUP | Direction=%s | "
                    "Score=%s | Authorized=%s",
                    symbol,
                    smc_result.get("direction"),
                    smc_result.get("score"),
                    authorization,
                )

            else:

                logger.info(
                    "%s | Status=%s | "
                    "Pro=%s | Counter=%s | No authorized A+ setup",
                    symbol,
                    status,
                    strategy_results["pro_trend"].get("status"),
                    strategy_results["counter_trend"].get("status"),
                )

            return result

        except Exception as exc:

            self.error_count += 1

            logger.exception(
                "%s | Instrument scan failed",
                symbol,
            )

            state.update({
                "status": "SCAN_ERROR",
                "last_error": str(exc),
                "last_scan": self._now(),
                "setup_found": False,
                "execution_authorized": False,
            })

            return {
                "symbol": symbol,
                "status": "SCAN_ERROR",
                "error": str(exc),
                "timestamp": self._now(),
                "a_plus": False,
                "execution_authorized": False,
            }

    # =====================================================
    # SCAN ALL INSTRUMENTS
    # =====================================================

    async def scan_all(self):

        started = time.time()

        results = {}

        logger.info(
            "Full scan started | Instruments=%s",
            len(self.INSTRUMENTS),
        )

        # Sequential instrument scanning is retained for
        # resource protection on the phone host.
        for symbol in self.INSTRUMENTS:

            if self._stop_event.is_set():
                break

            results[symbol] = await self.scan_instrument(
                symbol
            )

        duration = round(
            time.time() - started,
            3,
        )

        self.last_scan_time = self._now()
        self.last_scan_results = results
        self.scan_count += 1

        logger.info(
            "Full scan completed | Instruments=%s | Duration=%.2fs",
            len(results),
            duration,
        )

        return results

    # =====================================================
    # CONTINUOUS SCANNER
    # =====================================================

    async def run(self):

        self.running = True
        self._stop_event.clear()

        logger.info(
            "Market Scanner V%s started | Interval=%ss",
            self.VERSION,
            self.scan_interval,
        )

        try:

            while (
                self.running
                and not self._stop_event.is_set()
            ):

                cycle_started = time.time()

                await self.scan_all()

                elapsed = time.time() - cycle_started

                wait_time = max(
                    0,
                    self.scan_interval - elapsed,
                )

                if self._stop_event.is_set():
                    break

                await asyncio.sleep(wait_time)

        except asyncio.CancelledError:

            logger.info(
                "Market Scanner cancelled"
            )

            raise

        except Exception:

            logger.exception(
                "Scanner loop failure"
            )

        finally:

            self.running = False

            logger.info(
                "Market Scanner stopped"
            )

    def stop(self):

        self.running = False
        self._stop_event.set()

        logger.info(
            "Market Scanner stop requested"
        )

    # =====================================================
    # STATUS
    # =====================================================

    def get_status(self):

        with self._lock:

            return {
                "version": self.VERSION,
                "running": self.running,
                "scan_interval": self.scan_interval,
                "instruments": list(self.INSTRUMENTS),
                "timeframes": list(self.TIMEFRAMES),
                "last_scan_time": self.last_scan_time,
                "scan_count": self.scan_count,
                "error_count": self.error_count,
                "strategy_engines": {
                    "pro_trend_available": (
                        self.pro_trend_engine is not None
                    ),
                    "counter_trend_available": (
                        self.counter_trend_engine is not None
                    ),
                },
                "instrument_states": self.instrument_states,
            }

    def get_last_scan_results(self):

        with self._lock:
            return self.last_scan_results


# =========================================================
# SHARED INSTANCE
# =========================================================

market_scanner = MarketScanner()
scanner = market_scanner
