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

    async def initialize(self):
        logger.info("=" * 50)
        logger.info("INITIALIZING %s", settings.BOT_NAME)
        logger.info("=" * 50)

        validate_settings()

        logger.info("Mode: %s", settings.BOT_MODE)
        logger.info("Execution enabled: %s",
                    settings.ORDER_EXECUTION_ENABLED)
        logger.info("Instruments: %s",
                    ", ".join(settings.INSTRUMENTS))
        logger.info("Strategy: H1 -> M5 -> M1")

        self.running = True

    async def start(self):
        await self.initialize()

        logger.info("Vrotex Bot V1 starting.")

        try:
            while self.running:
                await self.shutdown_event.wait()

        except asyncio.CancelledError:
            logger.info("Bot task cancelled.")

        finally:
            await self.stop()

    async def stop(self):
        if not self.running:
            return

        logger.info("Shutdown requested.")

        self.running = False
        self.shutdown_event.set()

        logger.info("Vrotex Bot V1 stopped.")


async def main():
    bot = VrotexBot()

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))
        except NotImplementedError:
            pass

    try:
        await bot.start()

    except Exception:
        logger.exception("Fatal bot startup/runtime error")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted.")
