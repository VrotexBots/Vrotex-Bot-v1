
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

        # The lower-level connection handles HTTP retries.
        # Do not add another retry loop here.
        self.max_attempts = 1

        self.retry_delay = 2
        self.cooldown_seconds = 60
        self.rate_limit_cooldown_seconds = 120

        self.next_retry_time = 0
        self.last_connect_attempt = 0
        self.last_success_time = 0

    def _is_rate_limit_error(self, error=None):

        error_text = str(error or self.last_error or "").lower()

        return (
            "429" in error_text
            or "rate limit" in error_text
            or "too many requests" in error_text
        )

    def _set_cooldown(self, error=None):

        if self._is_rate_limit_error(error):

            cooldown = self.rate_limit_cooldown_seconds

        else:

            cooldown = self.cooldown_seconds

        self.next_retry_time = time.monotonic() + cooldown

    def _cooldown_remaining(self):

        remaining = self.next_retry_time - time.monotonic()

        return max(0, int(remaining))

    async def connect(self, force=False):

        async with self._lock:

            if self.connected:

                return True

            if self.connecting:

                return False

            if not force and time.monotonic() < self.next_retry_time:

                remaining = self._cooldown_remaining()

                logger.warning(
                    "Exness connection cooldown active. "
                    "Retry in %s seconds.",
                    remaining,
                )

                return False

            self.connecting = True
            self.last_connect_attempt = time.time()

            try:

                logger.info("Connecting to Exness...")

                # Lower-level connection owns its HTTP retry policy.
                result = await self.connection.connect()

                if result:

                    self.connected = True
                    self.last_error = None
                    self.next_retry_time = 0
                    self.last_success_time = time.time()

                    logger.info("Exness connection successful.")

                    return True

                self.connected = False

                self.last_error = getattr(
                    self.connection,
                    "last_error",
                    None,
                )

                self._set_cooldown(self.last_error)

                logger.error(
                    "Exness connection failed: %s",
                    self.last_error,
                )

                return False

            except Exception as exc:

                self.connected = False
                self.last_error = str(exc)

                self._set_cooldown(exc)

                logger.exception("Exness connector error.")

                return False

            finally:

                self.connecting = False

    async def disconnect(self):

        async with self._lock:

            try:

                if hasattr(self.connection, "disconnect"):

                    await self.connection.disconnect()

            except Exception as exc:

                logger.warning(
                    "Error during Exness disconnect: %s",
                    exc,
                )

            self.connected = False
            self.connecting = False

            logger.info("Exness disconnected.")

            return True

    async def check_connection(self, refresh_account=False):

        # Lightweight health check.
        # No API request unless explicitly requested.

        if not self.connected:

            return False

        if not refresh_account:

            return True

        try:

            account = await self.connection.get_account_info()

            if account:

                self.account_info = account
                self.last_success_time = time.time()

                return True

            self.connected = False

            self.last_error = getattr(
                self.connection,
                "last_error",
                "Account verification failed",
            )

            self._set_cooldown(self.last_error)

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

    async def get_account_info(self):

        if not self.connected:

            success = await self.connect()

            if not success:

                return None

        try:

            account = await self.connection.get_account_info()

            if account:

                self.account_info = account
                self.last_error = None
                self.last_success_time = time.time()

                return account

            self.connected = False

            self.last_error = getattr(
                self.connection,
                "last_error",
                "Account information unavailable",
            )

            self._set_cooldown(self.last_error)

            return None

        except Exception as exc:

            self.connected = False
            self.last_error = str(exc)

            self._set_cooldown(exc)

            logger.exception(
                "Failed to retrieve Exness account information."
            )

            return None

    async def reconnect(self):

        logger.warning("Manual Exness reconnect requested.")

        await self.disconnect()

        # Explicit reconnect bypasses cooldown.
        return await self.connect(force=True)

    def get_status(self):

        return {
            "connected": self.connected,
            "connecting": self.connecting,
            "account_info": self.account_info,
            "last_error": self.last_error,
            "last_connect_attempt": self.last_connect_attempt,
            "last_success_time": self.last_success_time,
            "retry_after": self._cooldown_remaining(),
        }


exness_connector = ExnessConnector()
