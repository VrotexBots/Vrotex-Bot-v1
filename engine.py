
import asyncio

from config import settings
from logging_config import get_logger
from state_manager import state_manager
from health import health_monitor
from scanner import scanner
from market_data_engine import market_data_engine


logger = get_logger("engine")


class TradingEngine:

    def __init__(self):

        self.running = False
        self.tasks = []
        self.heartbeat_interval = 30
        self.market_data_verified = False
        self.market_data_result = None

        self._stop_lock = asyncio.Lock()

    async def initialize(self):

        logger.info("Initializing Vrotex Trading Engine.")

        state_manager.initialize(
            mode=settings.BOT_MODE,
            instruments=settings.INSTRUMENTS,
        )

        state_manager.set_execution_enabled(
            settings.ORDER_EXECUTION_ENABLED
        )

        state_manager.set_status("INITIALIZING")

        logger.info(
            "Verifying strategy market data."
        )

        self.market_data_result = (
            await market_data_engine.verify_required_market_data(
                count=500
            )
        )

        self.market_data_verified = (
            self.market_data_result.get("ready", False)
        )

        if not self.market_data_verified:

            state_manager.set_status(
                "MARKET_DATA_UNAVAILABLE"
            )

            logger.critical(
                "Startup blocked. Market data verification "
                "failed: %s/%s pairs.",
                self.market_data_result.get("verified", 0),
                self.market_data_result.get("expected", 18),
            )

            return False

        logger.info(
            "Market data verified: %s/%s pairs.",
            self.market_data_result["verified"],
            self.market_data_result["expected"],
        )

        logger.info(
            "Engine initialization complete."
        )

        return True

    async def heartbeat_loop(self):

        while self.running:

            try:

                state_manager.heartbeat()

                health = health_monitor.get_health()

                logger.debug(
                    "Health status: %s",
                    health.get("status", "UNKNOWN"),
                )

            except Exception:

                logger.exception(
                    "Heartbeat monitoring error."
                )

            await asyncio.sleep(
                self.heartbeat_interval
            )

    async def scanner_loop(self):

        if not self.market_data_verified:
            raise RuntimeError(
                "Scanner cannot start without verified market data."
            )

        logger.info(
            "Starting Vrotex market scanner."
        )

        await scanner.run()

    async def start(self):

        if self.running:
            logger.warning(
                "Trading engine already running."
            )
            return

        initialized = await self.initialize()

        if not initialized:

            logger.error(
                "Trading engine startup blocked."
            )
            return

        self.running = True

        state_manager.set_status("RUNNING")

        logger.info(
            "Vrotex Trading Engine is running."
        )

        self.tasks = [
            asyncio.create_task(
                self.heartbeat_loop(),
                name="vrotex-heartbeat",
            ),
            asyncio.create_task(
                self.scanner_loop(),
                name="vrotex-scanner",
            ),
        ]

        try:

            await asyncio.gather(*self.tasks)

        except asyncio.CancelledError:

            logger.info(
                "Engine tasks cancelled."
            )

            raise

        except Exception:

            logger.exception(
                "Trading engine runtime failure."
            )

            state_manager.add_error(
                "Trading engine encountered a runtime failure."
            )

        finally:

            await self.stop()

    async def stop(self):

        async with self._stop_lock:

            if not self.running:
                return

            logger.info(
                "Stopping Vrotex Trading Engine."
            )

            self.running = False

            state_manager.request_shutdown()

            try:

                await scanner.stop()

            except Exception:

                logger.exception(
                    "Scanner shutdown error."
                )

            current_task = asyncio.current_task()

            tasks_to_stop = [
                task
                for task in self.tasks
                if task is not current_task and not task.done()
            ]

            for task in tasks_to_stop:
                task.cancel()

            if tasks_to_stop:

                await asyncio.gather(
                    *tasks_to_stop,
                    return_exceptions=True,
                )

            self.tasks.clear()

            state_manager.set_status("STOPPED")

            logger.info(
                "Vrotex Trading Engine stopped."
            )

    def get_status(self):

        return {
            "running": self.running,
            "market_data_verified": self.market_data_verified,
            "market_data": self.market_data_result,
            "health": health_monitor.get_health(),
            "state": state_manager.get_state(),
            "scanner": scanner.get_status(),
        }


engine = TradingEngine()
