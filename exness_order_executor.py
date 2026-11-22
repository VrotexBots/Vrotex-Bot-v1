
# exness_order_executor.py
# Vrotex Bot V1
# Autonomous Broker Execution

import asyncio
import uuid
from decimal import Decimal, InvalidOperation

from logging_config import get_logger
from exness_connection import exness_connection


logger = get_logger("broker.exness_order_executor")


class ExnessOrderExecutor:

    VERSION = "1.1"

    ALLOWED_INSTRUMENTS = {
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    }

    MIN_SCORE = 85

    POLL_INTERVAL = 2
    POLL_TIMEOUT = 30

    def __init__(self):

        self.connection = exness_connection

        # Autonomous execution is enabled.
        self.auto_execution = True

        self.orders_submitted = 0
        self.orders_confirmed = 0
        self.orders_failed = 0

        self.last_order = None
        self.pending_orders = {}

    @staticmethod
    def _decimal(value):

        try:

            number = Decimal(str(value))

            if not number.is_finite():
                return None

            return number

        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):

            return None

    def validate_setup(self, setup):

        if not isinstance(setup, dict):

            return False, "Invalid setup"

        # Master SMC authorization is mandatory.
        if not setup.get(
            "execution_authorized",
            False
        ):

            return False, (
                "Master SMC authorization missing"
            )

        if setup.get("approved") is not True:

            return False, "Setup not approved"

        score = self._decimal(
            setup.get("score")
        )

        if score is None or score < self.MIN_SCORE:

            return False, "Score below 85"

        instrument = str(
            setup.get(
                "instrument",
                setup.get("symbol", "")
            )
        ).upper()

        if instrument not in self.ALLOWED_INSTRUMENTS:

            return False, (
                f"Instrument not approved: {instrument}"
            )

        side = str(
            setup.get(
                "side",
                setup.get("direction", "")
            )
        ).lower()

        if side in (
            "buy",
            "long",
            "bullish",
        ):

            side = "buy"

        elif side in (
            "sell",
            "short",
            "bearish",
        ):

            side = "sell"

        else:

            return False, "Invalid direction"

        volume = self._decimal(
            setup.get("volume")
        )

        entry = self._decimal(
            setup.get("entry_price")
        )

        sl = self._decimal(
            setup.get(
                "stop_loss_price",
                setup.get("sl")
            )
        )

        tp = self._decimal(
            setup.get(
                "take_profit_price",
                setup.get("tp")
            )
        )

        if volume is None or volume <= 0:

            return False, "Invalid volume"

        if entry is None or entry <= 0:

            return False, "Invalid entry price"

        if sl is None or sl <= 0:

            return False, "Invalid stop loss"

        if tp is None or tp <= 0:

            return False, "Invalid take profit"

        if side == "buy":

            if not sl < entry < tp:

                return False, (
                    "Invalid BUY SL/TP placement"
                )

        else:

            if not tp < entry < sl:

                return False, (
                    "Invalid SELL SL/TP placement"
                )

        return True, {
            "instrument": instrument,
            "side": side,
            "volume": str(volume),
            "entry_price": str(entry),
            "stop_loss_price": str(sl),
            "take_profit_price": str(tp),
            "score": float(score),
        }

    async def _check_risk(self):

        try:

            from risk_manager import risk_manager

            result = risk_manager.can_trade()

            if isinstance(result, tuple):

                allowed, reason = result

                return bool(allowed), reason

            return bool(result), (
                "Risk approved"
                if result
                else "Risk rejected"
            )

        except Exception as exc:

            logger.exception(
                "Risk manager validation error"
            )

            return False, (
                f"Risk validation error: "
                f"{type(exc).__name__}"
            )

    async def _submit(self, setup, request_id):

        path = (
            f"/v1/trading/accounts/"
            f"{self.connection.account_id}"
            f"/positions"
        )

        payload = {
            "instrument": setup["instrument"],
            "side": setup["side"],
            "volume": setup["volume"],
            "stop_loss_price": (
                setup["stop_loss_price"]
            ),
            "take_profit_price": (
                setup["take_profit_price"]
            ),
            "comment": "Vrotex Bot V1",
        }

        return await self.connection.signed_request(
            self.connection.access_point,
            "POST",
            path,
            body=payload,
            idempotency_key=request_id,
        )

    async def _poll_operation(self, operation_id):

        path = (
            f"/v1/trading/accounts/"
            f"{self.connection.account_id}"
            f"/operations/{operation_id}"
        )

        elapsed = 0

        while elapsed < self.POLL_TIMEOUT:

            try:

                response = (
                    await self.connection.signed_request(
                        self.connection.access_point,
                        "GET",
                        path,
                    )
                )

            except Exception as exc:

                logger.warning(
                    "Operation status unavailable: %s",
                    type(exc).__name__,
                )

                await asyncio.sleep(
                    self.POLL_INTERVAL
                )

                elapsed += self.POLL_INTERVAL

                continue

            status = str(
                response.get("status", "")
            ).lower()

            if status in (
                "confirmed",
                "success",
                "successful",
                "completed",
            ):

                return {
                    "status": "CONFIRMED",
                    "response": response,
                }

            if status in (
                "rejected",
                "failed",
                "error",
            ):

                return {
                    "status": "FAILED",
                    "response": response,
                }

            await asyncio.sleep(
                self.POLL_INTERVAL
            )

            elapsed += self.POLL_INTERVAL

        return {
            "status": "PENDING",
            "operation_id": operation_id,
        }

    async def execute(self, setup):

        """
        Autonomous execution.

        No manual trade approval.
        No hardcoded demo-only mode restriction.

        Master SMC and Risk Manager remain
        responsible for setup authorization.
        """

        if not self.auto_execution:

            return {
                "success": False,
                "status": "DISABLED",
            }

        valid, normalized = (
            self.validate_setup(setup)
        )

        if not valid:

            return {
                "success": False,
                "status": "REJECTED",
                "reason": normalized,
            }

        if not self.connection.connected:

            return {
                "success": False,
                "status": "REJECTED",
                "reason": "Exness connection unavailable",
            }

        if not self.connection.access_point:

            return {
                "success": False,
                "status": "REJECTED",
                "reason": "Exness access point unresolved",
            }

        risk_allowed, risk_reason = (
            await self._check_risk()
        )

        if not risk_allowed:

            return {
                "success": False,
                "status": "REJECTED",
                "reason": risk_reason,
            }

        # Unique identifier for this order.
        request_id = (
            f"vrotex-{uuid.uuid4().hex}"
        )

        logger.warning(
            "AUTONOMOUS ORDER | %s %s | "
            "Volume=%s | Score=%s",
            normalized["side"].upper(),
            normalized["instrument"],
            normalized["volume"],
            normalized["score"],
        )

        try:

            acknowledgement = await self._submit(
                normalized,
                request_id,
            )

            self.orders_submitted += 1

            operation_id = (
                acknowledgement.get(
                    "operation_id"
                )
            )

            result = {
                "success": True,
                "status": "ACKNOWLEDGED",
                "request_id": request_id,
                "operation_id": operation_id,
                "instrument": normalized["instrument"],
                "side": normalized["side"],
                "volume": normalized["volume"],
                "acknowledgement": acknowledgement,
            }

            if not operation_id:

                result["status"] = "PENDING"

                result["reason"] = (
                    "Acknowledged but operation ID "
                    "not returned. Reconciliation required."
                )

                self.pending_orders[request_id] = result

                self.last_order = result

                return result

            confirmation = (
                await self._poll_operation(
                    operation_id
                )
            )

            result["confirmation"] = confirmation

            result["status"] = (
                confirmation["status"]
            )

            if result["status"] == "CONFIRMED":

                self.orders_confirmed += 1

            elif result["status"] == "FAILED":

                self.orders_failed += 1

            else:

                self.pending_orders[request_id] = result

            self.last_order = result

            logger.info(
                "Execution result: %s | %s",
                result["status"],
                operation_id,
            )

            return result

        except Exception as exc:

            logger.exception(
                "Order execution failure"
            )

            result = {
                "success": False,
                "status": "ERROR",
                "request_id": request_id,
                "reason": str(exc),
            }

            self.last_order = result

            return result

    def get_status(self):

        return {
            "version": self.VERSION,
            "autonomous_execution": (
                self.auto_execution
            ),
            "orders_submitted": (
                self.orders_submitted
            ),
            "orders_confirmed": (
                self.orders_confirmed
            ),
            "orders_failed": (
                self.orders_failed
            ),
            "pending_orders": (
                len(self.pending_orders)
            ),
            "last_order": self.last_order,
        }


exness_order_executor = ExnessOrderExecutor()
