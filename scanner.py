
"""
VROTEX BOT V1
Market Scanner

Version: 2.0

Purpose:
- Continuously scan all six approved instruments.
- Retrieve H1, M5 and M1 market candles.
- Run technical analysis on each timeframe.
- Submit collected market data to the master SMC engine.
- Reject incomplete setups.
- Keep execution disabled.

Strategy:
H1 = External narrative
M5 = Confirmation
M1 = Entry

This module does not place orders.
"""

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import settings
from logging_config import get_logger

from market_data_engine import market_data_engine
from technical_analysis_engine import technical_analysis_engine
from smc_engine import smc_engine


logger = get_logger("market_scanner")


class MarketScanner:

    VERSION = "2.0"

    STRATEGY_TIMEFRAMES = (
        "H1",
        "M5",
        "M1",
    )

    CANDLE_COUNT = 500

    def __init__(self):

        self.market_data = market_data_engine
        self.technical_analysis = technical_analysis_engine
        self.smc = smc_engine

        self.instruments = list(
            getattr(settings, "INSTRUMENTS", [
                "EURUSD",
                "GBPUSD",
                "USDJPY",
                "EURJPY",
                "EURGBP",
                "BTCUSD",
            ])
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

        self.results: Dict[str, Dict[str, Any]] = {}

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
                    not __import__("math").isfinite(v)
                    for v in values
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

            except (KeyError, TypeError, ValueError):
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

        candles = await self.market_data.get_recent_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=self.CANDLE_COUNT,
            price_type="bid",
        )

        if not self._valid_candles(candles):

            return {
                "valid": False,
                "timeframe": timeframe,
                "candles": [],
                "reason": "INSUFFICIENT_OR_INVALID_CANDLES",
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
                "reason": "TECHNICAL_ANALYSIS_FAILED",
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
    # SCAN ONE INSTRUMENT
    # --------------------------------------------------

    async def scan_instrument(
        self,
        symbol: str,
    ) -> Dict[str, Any]:

        symbol = str(symbol).upper()

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

        try:

            # Fetch H1, M5 and M1 concurrently.
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

            # Every strategy timeframe is mandatory.
            if (
                data_errors
                or len(market_data) != 3
            ):

                result.update({
                    "status": "DATA_INCOMPLETE",
                    "reason": "REQUIRED_TIMEFRAME_DATA_UNAVAILABLE",
                    "data_errors": data_errors,
                })

                return self._store_result(
                    symbol,
                    result,
                )

            # Current price comes from the latest M1 close.
            current_price = float(
                market_data["M1"]["candles"][-1]["close"]
            )

            if current_price <= 0:

                result.update({
                    "status": "INVALID_PRICE",
                    "reason": "CURRENT_PRICE_INVALID",
                })

                return self._store_result(
                    symbol,
                    result,
                )

            result["current_price"] = current_price

            # --------------------------------------------------
            # MASTER SMC DECISION
            # --------------------------------------------------
            #
            # The dedicated SMC evidence-generation pipeline
            # must supply entry, POI, FVG, displacement and
            # measured risk evidence before a setup can pass.
            #
            # Missing evidence is deliberately passed as None.
            # The master engine must reject incomplete setups.
            # --------------------------------------------------

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
                    "reason": "MASTER_SMC_RETURNED_INVALID_RESULT",
                })

                return self._store_result(
                    symbol,
                    result,
                )

            result["analysis"] = decision

            setup_found = (
                decision.get("status") == "A_PLUS_SETUP"
                and decision.get("a_plus") is True
                and decision.get("execution_authorized") is True
            )

            # The scanner never authorizes execution itself.
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
    ) -> Dict[str, Any]:

        self.results[symbol] = result

        if result["status"] == "ERROR":

            self.failed_scans += 1

        else:

            self.successful_scans += 1

        return result

    # --------------------------------------------------
    # SCAN ALL INSTRUMENTS
    # --------------------------------------------------

    async def scan_all(self) -> Dict[str, Any]:

        async with self.scan_lock:

            self.total_scans += 1

            self.last_scan_time = datetime.now(
                timezone.utc
            ).isoformat()

            logger.info(
                "Starting market scan: %s instruments",
                len(self.instruments),
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

            for symbol, result in zip(
                self.instruments,
                results,
            ):

                if isinstance(result, Exception):

                    logger.error(
                        "Scan task failed for %s: %s",
                        symbol,
                        result,
                    )

                    completed[symbol] = {
                        "symbol": symbol,
                        "status": "ERROR",
                        "setup_found": False,
                        "reason": str(result),
                        "execution_authorized": False,
                    }

                    self.failed_scans += 1

                else:

                    completed[symbol] = result

            self.status = "RUNNING"

            setup_count = sum(
                1
                for item in completed.values()
                if item.get("setup_found") is True
            )

            logger.info(
                "Market scan complete: %s instruments, %s setup candidates",
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

        try:

            while self.running:

                started = asyncio.get_running_loop().time()

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

    def get_status(self) -> Dict[str, Any]:

        return {
            "module": "MarketScanner",
            "version": self.VERSION,
            "status": self.status,
            "running": self.running,
            "instruments": list(self.instruments),
            "strategy_timeframes": list(
                self.STRATEGY_TIMEFRAMES
            ),
            "scan_interval_seconds": self.scan_interval,
            "total_scans": self.total_scans,
            "successful_scans": self.successful_scans,
            "failed_scans": self.failed_scans,
            "last_scan_time": self.last_scan_time,
            "execution_authorized": False,
        }


market_scanner = MarketScanner()
