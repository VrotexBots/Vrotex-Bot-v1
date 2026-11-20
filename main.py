
import asyncio
import signal
import sys

from config import settings, validate_settings
from logging_config import setup_logging


logger = setup_logging()


class VrotexBot:

    def __init__(self):

        self.running = False
        self.shutdown_event = asyncio.Event()
        self.engine_task = None

    async def initialize(self):

        logger.info("=" * 50)
        logger.info("INITIALIZING %s", settings.BOT_NAME)
        logger.info("=" * 50)

        validate_settings()

        logger.info("Mode: %s", settings.BOT_MODE)

        logger.info(
            "Execution enabled: %s",
            settings.ORDER_EXECUTION_ENABLED,
        )

        logger.info(
            "Instruments: %s",
            ", ".join(settings.INSTRUMENTS),
        )

        logger.info("Strategy: H1 -> M5 -> M1")

        self.running = True

    async def start(self):

        await self.initialize()

        logger.info("Vrotex Bot V1 starting.")

        from engine import engine

        self.engine_task = asyncio.create_task(
            engine.start(),
            name="vrotex-trading-engine",
        )

        shutdown_task = asyncio.create_task(
            self.shutdown_event.wait(),
            name="vrotex-shutdown-waiter",
        )

        try:

            done, pending = await asyncio.wait(
                [self.engine_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if shutdown_task in done:

                logger.info(
                    "Shutdown signal received."
                )

                await engine.stop()

            if self.engine_task in done:

                await self.engine_task

        finally:

            shutdown_task.cancel()

            await asyncio.gather(
                shutdown_task,
                return_exceptions=True,
            )

            await self.stop()

    async def stop(self):

        if not self.running:
            return

        logger.info("Shutdown requested.")

        self.running = False
        self.shutdown_event.set()

        try:

            from engine import engine

            await engine.stop()

        except Exception:

            logger.exception(
                "Engine shutdown failed."
            )

        if (
            self.engine_task
            and not self.engine_task.done()
            and self.engine_task is not asyncio.current_task()
        ):

            self.engine_task.cancel()

            await asyncio.gather(
                self.engine_task,
                return_exceptions=True,
            )

        logger.info("Vrotex Bot V1 stopped.")


async def main():

    bot = VrotexBot()

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):

        try:

            loop.add_signal_handler(
                sig,
                bot.shutdown_event.set,
            )

        except (NotImplementedError, RuntimeError):

            logger.warning(
                "Signal handler unavailable for %s",
                sig,
            )

    try:

        await bot.start()

    except asyncio.CancelledError:

        logger.info("Bot task cancelled.")

        raise

    except Exception:

        logger.exception(
            "Fatal bot startup/runtime error."
        )

        sys.exit(1)


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info("Bot interrupted.")
