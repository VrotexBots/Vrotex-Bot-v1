
import asyncio
from typing import Optional

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

        self.max_attempts = 3
        self.retry_delay = 2

    async def connect(self):

        async with self._lock:

            if self.connected and self.connection.connected:
                return {
                    "success": True,
                    "connected": True,
                    "message": "Already connected",
                }

            self.connecting = True
            self.last_error = None

            try:

                for attempt in range(1, self.max_attempts + 1):

                    try:

                        logger.info(
                            "Exness connection attempt %s/%s",
                            attempt,
                            self.max_attempts,
                        )

                        result = await self.connection.connect()

                        self.connected = True

                        self.account_info = result.get(
                            "account"
                        )

                        self.last_error = None

                        logger.info(
                            "Exness connector is connected."
                        )

                        return {
                            "success": True,
                            "connected": True,
                            "account_id": result.get(
                                "account_id"
                            ),
                            "message": "Connection successful",
                        }

                    except Exception as exc:

                        self.connected = False
                        self.last_error = str(exc)

                        logger.error(
                            "Connection attempt %s failed: %s",
                            attempt,
                            exc,
                        )

                        if attempt < self.max_attempts:

                            delay = (
                                self.retry_delay * attempt
                            )

                            logger.info(
                                "Retrying in %s seconds.",
                                delay,
                            )

                            await asyncio.sleep(delay)

                return {
                    "success": False,
                    "connected": False,
                    "message": "Connection failed",
                    "error": self.last_error,
                }

            finally:

                self.connecting = False

    async def reconnect(self):

        logger.warning(
            "Exness reconnection requested."
        )

        try:

            await self.connection.disconnect()

        except Exception as exc:

            logger.warning(
                "Disconnect before reconnect failed: %s",
                exc,
            )

        self.connected = False
        self.account_info = None

        return await self.connect()

    async def check_connection(self):

        if not self.connected:
            return False

        try:

            account = await self.connection.get_account_info()

            self.account_info = account

            self.connected = True

            return True

        except Exception as exc:

            logger.error(
                "Connection health check failed: %s",
                exc,
            )

            self.connected = False
            self.last_error = str(exc)

            return False

    async def get_account_info(self):

        if not self.connected:

            result = await self.connect()

            if not result.get("success"):
                raise ConnectionError(
                    "Exness connection unavailable"
                )

        account = await self.connection.get_account_info()

        self.account_info = account

        return account

    def get_status(self):

        return {
            "connected": self.connected,
            "connecting": self.connecting,
            "account_id": self.connection.account_id,
            "access_point_resolved": bool(
                self.connection.access_point
            ),
            "last_error": self.last_error,
        }

    async def disconnect(self):

        try:

            await self.connection.disconnect()

        finally:

            self.connected = False
            self.account_info = None

            logger.info(
                "Exness connector disconnected."
            )


exness_connector = ExnessConnector()
