import base64
import hashlib
import json
import time
from urllib.parse import urlencode

import httpx

from config import settings
from logging_config import get_logger

logger = get_logger("broker.exness_connection")


class ExnessConnection:

    def __init__(self):

        self.api_key = settings.EXN_API_KEY
        self.private_key_text = settings.EXN_PRIVATE_KEY
        self.account_id = settings.EXN_ACCOUNT_ID
        self.gateway_host = settings.EXN_GATEWAY_HOST.rstrip("/")

        self.access_point = None
        self.client = None
        self.connected = False
        self.account_info = None

    @staticmethod
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    def load_private_key(self):

        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key,
        )
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        key_text = self.private_key_text.strip()

        if key_text.startswith("-----BEGIN"):
            return load_pem_private_key(
                key_text.encode(),
                password=None
            )

        # Exness-generated private key format:
        # 128 hex characters = 64 bytes.
        if len(key_text) == 128:

            try:
                raw = bytes.fromhex(key_text)

                # Ed25519 uses the 32-byte seed.
                return Ed25519PrivateKey.from_private_bytes(
                    raw[:32]
                )

            except ValueError as exc:
                raise ValueError(
                    "Invalid hexadecimal private key"
                ) from exc

        # A 32-byte seed represented as 64 hex characters.
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

        private_key = self.load_private_key()

        signature = private_key.sign(payload_bytes)

        encoded_signature = self.b64url(signature)

        return {
            "EXN-API-KEY": self.api_key,
            "EXN-IDEMPOTENCY-KEY": idempotency_key,
            "EXN-TIMESTAMP": str(timestamp),
            "EXN-SIGN-VERSION": "1",
            "EXN-DATA": encoded_data,
            "EXN-SIGN": encoded_signature,
            "Accept": "application/json",
        }

    async def signed_request(
        self,
        base_url,
        method,
        path,
        body=None
    ):

        method = method.upper()

        if body is None:
            body_bytes = b""
        else:
            body_bytes = json.dumps(
                body,
                separators=(",", ":"),
                ensure_ascii=False
            ).encode("utf-8")

        idempotency_key = ""

        headers = self.sign_request(
            method=method,
            path=path,
            body=body_bytes,
            idempotency_key=idempotency_key
        )

        if body is not None:
            headers["Content-Type"] = "application/json"

        if self.client is None:

            self.client = httpx.AsyncClient(
                timeout=30,
                follow_redirects=False
            )

        response = await self.client.request(
            method=method,
            url=f"{base_url.rstrip('/')}{path}",
            headers=headers,
            content=body_bytes if body is not None else None
        )

        try:
            data = response.json()
        except ValueError:
            data = {"raw_response": response.text}

        if response.status_code >= 400:

            raise RuntimeError(
                f"Exness API error "
                f"{response.status_code}: {data}"
            )

        return data

    async def discover_access_point(self):

        if not self.gateway_host:
            raise RuntimeError(
                "EXN_GATEWAY_HOST is missing"
            )

        query = urlencode({
            "account_id": self.account_id
        })

        path = f"/v1/trading/access-point?{query}"

        logger.info("Resolving Exness account Access Point.")

        result = await self.signed_request(
            self.gateway_host,
            "GET",
            path
        )

        access_point = result.get("access_point")

        if not access_point:
            raise RuntimeError(
                "Access Point missing from discovery response"
            )

        self.access_point = access_point.rstrip("/")

        logger.info("Account Access Point resolved.")

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

    async def connect(self):

        if not self.api_key:
            raise RuntimeError("EXN_API_KEY is missing")

        if not self.private_key_text:
            raise RuntimeError("EXN_PRIVATE_KEY is missing")

        if not self.account_id:
            raise RuntimeError("EXN_ACCOUNT_ID is missing")

        if not self.gateway_host:
            raise RuntimeError("EXN_GATEWAY_HOST is missing")

        try:

            # Validate the private key locally first.
            self.load_private_key()

            # Resolve the account's correct API host.
            await self.discover_access_point()

            # Read-only account verification.
            self.account_info = await self.get_account_info()

            self.connected = True

            logger.info(
                "Exness connection verified successfully."
            )

            return {
                "connected": True,
                "account_id": self.account_id,
                "access_point": self.access_point,
                "account": self.account_info,
            }

        except Exception:

            self.connected = False

            logger.exception(
                "Exness connection verification failed."
            )

            raise

    async def disconnect(self):

        self.connected = False

        if self.client is not None:

            await self.client.aclose()

            self.client = None

        logger.info("Exness connection closed.")

    def get_connection_status(self):

        return {
            "connected": self.connected,
            "account_id": self.account_id,
            "access_point_resolved": bool(self.access_point),
        }


exness_connection = ExnessConnection()
