
import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from config import settings
from logging_config import get_logger

logger = get_logger("broker.exness_connection")


class ExnessConnection:
    """
    VROTEX BOT V1 — EXNESS CONNECTION

    Authenticated signed REST connection:
    - Account and Access Point verification
    - Existing market-data GET requests
    - Opening market positions
    - Placing pending orders
    - Updating and cancelling orders
    - Closing positions
    - Checking operation status
    - Retrieving trading snapshots

    Strategy and risk authorization remain upstream in Vrotex.
    """

    MAX_ATTEMPTS = 3
    BASE_RETRY_DELAY = 2
    MAX_RETRY_DELAY = 300

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    IDEMPOTENCY_KEY_PATTERN = re.compile(
        r"^[A-Za-z0-9._~-]{5,128}$"
    )

    def __init__(self):
        self.api_key = settings.EXN_API_KEY
        self.private_key_text = settings.EXN_PRIVATE_KEY
        self.account_id = str(settings.EXN_ACCOUNT_ID or "")
        self.gateway_host = (
            settings.EXN_GATEWAY_HOST or ""
        ).rstrip("/")

        self.access_point = None
        self.client = None
        self.connected = False
        self.account_info = None

        self.last_error = None
        self.last_successful_connection = None
        self.trading_requests_enabled = True
        self.last_trading_ack = None

    @staticmethod
    def b64url(data: bytes):
        return base64.urlsafe_b64encode(
            data
        ).decode().rstrip("=")

    @staticmethod
    def _json_bytes(body):
        if body is None:
            return b""

        if isinstance(body, bytes):
            return body

        return json.dumps(
            body,
            separators=(",", ":"),
            ensure_ascii=False
        ).encode("utf-8")

    @classmethod
    def _validate_idempotency_key(cls, key):
        if (
            not isinstance(key, str)
            or not cls.IDEMPOTENCY_KEY_PATTERN.fullmatch(key)
        ):
            raise ValueError(
                "A mutating Exness request requires an "
                "idempotency key of 5-128 characters."
            )

        return key

    def load_private_key(self):
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key,
        )

        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        key_text = self.private_key_text.strip()

        if key_text.startswith("-----BEGIN"):
            key = load_pem_private_key(
                key_text.encode(),
                password=None
            )

            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError(
                    "The configured PEM key is not an Ed25519 key."
                )

            return key

        # Exness hexadecimal private key format:
        # 128 hex characters = 64 bytes.
        if len(key_text) == 128:
            try:
                raw = bytes.fromhex(key_text)

                return Ed25519PrivateKey.from_private_bytes(
                    raw[:32]
                )

            except ValueError as exc:
                raise ValueError(
                    "Invalid hexadecimal private key"
                ) from exc

        # 32-byte Ed25519 seed = 64 hex characters.
        if len(key_text) == 64:
            try:
                raw = bytes.fromhex(key_text)

                return Ed25519PrivateKey.from_private_bytes(
                    raw
                )

            except ValueError as exc:
                raise ValueError(
                    "Invalid hexadecimal private key"
                ) from exc

        raise ValueError(
            "Unsupported private key format. "
            "Use Exness hexadecimal key or PEM format."
        )

    def sign_request(
        self,
        method,
        path,
        body=b"",
        idempotency_key=""
    ):
        method = method.upper()
        timestamp = int(time.time() * 1000)

        body_hash = self.b64url(
            hashlib.sha256(body).digest()
        )

        payload = {
            "api_key": self.api_key,
            "idempotency_key": idempotency_key,
            "timestamp": timestamp,
            "sign_version": 1,
            "method": method,
            "path": path,
            "body_hash": body_hash,
        }

        payload_bytes = json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False
        ).encode("utf-8")

        encoded_data = self.b64url(payload_bytes)

        signature = self.load_private_key().sign(
            payload_bytes
        )

        return {
            "EXN-API-KEY": self.api_key,
            "EXN-IDEMPOTENCY-KEY": idempotency_key,
            "EXN-TIMESTAMP": str(timestamp),
            "EXN-SIGN-VERSION": "1",
            "EXN-DATA": encoded_data,
            "EXN-SIGN": self.b64url(signature),
            "Accept": "application/json",
        }

    def _get_retry_after(self, response):
        value = response.headers.get("Retry-After")

        if not value:
            return None

        try:
            delay = float(value)

            return max(
                0,
                min(delay, self.MAX_RETRY_DELAY)
            )

        except ValueError:
            pass

        try:
            retry_date = parsedate_to_datetime(value)

            if retry_date.tzinfo is None:
                retry_date = retry_date.replace(
                    tzinfo=timezone.utc
                )

            delay = (
                retry_date - datetime.now(timezone.utc)
            ).total_seconds()

            return max(
                0,
                min(delay, self.MAX_RETRY_DELAY)
            )

        except Exception:
            return None

    def _retry_delay(self, attempt, response=None):
        if response is not None:
            server_delay = self._get_retry_after(response)

            if server_delay is not None:
                return server_delay

        delay = self.BASE_RETRY_DELAY * (2 ** attempt)

        return min(
            delay,
            self.MAX_RETRY_DELAY
        )

    async def _ensure_client(self):
        if self.client is None:
            timeout = httpx.Timeout(
                connect=15.0,
                read=30.0,
                write=30.0,
                pool=15.0,
            )

            limits = httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            )

            self.client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                follow_redirects=False,
            )

    async def signed_request(
        self,
        base_url,
        method,
        path,
        body=None,
        idempotency_key=""
    ):
        """
        Send an authenticated signed Exness REST request.

        GET requests use an empty idempotency key.
        Mutating requests require a stable caller-provided key.

        The same key and request body are retained across retries.
        """

        method = method.upper()

        if not path.startswith("/"):
            raise ValueError(
                "Exness request path must start with '/'."
            )

        if method == "GET":
            idempotency_key = ""
        else:
            idempotency_key = (
                self._validate_idempotency_key(
                    idempotency_key
                )
            )

        body_bytes = self._json_bytes(body)

        await self._ensure_client()

        for attempt in range(self.MAX_ATTEMPTS):
            headers = self.sign_request(
                method=method,
                path=path,
                body=body_bytes,
                idempotency_key=idempotency_key
            )

            if body is not None:
                headers["Content-Type"] = (
                    "application/json"
                )

            try:
                response = await self.client.request(
                    method=method,
                    url=(
                        f"{base_url.rstrip('/')}"
                        f"{path}"
                    ),
                    headers=headers,
                    content=(
                        body_bytes
                        if body is not None
                        else None
                    )
                )

            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as exc:

                if attempt >= self.MAX_ATTEMPTS - 1:
                    self.last_error = (
                        f"Network failure: "
                        f"{type(exc).__name__}"
                    )

                    raise RuntimeError(
                        "Exness network request failed "
                        "after retry attempts."
                    ) from exc

                delay = self._retry_delay(attempt)

                logger.warning(
                    "Exness network error (%s). "
                    "Retrying in %.1f seconds "
                    "(attempt %s/%s).",
                    type(exc).__name__,
                    delay,
                    attempt + 2,
                    self.MAX_ATTEMPTS
                )

                await self._sleep(delay)
                continue

            try:
                data = response.json()

            except ValueError:
                data = {
                    "raw_response": response.text
                }

            if (
                response.status_code
                in self.RETRYABLE_STATUS_CODES
            ):

                if attempt >= self.MAX_ATTEMPTS - 1:
                    self.last_error = (
                        f"HTTP {response.status_code}"
                    )

                    raise RuntimeError(
                        f"Exness API error "
                        f"{response.status_code}: "
                        f"{data}"
                    )

                delay = self._retry_delay(
                    attempt,
                    response=response
                )

                logger.warning(
                    "Exness returned HTTP %s. "
                    "Retrying in %.1f seconds "
                    "(attempt %s/%s).",
                    response.status_code,
                    delay,
                    attempt + 2,
                    self.MAX_ATTEMPTS
                )

                await self._sleep(delay)
                continue

            if response.status_code >= 400:
                self.last_error = (
                    f"HTTP {response.status_code}"
                )

                raise RuntimeError(
                    f"Exness API error "
                    f"{response.status_code}: "
                    f"{data}"
                )

            self.last_error = None

            return data

        raise RuntimeError(
            "Exness request exhausted retry attempts."
        )

    async def _sleep(self, seconds):
        import asyncio
        await asyncio.sleep(seconds)

    async def discover_access_point(self, force=False):
        if self.access_point and not force:
            logger.info(
                "Using cached Exness Access Point."
            )

            return self.access_point

        if not self.gateway_host:
            raise RuntimeError(
                "EXN_GATEWAY_HOST is missing"
            )

        query = urlencode({
            "account_id": self.account_id
        })

        path = (
            f"/v1/trading/access-point"
            f"?{query}"
        )

        logger.info(
            "Resolving Exness account Access Point."
        )

        result = await self.signed_request(
            self.gateway_host,
            "GET",
            path
        )

        access_point = result.get("access_point")

        if not access_point:
            raise RuntimeError(
                "Access Point missing from "
                "discovery response"
            )

        self.access_point = access_point.rstrip("/")

        logger.info(
            "Account Access Point resolved."
        )

        return self.access_point

    async def get_account_info(self):
        if not self.access_point:
            await self.discover_access_point()

        path = (
            f"/v1/configuration/accounts/"
            f"{self.account_id}/account"
        )

        return await self.signed_request(
            self.access_point,
            "GET",
            path
        )

    def _require_connected(self):
        if not self.connected or not self.access_point:
            raise RuntimeError(
                "Exness is not connected. "
                "Call await exness_connection.connect() first."
            )

    # ==========================================================
    # AUTHENTICATED TRADING METHODS
    # ==========================================================

    async def open_position(
        self,
        instrument,
        side,
        volume,
        idempotency_key,
        stop_loss_price=None,
        take_profit_price=None,
        price=None,
        deviation=None,
        comment=None,
    ):
        """
        Open a market position.

        side: buy or sell

        The caller must supply the same idempotency key when
        retrying the same trade request.
        """

        self._require_connected()

        instrument = str(instrument).strip().upper()
        side = str(side).strip().lower()

        if not instrument:
            raise ValueError("instrument is required")

        if side not in {"buy", "sell"}:
            raise ValueError(
                "side must be 'buy' or 'sell'"
            )

        body = {
            "instrument": instrument,
            "side": side,
            "volume": str(volume),
        }

        if price is not None:
            body["price"] = str(price)

        if deviation is not None:
            body["deviation"] = str(deviation)

        if stop_loss_price is not None:
            body["stop_loss_price"] = str(
                stop_loss_price
            )

        if take_profit_price is not None:
            body["take_profit_price"] = str(
                take_profit_price
            )

        if comment is not None:
            body["comment"] = str(comment)

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/positions"
        )

        result = await self.signed_request(
            self.access_point,
            "POST",
            path,
            body,
            idempotency_key
        )

        self.last_trading_ack = result

        return result

    async def place_pending_order(
        self,
        order_payload,
        idempotency_key,
    ):
        """Place a pending order."""

        self._require_connected()

        if (
            not isinstance(order_payload, dict)
            or not order_payload
        ):
            raise ValueError(
                "order_payload must be a non-empty dictionary"
            )

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/orders"
        )

        result = await self.signed_request(
            self.access_point,
            "POST",
            path,
            order_payload,
            idempotency_key
        )

        self.last_trading_ack = result

        return result

    async def update_order(
        self,
        order_id,
        update_payload,
        idempotency_key,
    ):
        """Modify an existing pending order."""

        self._require_connected()

        if not str(order_id).isdigit():
            raise ValueError("order_id must be numeric")

        if (
            not isinstance(update_payload, dict)
            or not update_payload
        ):
            raise ValueError(
                "update_payload must be a non-empty dictionary"
            )

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/orders/{order_id}"
        )

        result = await self.signed_request(
            self.access_point,
            "PATCH",
            path,
            update_payload,
            idempotency_key
        )

        self.last_trading_ack = result

        return result

    async def cancel_order(
        self,
        order_id,
        idempotency_key
    ):
        """Cancel an existing pending order."""

        self._require_connected()

        if not str(order_id).isdigit():
            raise ValueError("order_id must be numeric")

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/orders/{order_id}"
        )

        result = await self.signed_request(
            self.access_point,
            "DELETE",
            path,
            None,
            idempotency_key
        )

        self.last_trading_ack = result

        return result

    async def close_position(
        self,
        position_id,
        idempotency_key,
        volume=None,
        price=None,
        deviation=None,
    ):
        """Close a position fully or partially."""

        self._require_connected()

        if not str(position_id).isdigit():
            raise ValueError(
                "position_id must be numeric"
            )

        params = {}

        if volume is not None:
            params["volume"] = str(volume)

        if price is not None:
            params["price"] = str(price)

        if deviation is not None:
            params["deviation"] = str(deviation)

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/positions/{position_id}"
        )

        if params:
            path = f"{path}?{urlencode(params)}"

        result = await self.signed_request(
            self.access_point,
            "DELETE",
            path,
            None,
            idempotency_key
        )

        self.last_trading_ack = result

        return result

    async def get_operation_status(self, operation_id):
        """Check the final or pending status of an operation."""

        self._require_connected()

        if not str(operation_id).isdigit():
            raise ValueError(
                "operation_id must be numeric"
            )

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/operations/{operation_id}"
        )

        return await self.signed_request(
            self.access_point,
            "GET",
            path
        )

    async def get_trading_snapshot(self):
        """Retrieve the current trading account snapshot."""

        self._require_connected()

        path = (
            f"/v1/trading/accounts/"
            f"{self.account_id}/snapshot"
        )

        return await self.signed_request(
            self.access_point,
            "GET",
            path
        )

    # ==========================================================
    # CONNECTION
    # ==========================================================

    async def connect(self):
        if not self.api_key:
            raise RuntimeError(
                "EXN_API_KEY is missing"
            )

        if not self.private_key_text:
            raise RuntimeError(
                "EXN_PRIVATE_KEY is missing"
            )

        if not self.account_id:
            raise RuntimeError(
                "EXN_ACCOUNT_ID is missing"
            )

        if not self.gateway_host:
            raise RuntimeError(
                "EXN_GATEWAY_HOST is missing"
            )

        try:
            # Validate key locally before API requests.
            self.load_private_key()

            # Resolve account Access Point.
            await self.discover_access_point()

            # Verify account connectivity.
            self.account_info = (
                await self.get_account_info()
            )

            self.connected = True
            self.last_error = None

            self.last_successful_connection = (
                time.time()
            )

            logger.info(
                "Exness authenticated connection verified. "
                "Signed trading request methods are enabled."
            )

            return {
                "success": True,
                "connected": True,
                "trading_requests_enabled": (
                    self.trading_requests_enabled
                ),
                "account_id": self.account_id,
                "access_point": self.access_point,
                "account": self.account_info,
            }

        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)

            logger.exception(
                "Exness connection verification failed."
            )

            raise

    async def disconnect(self):
        self.connected = False

        if self.client is not None:
            await self.client.aclose()
            self.client = None

        logger.info(
            "Exness connection closed."
        )

    def get_connection_status(self):
        return {
            "connected": self.connected,
            "trading_requests_enabled": (
                self.trading_requests_enabled
            ),
            "account_id": self.account_id,
            "access_point_resolved": bool(
                self.access_point
            ),
            "last_error": self.last_error,
            "last_successful_connection": (
                self.last_successful_connection
            ),
            "last_trading_ack": self.last_trading_ack,
        }


exness_connection = ExnessConnection()
