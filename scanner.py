import asyncio

from config import settings
from logging_config import get_logger
from state_manager import state_manager
from utils.metrics import metrics

logger = get_logger("scanner")


class MarketScanner:

    def __init__(self):

        self.instruments = list(settings.INSTRUMENTS)
        self.running = False
        self.scan_interval = 1.0

        self.scan_count = 0
        self.last_scan_results = {}

    async def scan_instrument(self, symbol):

        """
        Individual instrument scan.

        Market-data and strategy modules will be connected
        here as they are implemented.
        """

        try:

            logger.debug("Scanning %s", symbol)

            # Strategy analysis will be integrated here.

            return {
                "symbol": symbol,
                "status": "WAITING_FOR_MARKET_DATA",
                "setup_found": False,
            }

        except Exception as exc:

            logger.exception("Scan failed for %s", symbol)

            state_manager.add_error(
                f"Scanner error for {symbol}: {exc}"
            )

            metrics.increment("scanner_errors")

            return {
                "symbol": symbol,
                "status": "ERROR",
                "setup_found": False,
                "error": str(exc),
            }

    async def scan_all(self):

        tasks = [
            self.scan_instrument(symbol)
            for symbol in self.instruments
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

        normalized_results = []

        for symbol, result in zip(self.instruments, results):

            if isinstance(result, Exception):

                logger.error(
                    "Unhandled scan exception for %s: %s",
                    symbol,
                    result
                )

                normalized_results.append({
                    "symbol": symbol,
                    "status": "ERROR",
                    "setup_found": False,
                    "error": str(result),
                })

            else:

                normalized_results.append(result)

        self.scan_count += 1
        self.last_scan_results = {
            result["symbol"]: result
            for result in normalized_results
        }

        state_manager.update_scan()

        metrics.increment("scan_cycles")
        metrics.increment("instruments_scanned", len(self.instruments))

        return normalized_results

    async def run(self):

        if self.running:
            logger.warning("Scanner is already running.")
            return

        self.running = True

        logger.info(
            "Scanner started for %s instruments",
            len(self.instruments)
        )

        try:

            while self.running:

                await self.scan_all()

                await asyncio.sleep(self.scan_interval)

        except asyncio.CancelledError:

            logger.info("Scanner task cancelled.")

            raise

        except Exception:

            logger.exception("Scanner runtime failure")

        finally:

            self.running = False

            logger.info("Scanner stopped.")

    def stop(self):

        self.running = False

    def get_status(self):

        return {
            "running": self.running,
            "instruments": self.instruments,
            "scan_count": self.scan_count,
            "last_results": self.last_scan_results,
        }


scanner = MarketScanner()
