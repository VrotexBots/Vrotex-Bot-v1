"""
Vrotex Bot V1 - Market Scanner
Version: 3.0

Approved instruments:
    EURUSD
    GBPUSD
    BTCUSD

Strategy timeframes:
    H1 -> M5 -> M1

Responsibilities:
    - Continuous instrument scanning
    - Market-data collection
    - Technical analysis on H1/M5/M1
    - Evidence collection
    - Master SMC analysis
    - Setup-state reporting

This module does NOT execute orders.
"""

import logging
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger("vrotex.market_scanner")


class MarketScanner:

    VERSION = "3.0"

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
        smc_engine=None,
        scan_interval=None,
    ):

        self.market_data_engine = market_data_engine
        self.technical_analysis_engine = technical_analysis_engine
        self.smc_engine = smc_engine

        self.scan_interval = (
            scan_interval
            or self.DEFAULT_SCAN_INTERVAL
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
    # ENGINE INITIALIZATION
    # =========================================================

    def _initialize_engines(self):

        if self.market_data_engine is None:

            try:
                from market_data_engine import market_data_engine

                self.market_data_engine = market_data_engine

            except Exception as exc:

                logger.error(
                    "Market Data Engine unavailable: %s",
                    exc,
                )

        if self.technical_analysis_engine is None:

            try:
                from technical_analysis_engine import (
                    technical_analysis_engine,
                )

                self.technical_analysis_engine = (
                    technical_analysis_engine
                )

            except Exception as exc:

                logger.error(
                    "Technical Analysis Engine unavailable: %s",
                    exc,
                )

        if self.smc_engine is None:

            try:
                from smc_engine import smc_engine

                self.smc_engine = smc_engine

            except Exception as exc:

                logger.error(
                    "Master SMC Engine unavailable: %s",
                    exc,
                )

    # =========================================================
    # GENERAL HELPERS
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

            return float(value)

        except (ValueError, TypeError):

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

    # =========================================================
    # MARKET DATA
    # =========================================================

    def _get_candles(
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

        try:

            candles = method(
                symbol,
                timeframe,
                count,
                price_type="bid",
            )

        except TypeError:

            candles = method(
                symbol,
                timeframe,
                count,
            )

        if candles is None:

            return []

        if isinstance(candles, dict):

            candles = candles.get(
                "candles",
                candles.get("data", []),
            )

        return self._safe_list(candles)

    # =========================================================
    # LIVE PRICE
    # =========================================================

    def _get_live_price(self, symbol):

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

                tick = method(symbol)

                if tick is None:
                    continue

                if isinstance(tick, (int, float)):

                    return float(tick)

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

                    if bid and ask:

                        return (bid + ask) / 2.0

                    if bid:
                        return bid

                    if ask:
                        return ask

                    if last:
                        return last

                    if mid:
                        return mid

            except Exception:

                logger.debug(
                    "Live price method failed: %s",
                    method_name,
                    exc_info=True,
                )

        return None

    # =========================================================
    # TECHNICAL ANALYSIS
    # =========================================================

    def _analyse_timeframe(
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

            result = method(
                candles,
                symbol=symbol,
                timeframe=timeframe,
            )

        except TypeError:

            result = method(candles)

        if not isinstance(result, dict):

            raise RuntimeError(
                "Technical Analysis returned invalid result"
            )

        result.setdefault(
            "symbol",
            symbol,
        )

        result.setdefault(
            "timeframe",
            timeframe,
        )

        result.setdefault(
            "candles",
            len(candles),
        )

        result.setdefault(
            "status",
            "ANALYZED",
        )

        return result

    # =========================================================
    # EVIDENCE COLLECTION
    # =========================================================

    def _collect_market_data(
        self,
        symbol,
    ):

        result = {}

        for timeframe in self.TIMEFRAMES:

            candles = self._get_candles(
                symbol,
                timeframe,
                self.CANDLE_COUNT,
            )

            if len(candles) < 50:

                logger.warning(
                    "%s | %s | Insufficient candles: %s",
                    symbol,
                    timeframe,
                    len(candles),
                )

                result[timeframe] = {
                    "candles": candles,
                    "technical": {
                        "status": "INSUFFICIENT_DATA",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "candles": len(candles),
                    },
                }

                continue

            technical = self._analyse_timeframe(
                symbol,
                timeframe,
                candles,
            )

            result[timeframe] = {
                "candles": candles,
                "technical": technical,
            }

        return result

    def _extract_entry_evidence(
        self,
        market_data,
    ):

        m1 = market_data.get(
            "M1",
            {},
        )

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

        # Do not invent entry confirmations.
        return None

    def _extract_poi_evidence(
        self,
        market_data,
    ):

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

            tf_data = market_data.get(
                timeframe,
                {},
            )

            technical = self._safe_dict(
                tf_data.get("technical")
            )

            displacement = technical.get(
                "displacement",
                technical.get(
                    "displacement_evidence"
                ),
            )

            if displacement:

                evidence[timeframe] = displacement

        if not evidence:

            return None

        return evidence

    def _extract_fvg_evidence(
        self,
        market_data,
    ):

        evidence = {}

        for timeframe in self.TIMEFRAMES:

            tf_data = market_data.get(
                timeframe,
                {},
            )

            technical = self._safe_dict(
                tf_data.get("technical")
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

        if not evidence:

            return None

        return evidence

    # =========================================================
    # RISK CHECK INPUT
    # =========================================================

    def _collect_risk_checks(
        self,
        symbol,
        market_data,
        current_price,
    ):

        # Scanner does not manufacture successful risk checks.
        # Actual risk validation must be supplied by the
        # integrated risk-management component.

        return None

    # =========================================================
    # MASTER SMC ANALYSIS
    # =========================================================

    def _run_smc_analysis(
        self,
        symbol,
        market_data,
        current_price,
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

        entry_evidence = (
            self._extract_entry_evidence(
                market_data
            )
        )

        poi_evidence = (
            self._extract_poi_evidence(
                market_data
            )
        )

        displacement_evidence = (
            self._extract_displacement_evidence(
                market_data
            )
        )

        fvg_evidence = (
            self._extract_fvg_evidence(
                market_data
            )
        )

        risk_checks = (
            self._collect_risk_checks(
                symbol,
                market_data,
                current_price,
            )
        )

        try:

            decision = method(
                market_data=market_data,
                current_price=current_price,
                entry_evidence=entry_evidence,
                poi_evidence=poi_evidence,
                displacement_evidence=(
                    displacement_evidence
                ),
                fvg_evidence=fvg_evidence,
                risk_checks=risk_checks,
                category_scores=None,
                fundamentals=None,
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
    # SCAN ONE INSTRUMENT
    # =========================================================

    def scan_instrument(
        self,
        symbol,
    ):

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

            current_price = self._get_live_price(
                symbol
            )

            market_data = (
                self._collect_market_data(
                    symbol
                )
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

                if (
                    len(candles) >= 50
                    and technical.get("status")
                    != "INSUFFICIENT_DATA"
                ):

                    valid_timeframes.append(
                        timeframe
                    )

            if len(valid_timeframes) != 3:

                result = {
                    "symbol": symbol,
                    "status": "INSUFFICIENT_MARKET_DATA",
                    "timestamp": self._utc_now(),
                    "current_price": current_price,
                    "valid_timeframes": (
                        valid_timeframes
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

            if current_price is None:

                result = {
                    "symbol": symbol,
                    "status": "LIVE_PRICE_UNAVAILABLE",
                    "timestamp": self._utc_now(),
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

            decision = self._run_smc_analysis(
                symbol,
                market_data,
                current_price,
            )

            status = decision.get(
                "status",
                "UNKNOWN",
            )

            # Master SMC setup detection.
            a_plus = (
                status == "A_PLUS_SETUP"
                and decision.get("a_plus") is True
            )

            # Authorization must be explicitly returned
            # by a verified authorization component.
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

            self.instrument_states[symbol].update(
                {
                    "status": result.get(
                        "status"
                    ),
                    "last_scan": result.get(
                        "timestamp"
                    ),
                    "last_price": result.get(
                        "current_price"
                    ),
                    "last_error": result.get(
                        "error"
                    ),
                    "setup_found": result.get(
                        "setup_found",
                        False,
                    ),
                    "setup_direction": result.get(
                        "setup_direction"
                    ),
                    "setup_type": result.get(
                        "setup_type"
                    ),
                    "a_plus_score": result.get(
                        "a_plus_score",
                        0,
                    ),
                    "execution_authorized": (
                        result.get(
                            "execution_authorized",
                            False,
                        )
                    ),
                }
            )

            self.last_scan_results[symbol] = (
                result
            )

    # =========================================================
    # SCAN ALL APPROVED INSTRUMENTS
    # =========================================================

    def scan_all(self):

        scan_started = time.time()

        results = {}

        logger.info(
            "Starting Vrotex V1 full scan"
        )

        # Sequential scanning is intentional:
        # avoids unnecessary resource pressure
        # on the phone/cloud runtime.

        for symbol in self.INSTRUMENTS:

            if self._stop_event.is_set():

                break

            results[symbol] = (
                self.scan_instrument(
                    symbol
                )
            )

        with self._lock:

            self.scan_count += 1

            self.last_scan_time = (
                self._utc_now()
            )

        duration = (
            time.time() - scan_started
        )

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
            "instruments_scanned": len(
                results
            ),
            "results": results,
        }

    # =========================================================
    # CONTINUOUS SCANNER
    # =========================================================

    def run(self):

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

                    self.scan_all()

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

                    self._stop_event.wait(
                        remaining
                    )

        finally:

            self.running = False

            logger.info(
                "Market Scanner stopped"
            )

    # =========================================================
    # STOP
    # =========================================================

    def stop(self):

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
                "scan_interval": (
                    self.scan_interval
                ),
                "instruments": (
                    self.INSTRUMENTS
                ),
                "timeframes": (
                    self.TIMEFRAMES
                ),
                "scan_count": (
                    self.scan_count
                ),
                "error_count": (
                    self.error_count
                ),
                "last_scan_time": (
                    self.last_scan_time
                ),
                "instrument_states": (
                    self.instrument_states.copy()
                ),
            }

    # =========================================================
    # LAST RESULTS
    # =========================================================

    def get_last_scan_results(self):

        with self._lock:

            return (
                self.last_scan_results.copy()
            )


# =============================================================
# SINGLETON
# =============================================================

market_scanner = MarketScanner()
