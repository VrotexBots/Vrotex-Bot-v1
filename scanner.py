"""
VROTEX BOT V1
Market Scanner

Version: 2.0

Purpose:
- Continuously scan the approved pilot instruments.
- Retrieve H1, M5 and M1 market candles.
- Run technical analysis on each timeframe.
- Obtain validated live Bid/Ask prices.
- Submit collected market data to the master SMC engine.
- Reject incomplete market data.
- Keep order execution outside this module.

Pilot:
EURUSD, GBPUSD, BTCUSD

Strategy:
H1 = External narrative
M5 = Confirmation
M1 = Entry
"""

import asyncio
import inspect
import math
from datetime import datetime, timezone
from typing import Any, Dict

from config import settings
from logging_config import get_logger

from market_data_engine import market_data_engine
from technical_analysis_engine import technical_analysis_engine
from smc_engine import smc_engine


logger = get_logger("market_scanner")


class MarketScanner:

    VERSION = "2.0"

    PILOT_INSTRUMENTS = (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    )

    STRATEGY_TIMEFRAMES = (
        "H1",
        "M5",
        "M1",
    )

    CANDLE_COUNT = 1000

    def __init__(self):

        self.market_data = market_data_engine
        self.technical_analysis = technical_analysis_engine
        self.smc = smc_engine

        self.instruments = list(
            self.PILOT_INSTRUMENTS
        )

        self.running = False
        self.stop_event = asyncio.Event()
        self.scan_lock = asyncio.Lock()

        self.scan_interval = max(
            5,
            int(
                getattr(
                    settings,
                    "SCAN_INTERVAL_SECONDS",
                    15,
                )
            ),
        )

        self.last_scan_time = None
        self.total_scans = 0
        self.successful_scans = 0
        self.failed_scans = 0

        self.results: Dict[
            str,
            Dict[str, Any]
        ] = {}

        self.status = "INITIALIZED"

    # --------------------------------------------------
    # ASYNC COMPATIBILITY
    # --------------------------------------------------

    @staticmethod
    async def _resolve(value):

        if inspect.isawaitable(value):
            return await value

        return value

    # --------------------------------------------------
    # CANDLE VALIDATION
    # --------------------------------------------------

    @staticmethod
    def _valid_candles(candles):

        if not isinstance(candles, list):
            return False

        if len(candles) < 50:
            return False

        required = (
            "open",
            "high",
            "low",
            "close",
        )

        for candle in candles:

            if not isinstance(candle, dict):
                return False

            try:

                values = [
                    float(candle[key])
                    for key in required
                ]

                if any(
                    not math.isfinite(value)
                    for value in values
                ):
                    return False

                open_price, high, low, close = values

                if low <= 0 or high <= 0:
                    return False

                if high < low:
                    return False

                if not (
                    low <= open_price <= high
                    and low <= close <= high
                ):
                    return False

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                return False

        return True

    # --------------------------------------------------
    # MARKET DATA COLLECTION
    # --------------------------------------------------

    async def _collect_timeframe(
        self,
        symbol: str,
        timeframe: str,
    ) -> Dict[str, Any]:

        candles = await (
            self.market_data.get_recent_candles(
                symbol=symbol,
                timeframe=timeframe,
                count=self.CANDLE_COUNT,
                price_type="bid",
            )
        )

        if not self._valid_candles(candles):

            return {
                "valid": False,
                "timeframe": timeframe,
                "candles": [],
                "reason": (
                    "INSUFFICIENT_OR_INVALID_CANDLES"
                ),
            }

        analysis = await self._resolve(
            self.technical_analysis.analyze(
                candles,
                symbol=symbol,
                timeframe=timeframe,
            )
        )

        if not isinstance(analysis, dict):

            return {
                "valid": False,
                "timeframe": timeframe,
                "candles": candles,
                "reason": (
                    "TECHNICAL_ANALYSIS_FAILED"
                ),
            }

        return {
            "valid": True,
            "timeframe": timeframe,
            "candles": candles,
            "technical": analysis,
            "candle_count": len(candles),
            "latest_candle": candles[-1],
            "reason": "ANALYSIS_COMPLETED",
        }

    # --------------------------------------------------
    # LIVE PRICE VALIDATION
    # --------------------------------------------------

    def _get_validated_live_tick(
        self,
        symbol: str,
    ):

        tick = self.market_data.get_live_tick(
            symbol
        )

        if not isinstance(tick, dict):
            return None

        try:

            bid = float(tick["bid"])
            ask = float(tick["ask"])
            mid = float(
                tick.get(
                    "mid",
                    (bid + ask) / 2,
                )
            )
            age = float(tick["age"])

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

        if not all(
            math.isfinite(value)
            for value in (
                bid,
                ask,
                mid,
                age,
            )
        ):
            return None

        if bid <= 0 or ask < bid:
            return None

        if age < 0:
            return None

        max_age = float(
            getattr(
                settings,
                "LIVE_TICK_MAX_AGE_SECONDS",
                10,
            )
        )

        if age > max_age:
            return None

        if tick.get("fresh") is not True:
            return None

        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": ask - bid,
            "timestamp": tick.get("timestamp"),
            "age": age,
            "fresh": True,
        }

    # --------------------------------------------------
    # SCAN ONE INSTRUMENT
    # --------------------------------------------------

    async def scan_instrument(
        self,
        symbol: str,
    ) -> Dict[str, Any]:

        symbol = str(symbol).upper().strip()

        result = {
            "symbol": symbol,
            "status": "SCANNING",
            "setup_found": False,
            "direction": None,
            "timeframes": {},
            "analysis": None,
            "reason": None,
            "execution_authorized": False,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        if symbol not in self.instruments:

            result.update({
                "status": "REJECTED",
                "reason": "INSTRUMENT_NOT_APPROVED",
            })

            return self._store_result(
                symbol,
                result,
            )

        try:

            # ------------------------------------------
            # COLLECT H1, M5 AND M1
            # ------------------------------------------

            timeframe_results = await asyncio.gather(
                *[
                    self._collect_timeframe(
                        symbol,
                        timeframe,
                    )
                    for timeframe in self.STRATEGY_TIMEFRAMES
                ],
                return_exceptions=True,
            )

            market_data = {}
            data_errors = []

            for timeframe, item in zip(
                self.STRATEGY_TIMEFRAMES,
                timeframe_results,
            ):

                if isinstance(item, Exception):

                    data_errors.append({
                        "timeframe": timeframe,
                        "error": str(item),
                    })

                    continue

                result["timeframes"][timeframe] = item

                if item.get("valid") is not True:

                    data_errors.append({
                        "timeframe": timeframe,
                        "error": item.get("reason"),
                    })

                    continue

                market_data[timeframe] = {
                    "candles": item["candles"],
                    "technical": item["technical"],
                }

            # ------------------------------------------
            # REQUIRED TIMEFRAME VALIDATION
            # ------------------------------------------

            if (
                data_errors
                or len(market_data) != len(
                    self.STRATEGY_TIMEFRAMES
                )
            ):

                result.update({
                    "status": "DATA_INCOMPLETE",
                    "reason": (
                        "REQUIRED_TIMEFRAME_DATA_UNAVAILABLE"
                    ),
                    "data_errors": data_errors,
                })

                return self._store_result(
                    symbol,
                    result,
                )

            # ------------------------------------------
            # GET FRESH LIVE BID/ASK
            # ------------------------------------------

            live_tick = self._get_validated_live_tick(
                symbol
            )

            if live_tick is None:

                result.update({
                    "status": "LIVE_TICK_UNAVAILABLE",
                    "reason": (
                        "NO_VALID_FRESH_LIVE_BID_ASK"
                    ),
                    "execution_authorized": False,
                })

                logger.warning(
                    "Live tick unavailable or stale | %s",
                    symbol,
                )

                return self._store_result(
                    symbol,
                    result,
                )

            current_price = live_tick["mid"]

            if (
                not math.isfinite(current_price)
                or current_price <= 0
            ):

                result.update({
                    "status": "INVALID_PRICE",
                    "reason": "CURRENT_PRICE_INVALID",
                })

                return self._store_result(
                    symbol,
                    result,
                )

            # Make validated live market prices
            # accessible to the SMC analysis input.
            market_data["live_tick"] = dict(
                live_tick
            )

            result.update({
                "current_price": current_price,
                "bid": live_tick["bid"],
                "ask": live_tick["ask"],
                "spread": live_tick["spread"],
                "tick_timestamp": live_tick["timestamp"],
                "tick_age_seconds": live_tick["age"],
                "live_tick_fresh": True,
            })

            # ------------------------------------------
            # MASTER SMC ENGINE
            # ------------------------------------------

            decision = await self._resolve(
                self.smc.analyse(
                    market_data=market_data,
                    current_price=current_price,
                    entry_evidence=None,
                    poi_evidence=None,
                    displacement_evidence=None,
                    fvg_evidence=None,
                    risk_checks=None,
                    category_scores=None,
                    fundamentals=None,
                )
            )

            if not isinstance(decision, dict):

                result.update({
                    "status": "ANALYSIS_ERROR",
                    "reason": (
                        "MASTER_SMC_RETURNED_INVALID_RESULT"
                    ),
                })

                return self._store_result(
                    symbol,
                    result,
                )

            result["analysis"] = decision

            setup_found = (
                decision.get("status") == "A_PLUS_SETUP"
                and decision.get("a_plus") is True
                and decision.get(
                    "execution_authorized"
                ) is True
            )

            result.update({
                "status": (
                    "SETUP_CANDIDATE"
                    if setup_found
                    else "NO_CONFIRMED_SETUP"
                ),
                "setup_found": setup_found,
                "direction": decision.get("direction"),
                "reason": decision.get("reason"),
                "execution_authorized": False,
            })

            logger.info(
                "Analysis complete | %s | "
                "Bid: %s | Ask: %s | Mid: %s | "
                "Tick age: %.2fs | Status: %s | "
                "Direction: %s",
                symbol,
                live_tick["bid"],
                live_tick["ask"],
                current_price,
                live_tick["age"],
                result["status"],
                result["direction"],
            )

            return self._store_result(
                symbol,
                result,
            )

        except Exception as exc:

            logger.exception(
                "Instrument scan failed: %s",
                symbol,
            )

            result.update({
                "status": "ERROR",
                "reason": str(exc),
            })

            return self._store_result(
                symbol,
                result,
            )

    # --------------------------------------------------
    # STORE RESULTS
    # --------------------------------------------------

    def _store_result(
        self,
        symbol: str,
        result: Dict[str, Any],
    ):

        self.results[symbol] = result

        if result["status"] in (
            "ERROR",
            "ANALYSIS_ERROR",
        ):

            self.failed_scans += 1

        else:

            self.successful_scans += 1

        return result

    # --------------------------------------------------
    # SCAN PILOT
    # --------------------------------------------------

    async def scan_all(self):

        async with self.scan_lock:

            self.total_scans += 1

            self.last_scan_time = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            logger.info(
                "Starting V1 market scan | "
                "%s instruments | %s",
                len(self.instruments),
                ", ".join(self.instruments),
            )

            tasks = [
                self.scan_instrument(symbol)
                for symbol in self.instruments
            ]

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

            completed = {}

            for symbol, scan_result in zip(
                self.instruments,
                results,
            ):

                if isinstance(scan_result, Exception):

                    logger.error(
                        "Scan task failed | %s | %s",
                        symbol,
                        scan_result,
                    )

                    completed[symbol] = {
                        "symbol": symbol,
                        "status": "ERROR",
                        "setup_found": False,
                        "reason": str(scan_result),
                        "execution_authorized": False,
                    }

                    self.failed_scans += 1

                else:

                    completed[symbol] = scan_result

            self.status = "RUNNING"

            setup_count = sum(
                1
                for item in completed.values()
                if item.get("setup_found") is True
            )

            logger.info(
                "V1 scan complete | "
                "%s instruments | "
                "%s setup candidates",
                len(completed),
                setup_count,
            )

            return {
                "status": "COMPLETED",
                "timestamp": self.last_scan_time,
                "total_instruments": len(completed),
                "setup_candidates": setup_count,
                "results": completed,
                "execution_authorized": False,
            }

    # --------------------------------------------------
    # CONTINUOUS SCANNING
    # --------------------------------------------------

    async def run(self):

        if self.running:

            logger.warning(
                "Market scanner is already running"
            )

            return

        self.running = True
        self.stop_event.clear()
        self.status = "RUNNING"

        logger.info(
            "Vrotex V1 market scanner started"
        )

        logger.info(
            "Pilot instruments: %s",
            ", ".join(self.instruments),
        )

        logger.info(
            "Strategy timeframes: H1 -> M5 -> M1"
        )

        logger.info(
            "Candles per strategy timeframe: %s",
            self.CANDLE_COUNT,
        )

        try:

            while self.running:

                started = (
                    asyncio.get_running_loop().time()
                )

                await self.scan_all()

                elapsed = (
                    asyncio.get_running_loop().time()
                    - started
                )

                delay = max(
                    1,
                    self.scan_interval - elapsed,
                )

                try:

                    await asyncio.wait_for(
                        self.stop_event.wait(),
                        timeout=delay,
                    )

                    break

                except asyncio.TimeoutError:

                    continue

        except asyncio.CancelledError:

            logger.info(
                "Market scanner task cancelled"
            )

            raise

        except Exception:

            logger.exception(
                "Market scanner loop failed"
            )

            self.status = "ERROR"

        finally:

            self.running = False

            if self.status != "ERROR":
                self.status = "STOPPED"

            logger.info(
                "Vrotex V1 market scanner stopped"
            )

    # --------------------------------------------------
    # STOP
    # --------------------------------------------------

    async def stop(self):

        self.running = False
        self.stop_event.set()

        logger.info(
            "Market scanner stop requested"
        )

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_status(self):

        live_ticks = self.market_data.get_live_ticks()

        return {
            "module": "MarketScanner",
            "version": self.VERSION,
            "status": self.status,
            "running": self.running,
            "instruments": list(self.instruments),
            "strategy_timeframes": list(
                self.STRATEGY_TIMEFRAMES
            ),
            "candles_per_timeframe": self.CANDLE_COUNT,
            "scan_interval_seconds": self.scan_interval,
            "total_scans": self.total_scans,
            "successful_scans": self.successful_scans,
            "failed_scans": self.failed_scans,
            "last_scan_time": self.last_scan_time,
            "live_tick_count": len(live_ticks),
            "live_tick_instruments": list(
                live_ticks.keys()
            ),
            "execution_authorized": False,
        }


market_scanner = MarketScanner()

# Compatibility alias for engine.py
scanner = market_scanner
