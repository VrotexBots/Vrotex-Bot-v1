import asyncio
import time

from logging_config import get_logger
from exness_connection import exness_connection


logger = get_logger("exness_connector")


class ExnessConnector:

    def __init__(self):

        self.connection = exness_connection

        self.connected = False
        self.connecting = False

        self.account_info = None
        self.last_error = None

        self._lock = asyncio.Lock()

        # Lower-level connection owns HTTP retries.
        self.max_attempts = 1

        self.retry_delay = 2
        self.cooldown_seconds = 60
        self.rate_limit_cooldown_seconds = 120

        self.next_retry_time = 0
        self.last_connect_attempt = 0
        self.last_success_time = 0

    # --------------------------------------------------
    # RESPONSE FORMAT
    # --------------------------------------------------

    def _response(
        self,
        success,
        error=None,
    ):

        return {
            "success": bool(success),
            "connected": self.connected,
            "error": error,
            "account_info": self.account_info,
        }

    # --------------------------------------------------
    # RATE LIMIT DETECTION
    # --------------------------------------------------

    def _is_rate_limit_error(self, error=None):

        error_text = str(
            error or self.last_error or ""
        ).lower()

        return (
            "429" in error_text
            or "rate limit" in error_text
            or "too many requests" in error_text
        )

    # --------------------------------------------------
    # COOLDOWN
    # --------------------------------------------------

    def _set_cooldown(self, error=None):

        if self._is_rate_limit_error(error):

            cooldown = (
                self.rate_limit_cooldown_seconds
            )

        else:

            cooldown = self.cooldown_seconds

        self.next_retry_time = (
            time.monotonic() + cooldown
        )

    def _cooldown_remaining(self):

        remaining = (
            self.next_retry_time
            - time.monotonic()
        )

        return max(
            0,
            int(remaining),
        )

    # --------------------------------------------------
    # CONNECT
    # --------------------------------------------------

    async def connect(self, force=False):

        async with self._lock:

            if self.connected:

                return self._response(
                    success=True,
                )

            if self.connecting:

                return self._response(
                    success=False,
                    error="Connection already in progress",
                )

            if (
                not force
                and time.monotonic()
                < self.next_retry_time
            ):

                remaining = (
                    self._cooldown_remaining()
                )

                error = (
                    "Connection cooldown active. "
                    f"Retry in {remaining} seconds."
                )

                logger.warning(error)

                return self._response(
                    success=False,
                    error=error,
                )

            self.connecting = True

            self.last_connect_attempt = (
                time.time()
            )

            try:

                logger.info(
                    "Connecting to Exness..."
                )

                # HTTP retry logic remains in
                # exness_connection.py.
                result = await (
                    self.connection.connect()
                )

                # Support either a bool or a
                # dictionary from lower-level code.
                if isinstance(result, dict):

                    success = bool(
                        result.get("success", False)
                    )

                    error = result.get("error")

                else:

                    success = bool(result)

                    error = None

                if success:

                    self.connected = True
                    self.last_error = None
                    self.next_retry_time = 0

                    self.last_success_time = (
                        time.time()
                    )

                    logger.info(
                        "Exness connection successful."
                    )

                    return self._response(
                        success=True,
                    )

                self.connected = False

                self.last_error = (
                    error
                    or getattr(
                        self.connection,
                        "last_error",
                        None,
                    )
                    or "Exness connection failed"
                )

                self._set_cooldown(
                    self.last_error
                )

                logger.error(
                    "Exness connection failed: %s",
                    self.last_error,
                )

                return self._response(
                    success=False,
                    error=self.last_error,
                )

            except Exception as exc:

                self.connected = False
                self.last_error = str(exc)

                self._set_cooldown(exc)

                logger.exception(
                    "Exness connector error."
                )

                return self._response(
                    success=False,
                    error=self.last_error,
                )

            finally:

                self.connecting = False

    # --------------------------------------------------
    # DISCONNECT
    # --------------------------------------------------

    async def disconnect(self):

        async with self._lock:

            try:

                if hasattr(
                    self.connection,
                    "disconnect",
                ):

                    await (
                        self.connection.disconnect()
                    )

            except Exception as exc:

                logger.warning(
                    "Error during Exness disconnect: %s",
                    exc,
                )

            self.connected = False
            self.connecting = False

            logger.info(
                "Exness disconnected."
            )

            return True

    # --------------------------------------------------
    # CONNECTION CHECK
    # --------------------------------------------------

    async def check_connection(
        self,
        refresh_account=False,
    ):

        if not self.connected:

            return False

        if not refresh_account:

            return True

        try:

            account = await (
                self.connection.get_account_info()
            )

            if account:

                self.account_info = account

                self.last_success_time = (
                    time.time()
                )

                return True

            self.connected = False

            self.last_error = getattr(
                self.connection,
                "last_error",
                "Account verification failed",
            )

            self._set_cooldown(
                self.last_error
            )

            return False

        except Exception as exc:

            self.connected = False
            self.last_error = str(exc)

            self._set_cooldown(exc)

            logger.error(
                "Exness connection check failed: %s",
                exc,
            )

            return False

    # --------------------------------------------------
    # ACCOUNT INFORMATION
    # --------------------------------------------------

    async def get_account_info(self):

        if not self.connected:

            result = await self.connect()

            if not result.get("success"):

                return None

        try:

            account = await (
                self.connection.get_account_info()
            )

            if account:

                self.account_info = account
                self.last_error = None

                self.last_success_time = (
                    time.time()
                )

                return account

            self.connected = False

            self.last_error = getattr(
                self.connection,
                "last_error",
                "Account information unavailable",
            )

            self._set_cooldown(
                self.last_error
            )

            return None

        except Exception as exc:

            self.connected = False
            self.last_error = str(exc)

            self._set_cooldown(exc)

            logger.exception(
                "Failed to retrieve Exness account information."
            )

            return None

    # --------------------------------------------------
    # RECONNECT
    # --------------------------------------------------

    async def reconnect(self):

        logger.warning(
            "Manual Exness reconnect requested."
        )

        await self.disconnect()

        # Explicit reconnect bypasses cooldown.
        return await self.connect(
            force=True,
        )

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_status(self):

        return {
            "connected": self.connected,
            "connecting": self.connecting,
            "account_info": self.account_info,
            "last_error": self.last_error,
            "last_connect_attempt": (
                self.last_connect_attempt
            ),
            "last_success_time": (
                self.last_success_time
            ),
            "retry_after": (
                self._cooldown_remaining()
            ),
        }


exness_connector = ExnessConnector()
