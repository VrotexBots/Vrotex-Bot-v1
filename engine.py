
import asyncio
import inspect

from config import settings
from logging_config import get_logger

from state_manager import state_manager
from health import health_monitor
from scanner import scanner
from market_data_engine import market_data_engine
from live_tick_engine import live_tick_engine


logger = get_logger("engine")


class TradingEngine:

    def __init__(self):

        self.running = False
        self.tasks = []

        self.heartbeat_interval = 30

        self.market_data_verified = False
        self.market_data_result = None

        self.live_ticks_ready = False
        self.live_tick_result = None

        self._stop_lock = asyncio.Lock()
        self._started = False
        self._shutdown_requested = False

    # --------------------------------------------------
    # ASYNC COMPATIBILITY
    # --------------------------------------------------

    @staticmethod
    async def _run_method(method, *args):

        if inspect.iscoroutinefunction(method):
            return await method(*args)

        result = await asyncio.to_thread(
            method,
            *args,
        )

        if inspect.isawaitable(result):
            return await result

        return result

    # --------------------------------------------------
    # LIVE TICK CONNECTION
    # --------------------------------------------------

    async def start_live_ticks(self):

        logger.info(
            "Starting Exness push-based live-tick engine."
        )

        try:

            start_method = getattr(
                live_tick_engine,
                "start",
                None,
            )

            if not callable(start_method):

                raise RuntimeError(
                    "Live-tick engine has no start method."
                )

            self.live_tick_result = await self._run_method(
                start_method
            )

            status_method = getattr(
                live_tick_engine,
                "get_status",
                None,
            )

            if not callable(status_method):

                raise RuntimeError(
                    "Live-tick engine has no status method."
                )

            status = await self._run_method(
                status_method
            )

            if not isinstance(status, dict):

                raise RuntimeError(
                    "Invalid live-tick engine status."
                )

            # ------------------------------------------
            # CONNECTION READINESS
            # ------------------------------------------

            connected = (
                status.get("connected") is True
                or status.get("stream_connected") is True
            )

            # A ready stream is also necessarily connected.
            if status.get("ready") is True:
                connected = True

            if not connected:

                raise RuntimeError(
                    "Exness live-tick WebSocket "
                    "is not connected. "
                    f"Status: {status}"
                )

            # ------------------------------------------
            # IMPORTANT:
            # Connection readiness is NOT tick readiness.
            #
            # We allow the engine to start after the
            # WebSocket connects and subscribes.
            #
            # Exness will push ticks asynchronously.
            # ------------------------------------------

            self.live_ticks_ready = True

            self.live_tick_result = status

            logger.info(
                "Exness live-tick WebSocket connected. "
                "Waiting for pushed tick updates. "
                "Status: %s",
                status,
            )

            return True

        except Exception as exc:

            self.live_ticks_ready = False

            logger.exception(
                "Live-tick connection startup failed."
            )

            self.live_tick_result = {
                "connected": False,
                "ready": False,
                "error": str(exc),
            }

            return False

    # --------------------------------------------------
    # INITIALIZATION
    # --------------------------------------------------

    async def initialize(self):

        logger.info(
            "Initializing Vrotex Trading Engine."
        )

        self._shutdown_requested = False

        state_manager.initialize(
            mode=settings.BOT_MODE,
            instruments=settings.INSTRUMENTS,
        )

        state_manager.set_execution_enabled(
            settings.ORDER_EXECUTION_ENABLED
        )

        state_manager.set_status(
            "INITIALIZING"
        )

        # ----------------------------------------------
        # VERIFY STRATEGY MARKET DATA
        # ----------------------------------------------

        logger.info(
            "Verifying V1 strategy market data | "
            "3 instruments | H1, M5, M1 | 1000 candles."
        )

        self.market_data_result = (
            await market_data_engine.verify_required_market_data(
                count=1000
            )
        )

        self.market_data_verified = (
            self.market_data_result.get(
                "ready",
                False,
            ) is True
        )

        verified = self.market_data_result.get(
            "verified",
            0,
        )

        expected = self.market_data_result.get(
            "expected",
            9,
        )

        if not self.market_data_verified:

            state_manager.set_status(
                "MARKET_DATA_UNAVAILABLE"
            )

            logger.critical(
                "Startup blocked. Market data verification "
                "failed: %s/%s strategy pairs.",
                verified,
                expected,
            )

            return False

        logger.info(
            "Strategy market data verified: %s/%s pairs.",
            verified,
            expected,
        )

        # ----------------------------------------------
        # START EXNESS PUSH LIVE-TICK CONNECTION
        # ----------------------------------------------

        state_manager.set_status(
            "STARTING_LIVE_TICKS"
        )

        ticks_connected = await self.start_live_ticks()

        if not ticks_connected:

            state_manager.set_status(
                "LIVE_TICKS_UNAVAILABLE"
            )

            logger.critical(
                "Startup blocked. Exness live-tick "
                "WebSocket connection failed."
            )

            return False

        # ----------------------------------------------
        # INITIAL TICK CHECK
        #
        # Ticks are NOT required at startup.
        # Exness pushes them after subscription.
        # ----------------------------------------------

        try:

            ticks = market_data_engine.get_live_ticks()

        except Exception:

            logger.exception(
                "Could not read initial live-tick state."
            )

            ticks = {}

        required_instruments = (
            "EURUSD",
            "GBPUSD",
            "BTCUSD",
        )

        missing_ticks = [
            symbol
            for symbol in required_instruments
            if symbol not in ticks
        ]

        received_count = (
            len(required_instruments)
            - len(missing_ticks)
        )

        if missing_ticks:

            logger.info(
                "Live-tick stream connected. "
                "Waiting for Exness to push ticks for: %s",
                ", ".join(missing_ticks),
            )

        else:

            logger.info(
                "Live ticks already available for "
                "all configured instruments."
            )

        # ----------------------------------------------
        # STARTUP COMPLETE
        # ----------------------------------------------

        logger.info(
            "Startup checks passed | "
            "Market data: %s/%s | "
            "Tick connection: CONNECTED | "
            "Initial ticks: %s/%s",
            verified,
            expected,
            received_count,
            len(required_instruments),
        )

        logger.info(
            "Engine initialization complete. "
            "Waiting for live Exness tick pushes."
        )

        return True

    # --------------------------------------------------
    # HEARTBEAT
    # --------------------------------------------------

    async def heartbeat_loop(self):

        logger.info(
            "Engine heartbeat started."
        )

        while self.running:

            try:

                state_manager.heartbeat()

                health = health_monitor.get_health()

                market_status = (
                    market_data_engine.get_status()
                )

                tick_status = (
                    live_tick_engine.get_status()
                )

                logger.debug(
                    "Heartbeat | Health: %s | "
                    "Market data: %s | "
                    "Tick connection: %s | "
                    "Ticks received: %s",
                    health.get(
                        "status",
                        "UNKNOWN",
                    ),
                    market_status.get(
                        "verified_pairs",
                        0,
                    ),
                    tick_status.get(
                        "connected",
                        tick_status.get(
                            "stream_connected",
                            False,
                        ),
                    ),
                    tick_status.get(
                        "ticks_received",
                        0,
                    ),
                )

            except Exception:

                logger.exception(
                    "Heartbeat monitoring error."
                )

            try:

                await asyncio.sleep(
                    self.heartbeat_interval
                )

            except asyncio.CancelledError:
                raise

        logger.info(
            "Engine heartbeat stopped."
        )

    # --------------------------------------------------
    # SCANNER
    # --------------------------------------------------

    async def scanner_loop(self):

        if not self.market_data_verified:

            raise RuntimeError(
                "Scanner cannot start without verified market data."
            )

        if not self.live_ticks_ready:

            raise RuntimeError(
                "Scanner cannot start without a connected "
                "live-tick WebSocket."
            )

        logger.info(
            "Starting Vrotex market scanner."
        )

        logger.info(
            "Scanner active. Live prices are received "
            "through Exness push events."
        )

        await scanner.run()

    # --------------------------------------------------
    # RUNTIME TASK MONITORING
    # --------------------------------------------------

    async def monitor_tasks(self):

        if not self.tasks:
            return

        done, pending = await asyncio.wait(
            self.tasks,
            return_when=asyncio.FIRST_EXCEPTION,
        )

        for task in done:

            if task.cancelled():
                continue

            exception = task.exception()

            if exception is not None:

                logger.error(
                    "Engine task failed | %s | %s",
                    task.get_name(),
                    exception,
                )

                raise exception

        if not pending and self.running:

            logger.warning(
                "All engine tasks stopped unexpectedly."
            )

    # --------------------------------------------------
    # START
    # --------------------------------------------------

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

            await self.stop()

            return

        self.running = True
        self._started = True

        state_manager.set_status(
            "RUNNING"
        )

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

            await self.monitor_tasks()

        except asyncio.CancelledError:

            logger.info(
                "Engine tasks cancelled."
            )

            raise

        except Exception as exc:

            logger.exception(
                "Trading engine runtime failure."
            )

            try:

                state_manager.add_error(
                    str(exc)
                )

            except Exception:

                logger.exception(
                    "Could not record engine runtime error."
                )

            try:

                state_manager.set_status(
                    "RUNTIME_ERROR"
                )

            except Exception:
                pass

        finally:

            await self.stop()

    # --------------------------------------------------
    # STOP LIVE TICKS
    # --------------------------------------------------

    async def stop_live_ticks(self):

        stop_method = getattr(
            live_tick_engine,
            "stop",
            None,
        )

        if not callable(stop_method):
            return

        try:

            await self._run_method(
                stop_method
            )

            logger.info(
                "Live-tick engine stopped."
            )

        except Exception:

            logger.exception(
                "Live-tick engine shutdown error."
            )

        finally:

            self.live_ticks_ready = False

    # --------------------------------------------------
    # CLEAN SHUTDOWN
    # --------------------------------------------------

    async def stop(self):

        async with self._stop_lock:

            if self._shutdown_requested:
                return

            self._shutdown_requested = True

            logger.info(
                "Stopping Vrotex Trading Engine."
            )

            self.running = False

            try:

                state_manager.request_shutdown()

            except Exception:

                logger.exception(
                    "State manager shutdown request failed."
                )

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
                if task is not current_task
                and not task.done()
            ]

            for task in tasks_to_stop:

                task.cancel()

            if tasks_to_stop:

                await asyncio.gather(
                    *tasks_to_stop,
                    return_exceptions=True,
                )

            self.tasks.clear()

            await self.stop_live_ticks()

            try:

                state_manager.set_status(
                    "STOPPED"
                )

            except Exception:

                logger.exception(
                    "Could not update engine stopped status."
                )

            self._started = False

            logger.info(
                "Vrotex Trading Engine stopped."
            )

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_status(self):

        try:

            tick_status = (
                live_tick_engine.get_status()
            )

        except Exception as exc:

            tick_status = {
                "ready": False,
                "error": str(exc),
            }

        return {
            "running": self.running,
            "market_data_verified": (
                self.market_data_verified
            ),
            "market_data": self.market_data_result,
            "live_ticks_ready": self.live_ticks_ready,
            "live_tick_status": tick_status,
            "health": health_monitor.get_health(),
            "state": state_manager.get_state(),
            "scanner": scanner.get_status(),
        }


engine = TradingEngine()
