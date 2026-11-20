
import asyncio
import signal
import sys

from config import settings, validate_settings
from logging_config import setup_logging
from engine import engine


logger = setup_logging()


class VrotexBot:

    VERSION = "1.0"

    def __init__(self):

        self.running = False
        self.shutdown_event = asyncio.Event()
        self.engine_task = None

    async def initialize(self):

        logger.info("=" * 55)
        logger.info("INITIALIZING %s", settings.BOT_NAME)
        logger.info("=" * 55)

        validate_settings()

        logger.info("Bot version: %s", self.VERSION)
        logger.info("Mode: %s", settings.BOT_MODE)
        logger.info(
            "Execution enabled: %s",
            settings.ORDER_EXECUTION_ENABLED
        )
        logger.info(
            "Instruments: %s",
            ", ".join(settings.INSTRUMENTS)
        )
        logger.info("Strategy: H1 -> M5 -> M1")

        if settings.BOT_MODE.upper() != "DEMO":
            logger.warning(
                "BOT MODE IS NOT DEMO. "
                "Verify configuration before starting."
            )

        self.running = True

        logger.info("Configuration validation completed.")

    async def start(self):

        await self.initialize()

        logger.info("Starting Vrotex master engine.")

        self.engine_task = asyncio.create_task(
            engine.start(),
            name="vrotex-master-engine"
        )

        try:

            shutdown_task = asyncio.create_task(
                self.shutdown_event.wait(),
                name="vrotex-shutdown-waiter"
            )

            done, pending = await asyncio.wait(
                [self.engine_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(
                *pending,
                return_exceptions=True
            )

            if self.engine_task in done:
                await self.engine_task

        except asyncio.CancelledError:

            logger.info("Bot startup task cancelled.")
            raise

        finally:

            await self.stop()

    async def stop(self):

        if not self.running:
            return

        logger.info("Vrotex shutdown requested.")

        self.running = False
        self.shutdown_event.set()

        try:

            await engine.stop()

        except Exception:

            logger.exception(
                "Error while stopping master engine."
            )

        if self.engine_task and not self.engine_task.done():

            self.engine_task.cancel()

            await asyncio.gather(
                self.engine_task,
                return_exceptions=True
            )

        logger.info("Vrotex Bot V1 stopped.")


async def main():

    bot = VrotexBot()

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):

        try:

            loop.add_signal_handler(
                sig,
                bot.shutdown_event.set
            )

        except (NotImplementedError, RuntimeError):

            logger.warning(
                "Signal handler unavailable for %s",
                sig
            )

    await bot.start()


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info("Bot interrupted by user.")

    except Exception:

        logger.exception(
            "Fatal Vrotex Bot V1 startup/runtime error."
        )

        sys.exit(1)
