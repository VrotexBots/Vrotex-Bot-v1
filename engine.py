import asyncio

from config import settings
from logging_config import get_logger
from state_manager import state_manager
from health import health_monitor
from scanner import scanner

logger = get_logger("engine")


class TradingEngine:

    def __init__(self):

        self.running = False
        self.tasks = []
        self.heartbeat_interval = 30

    async def initialize(self):

        logger.info("Initializing trading engine.")

        state_manager.initialize(
            mode=settings.BOT_MODE,
            instruments=settings.INSTRUMENTS
        )

        state_manager.set_execution_enabled(
            settings.ORDER_EXECUTION_ENABLED
        )

        state_manager.set_status("INITIALIZING")

        logger.info("Engine initialization complete.")

    async def heartbeat_loop(self):

        while self.running:

            state_manager.heartbeat()

            health = health_monitor.get_health()

            logger.debug(
                "Health status: %s",
                health["status"]
            )

            await asyncio.sleep(self.heartbeat_interval)

    async def scanner_loop(self):

        await scanner.run()

    async def start(self):

        if self.running:
            logger.warning("Engine already running.")
            return

        await self.initialize()

        self.running = True

        state_manager.set_status("RUNNING")

        logger.info("Vrotex Trading Engine is running.")

        self.tasks = [
            asyncio.create_task(
                self.heartbeat_loop(),
                name="vrotex-heartbeat"
            ),
            asyncio.create_task(
                self.scanner_loop(),
                name="vrotex-scanner"
            ),
        ]

        try:

            await asyncio.gather(*self.tasks)

        except asyncio.CancelledError:

            logger.info("Engine tasks cancelled.")

            raise

        except Exception:

            logger.exception("Trading engine failure")

            state_manager.add_error(
                "Trading engine encountered a runtime failure"
            )

        finally:

            await self.stop()

    async def stop(self):

        if not self.running:
            return

        logger.info("Stopping trading engine.")

        self.running = False

        state_manager.request_shutdown()

        scanner.stop()

        for task in self.tasks:

            if not task.done():
                task.cancel()

        if self.tasks:

            await asyncio.gather(
                *self.tasks,
                return_exceptions=True
            )

        self.tasks.clear()

        state_manager.set_status("STOPPED")

        logger.info("Trading engine stopped.")

    def get_status(self):

        return {
            "running": self.running,
            "health": health_monitor.get_health(),
            "state": state_manager.get_state(),
            "scanner": scanner.get_status(),
        }


engine = TradingEngine()
