import asyncio
import os
import signal
import sys

import uvicorn

from config import settings, validate_settings
from logging_config import setup_logging
from dashboard_api import create_app


logger = setup_logging()


class VrotexBot:

    def __init__(self):

        self.running = False
        self.shutdown_event = asyncio.Event()
        self.engine_task = None
        self.http_server = None
        self.engine_control_lock = asyncio.Lock()

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

        # This flag represents the application/web-service lifecycle.
        # The trading engine has its own independent lifecycle.
        self.running = True

    def is_engine_running(self):

        return bool(
            self.engine_task
            and not self.engine_task.done()
        )

    async def start_engine(self):

        async with self.engine_control_lock:

            if self.shutdown_event.is_set():
                raise RuntimeError(
                    "The Vrotex service is shutting down."
                )

            if self.is_engine_running():

                logger.info(
                    "Trading engine is already running."
                )

                return {
                    "success": True,
                    "running": True,
                    "message": "Trading engine is already running.",
                }

            from engine import engine

            logger.info(
                "Starting Vrotex trading engine."
            )

            self.engine_task = asyncio.create_task(
                engine.start(),
                name="vrotex-trading-engine",
            )

            # Allow the engine task to begin and surface immediate startup errors.
            await asyncio.sleep(0)

            if self.engine_task.done():

                exception = self.engine_task.exception()

                if exception is not None:
                    logger.error(
                        "Trading engine failed during startup.",
                        exc_info=(
                            type(exception),
                            exception,
                            exception.__traceback__,
                        ),
                    )
                    raise RuntimeError(
                        "Trading engine failed during startup."
                    ) from exception

                logger.warning(
                    "Trading engine exited during startup."
                )

                return {
                    "success": False,
                    "running": False,
                    "message": "Trading engine exited during startup. Check Live Logs.",
                }

            return {
                "success": True,
                "running": True,
                "message": "Trading engine start requested.",
            }

    async def stop_engine(self):

        async with self.engine_control_lock:

            from engine import engine

            if not self.is_engine_running():

                logger.info(
                    "Trading engine is already stopped."
                )

                self.engine_task = None

                return {
                    "success": True,
                    "running": False,
                    "message": "Trading engine is already stopped.",
                }

            logger.info(
                "Stopping Vrotex trading engine."
            )

            try:

                await engine.stop()

            except Exception:

                logger.exception(
                    "Trading engine stop request failed."
                )

                raise

            if (
                self.engine_task
                and not self.engine_task.done()
            ):

                try:

                    await asyncio.wait_for(
                        self.engine_task,
                        timeout=15,
                    )

                except asyncio.TimeoutError:

                    logger.warning(
                        "Trading engine did not stop within 15 seconds; cancelling its task."
                    )

                    self.engine_task.cancel()

                    await asyncio.gather(
                        self.engine_task,
                        return_exceptions=True,
                    )

            self.engine_task = None

            logger.info(
                "Vrotex trading engine stopped."
            )

            return {
                "success": True,
                "running": False,
                "message": "Trading engine stopped.",
            }

    async def start(self):

        await self.initialize()

        logger.info(
            "Vrotex Bot V1 service starting."
        )

        app = create_app(self)

        port = int(
            os.environ.get("PORT", 10000)
        )

        uvicorn_config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=port,
            log_config=None,
            access_log=True,
        )

        self.http_server = uvicorn.Server(
            uvicorn_config
        )

        server_task = asyncio.create_task(
            self.http_server.serve(),
            name="vrotex-dashboard-api-server",
        )

        shutdown_task = asyncio.create_task(
            self.shutdown_event.wait(),
            name="vrotex-shutdown-waiter",
        )

        logger.info(
            "Dashboard/API server starting | PORT=%s",
            port,
        )

        try:

            # Preserve the existing automatic engine startup behavior.
            await self.start_engine()

            # The web server remains alive independently of the engine.
            done, _ = await asyncio.wait(
                [
                    server_task,
                    shutdown_task,
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if server_task in done:

                # A web-server exit is a service-level event.
                await server_task

                logger.error(
                    "Dashboard/API server exited."
                )

        finally:

            shutdown_task.cancel()

            await asyncio.gather(
                shutdown_task,
                return_exceptions=True,
            )

            await self.stop()

    async def stop(self):

        if not self.running and self.http_server is None:
            return

        logger.info(
            "Vrotex Bot V1 service shutdown requested."
        )

        self.running = False
        self.shutdown_event.set()

        try:

            await self.stop_engine()

        except Exception:

            logger.exception(
                "Engine shutdown failed."
            )

        if self.http_server:

            logger.info(
                "Stopping dashboard/API server."
            )

            self.http_server.should_exit = True
            self.http_server = None

        logger.info(
            "Vrotex Bot V1 service stopped."
        )


# ==========================================
# MAIN ENTRY POINT
# ==========================================

async def main():

    bot = VrotexBot()

    loop = asyncio.get_running_loop()

    for sig in (
        signal.SIGINT,
        signal.SIGTERM,
    ):

        try:

            loop.add_signal_handler(
                sig,
                bot.shutdown_event.set,
            )

        except (
            NotImplementedError,
            RuntimeError,
        ):

            logger.warning(
                "Signal handler unavailable for %s",
                sig,
            )

    try:

        await bot.start()

    except asyncio.CancelledError:

        logger.info(
            "Bot task cancelled."
        )

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

        logger.info(
            "Bot interrupted."
        )
