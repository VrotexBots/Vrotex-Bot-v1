
import asyncio

from config import settings
from logging_config import get_logger
from state_manager import state_manager
from health import health_monitor
from scanner import scanner
from decision_engine import decision_engine

logger = get_logger("engine")


class TradingEngine:

    VERSION = "2.0"

    def __init__(self):

        self.running = False
        self.tasks = []
        self.heartbeat_interval = 30
        self.last_decision = None
        self.scanner_connected = False
        self.runtime_errors = []

    async def initialize(self):

        logger.info("Initializing Vrotex Bot V1.")

        state_manager.initialize(
            mode=settings.BOT_MODE,
            instruments=settings.INSTRUMENTS
        )

        # Real-money execution must never be enabled
        # automatically by the engine.
        state_manager.set_execution_enabled(
            settings.ORDER_EXECUTION_ENABLED
        )

        state_manager.set_status("INITIALIZING")

        logger.info(
            "Decision engine loaded: %s",
            decision_engine.VERSION
        )

        logger.info(
            "Decision threshold: %.2f",
            decision_engine.minimum_score
        )

        logger.info(
            "Configured instruments: %s",
            settings.INSTRUMENTS
        )

        # Register the decision callback if the scanner
        # implements the callback interface.
        callback_register = getattr(
            scanner,
            "set_decision_callback",
            None
        )

        if callable(callback_register):

            callback_register(self.process_setup)

            self.scanner_connected = True

            logger.info(
                "Scanner decision callback connected."
            )

        else:

            self.scanner_connected = False

            logger.warning(
                "Scanner does not yet expose "
                "set_decision_callback(). "
                "Decision integration is not complete."
            )

        state_manager.set_status("INITIALIZED")

        logger.info("Engine initialization complete.")

    def process_setup(self, setup):

        """
        Receives a completed setup from the scanner
        and evaluates it through the decision engine.
        """

        if not isinstance(setup, dict):

            logger.error(
                "Scanner supplied invalid setup data."
            )

            return None

        try:

            result = decision_engine.evaluate(setup)

            self.last_decision = result

            if result.get("approved") is True:

                logger.info(
                    "DECISION APPROVED | %s | %s | %.2f",
                    result.get("symbol"),
                    result.get("direction"),
                    result.get("score", 0)
                )

            else:

                logger.info(
                    "DECISION REJECTED | %s",
                    result.get("reason")
                )

            # This engine does not place broker orders.
            # Execution remains a separate controlled stage.
            return result

        except Exception:

            logger.exception(
                "Decision evaluation failed."
            )

            return None

    async def heartbeat_loop(self):

        while self.running:

            try:

                state_manager.heartbeat()

                health = health_monitor.get_health()

                logger.debug(
                    "Health status: %s",
                    health.get("status", "UNKNOWN")
                )

            except Exception:

                logger.exception(
                    "Heartbeat monitoring failure."
                )

            await asyncio.sleep(
                self.heartbeat_interval
            )

    async def scanner_loop(self):

        logger.info("Starting scanner loop.")

        try:

            await scanner.run()

            if self.running:

                raise RuntimeError(
                    "Scanner stopped unexpectedly."
                )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.exception("Scanner failure.")

            self.runtime_errors.append(
                "Scanner runtime failure"
            )

            state_manager.add_error(
                "Scanner runtime failure"
            )

            raise

    async def start(self):

        if self.running:

            logger.warning(
                "Trading engine already running."
            )

            return

        await self.initialize()

        self.running = True

        state_manager.set_status("RUNNING")

        logger.info(
            "Vrotex Bot V1 started in %s mode.",
            settings.BOT_MODE
        )

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

            logger.info(
                "Engine tasks cancelled."
            )

            raise

        except Exception:

            logger.exception(
                "Trading engine runtime failure."
            )

            state_manager.add_error(
                "Trading engine runtime failure"
            )

        finally:

            await self.stop()

    async def stop(self):

        if not self.running:
            return

        logger.info("Stopping Vrotex Bot V1.")

        self.running = False

        state_manager.request_shutdown()

        try:

            scanner.stop()

        except Exception:

            logger.exception(
                "Scanner shutdown error."
            )

        current_task = asyncio.current_task()

        for task in self.tasks:

            if task is not current_task and not task.done():

                task.cancel()

        remaining_tasks = [
            task for task in self.tasks
            if task is not current_task
        ]

        if remaining_tasks:

            await asyncio.gather(
                *remaining_tasks,
                return_exceptions=True
            )

        self.tasks.clear()

        state_manager.set_status("STOPPED")

        logger.info("Vrotex Bot V1 stopped.")

    def get_status(self):

        return {
            "version": self.VERSION,
            "running": self.running,
            "scanner_connected": self.scanner_connected,
            "decision_engine": decision_engine.get_status(),
            "last_decision": self.last_decision,
            "health": health_monitor.get_health(),
            "state": state_manager.get_state(),
            "scanner": scanner.get_status(),
            "runtime_errors": list(self.runtime_errors),
        }


engine = TradingEngine()
