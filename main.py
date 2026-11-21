import asyncio
import json
import os
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
        self.http_server = None

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

    # ==========================================
    # HTTP SERVER
    # ==========================================

    async def start_http_server(self):

        port = int(os.environ.get("PORT", 10000))

        self.http_server = await asyncio.start_server(
            self.handle_http_request,
            host="0.0.0.0",
            port=port,
        )

        addresses = [
            socket.getsockname()
            for socket in self.http_server.sockets
        ]

        logger.info(
            "HTTP server listening on %s",
            addresses,
        )

        logger.info(
            "Render port binding successful | PORT=%s",
            port,
        )

    async def handle_http_request(
        self,
        reader,
        writer,
    ):

        try:

            request_line = await asyncio.wait_for(
                reader.readline(),
                timeout=5,
            )

            if not request_line:

                return

            request_line = request_line.decode(
                "utf-8",
                errors="replace",
            ).strip()

            parts = request_line.split()

            if len(parts) < 2:

                await self.send_http_response(
                    writer,
                    400,
                    "Bad Request",
                    "Invalid HTTP request.",
                )

                return

            method = parts[0]
            path = parts[1].split("?")[0]

            # Read HTTP headers
            while True:

                header = await asyncio.wait_for(
                    reader.readline(),
                    timeout=5,
                )

                if not header or header in (
                    b"\r\n",
                    b"\n",
                ):

                    break

            # ==================================
            # HEALTH ENDPOINT
            # ==================================

            if path == "/health":

                engine_status = (
                    "running"
                    if (
                        self.engine_task
                        and not self.engine_task.done()
                    )
                    else "stopped"
                )

                response_data = {
                    "status": "ok",
                    "bot": settings.BOT_NAME,
                    "running": self.running,
                    "engine": engine_status,
                }

                body = json.dumps(
                    response_data
                )

                await self.send_http_response(
                    writer,
                    200,
                    "OK",
                    body,
                    content_type="application/json",
                )

                return

            # ==================================
            # ROOT ENDPOINT
            # ==================================

            if path == "/":

                body = (
                    "Vrotex Bot V1 is running."
                )

                await self.send_http_response(
                    writer,
                    200,
                    "OK",
                    body,
                    content_type="text/plain",
                )

                return

            # ==================================
            # UNKNOWN ENDPOINT
            # ==================================

            await self.send_http_response(
                writer,
                404,
                "Not Found",
                "Endpoint not found.",
            )

        except asyncio.TimeoutError:

            logger.warning(
                "HTTP request timed out."
            )

        except Exception:

            logger.exception(
                "HTTP request handler error."
            )

        finally:

            writer.close()

            try:

                await writer.wait_closed()

            except Exception:

                pass

    async def send_http_response(
        self,
        writer,
        status_code,
        status_text,
        body,
        content_type="text/plain",
    ):

        body_bytes = body.encode("utf-8")

        response_headers = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: {content_type}; charset=utf-8\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )

        writer.write(
            response_headers.encode("utf-8")
        )

        writer.write(body_bytes)

        await writer.drain()

    async def stop_http_server(self):

        if self.http_server:

            logger.info(
                "Stopping HTTP server."
            )

            self.http_server.close()

            await self.http_server.wait_closed()

            self.http_server = None

            logger.info(
                "HTTP server stopped."
            )

    # ==========================================
    # BOT STARTUP
    # ==========================================

    async def start(self):

        await self.initialize()

        logger.info(
            "Vrotex Bot V1 starting."
        )

        # Start HTTP server for Render port detection
        await self.start_http_server()

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

    # ==========================================
    # BOT SHUTDOWN
    # ==========================================

    async def stop(self):

        if not self.running:
            return

        logger.info(
            "Shutdown requested."
        )

        self.running = False

        self.shutdown_event.set()

        await self.stop_http_server()

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

        logger.info(
            "Vrotex Bot V1 stopped."
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
