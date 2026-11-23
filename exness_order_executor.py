
# exness_order_executor.py
# Vrotex Bot V1
# Autonomous Exness Order Execution
#
# Opens market positions, checks operation status,
# and verifies opened positions through Exness.

import asyncio
import hashlib
from decimal import Decimal, InvalidOperation

from logging_config import get_logger
from exness_connection import exness_connection


logger = get_logger("broker.exness_order_executor")


class ExnessOrderExecutor:

    VERSION = "2.1"

    ALLOWED_INSTRUMENTS = {
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    }

    MIN_SCORE = Decimal("85")

    POLL_INTERVAL = 2
    POLL_TIMEOUT = 30

    def __init__(self):

        self.connection = exness_connection

        self.auto_execution = True

        self.orders_submitted = 0
        self.orders_confirmed = 0
        self.orders_failed = 0
        self.orders_pending = 0

        self.last_order = None

        self.pending_orders = {}
        self.completed_orders = {}

        self._execution_lock = asyncio.Lock()

    # ==========================================================
    # GENERAL HELPERS
    # ==========================================================

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

    @staticmethod
    def _walk_dicts(value):

        if isinstance(value, dict):

            yield value

            for item in value.values():
                yield from ExnessOrderExecutor._walk_dicts(
                    item
                )

        elif isinstance(value, list):

            for item in value:
                yield from ExnessOrderExecutor._walk_dicts(
                    item
                )

    @staticmethod
    def _normalise_side(value):

        value = str(value or "").strip().lower()

        if value in ("buy", "long", "bullish"):
            return "buy"

        if value in ("sell", "short", "bearish"):
            return "sell"

        return None

    @staticmethod
    def _normalise_symbol(value):

        return str(value or "").strip().upper()

    @staticmethod
    def _extract_value(data, keys):

        for item in ExnessOrderExecutor._walk_dicts(data):

            for key in keys:

                value = item.get(key)

                if value is not None:
                    return value

        return None

    # ==========================================================
    # SETUP VALIDATION
    # ==========================================================

    def validate_setup(self, setup):

        if not isinstance(setup, dict):
            return False, "Invalid setup"

        if setup.get("execution_authorized") is not True:
            return False, "Master SMC authorization missing"

        if setup.get("approved") is False:
            return False, "Setup rejected upstream"

        score = self._decimal(
            setup.get(
                "score",
                setup.get("final_score"),
            )
        )

        if score is None or score < self.MIN_SCORE:
            return False, "Score below 85"

        instrument = self._normalise_symbol(
            setup.get(
                "instrument",
                setup.get("symbol"),
            )
        )

        if instrument not in self.ALLOWED_INSTRUMENTS:
            return False, f"Instrument not approved: {instrument}"

        side = self._normalise_side(
            setup.get(
                "side",
                setup.get("direction"),
            )
        )

        if side is None:
            return False, "Invalid trade direction"

        volume = self._decimal(setup.get("volume"))

        entry = self._decimal(
            setup.get(
                "entry_price",
                setup.get("entry"),
            )
        )

        sl = self._decimal(
            setup.get(
                "stop_loss_price",
                setup.get("sl"),
            )
        )

        tp = self._decimal(
            setup.get(
                "take_profit_price",
                setup.get("tp"),
            )
        )

        risk_percent = self._decimal(
            setup.get("risk_percent")
        )

        if volume is None or volume <= 0:
            return False, "Invalid volume"

        if entry is None or entry <= 0:
            return False, "Invalid entry price"

        if sl is None or sl <= 0:
            return False, "Invalid stop loss"

        if tp is None or tp <= 0:
            return False, "Invalid take profit"

        if risk_percent is None or risk_percent <= 0:
            return False, "Risk percentage missing"

        if risk_percent > Decimal("1"):
            return False, "Risk exceeds 1% per trade"

        if side == "buy":

            if not sl < entry < tp:
                return False, "Invalid BUY SL/TP placement"

        else:

            if not tp < entry < sl:
                return False, "Invalid SELL SL/TP placement"

        normalized = dict(setup)

        normalized.update({
            "instrument": instrument,
            "symbol": instrument,
            "side": side,
            "direction": side,
            "volume": str(volume),
            "entry_price": str(entry),
            "stop_loss_price": str(sl),
            "take_profit_price": str(tp),
            "risk_percent": str(risk_percent),
            "score": float(score),
        })

        return True, normalized

    # ==========================================================
    # RISK MANAGER
    # ==========================================================

    async def _check_risk(self, setup):

        try:

            from risk_manager import risk_manager

            global_result = risk_manager.can_trade()

            if isinstance(global_result, tuple):

                if global_result[0] is not True:

                    reason = (
                        global_result[1]
                        if len(global_result) > 1
                        else "Global risk rejected"
                    )

                    return False, str(reason)

            elif global_result is not True:

                return False, "Global risk limits rejected trade"

            validator = getattr(
                risk_manager,
                "validate_trade",
                None,
            )

            if not callable(validator):

                return False, "Risk Manager validator unavailable"

            result = validator(setup)

            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, tuple):

                allowed = result[0] is True

                reason = (
                    result[1]
                    if len(result) > 1
                    else "Trade risk rejected"
                )

                if not allowed:
                    return False, str(reason)

            elif isinstance(result, dict):

                allowed = any(
                    result.get(key) is True
                    for key in (
                        "allowed",
                        "approved",
                        "valid",
                        "success",
                        "passed",
                    )
                )

                if not allowed:
                    return False, {
                        "reason": "Trade risk rejected",
                        "risk_report": result,
                    }

            elif result is not True:

                return False, "Trade-specific risk rejected"

            return True, "Risk approved"

        except Exception as exc:

            logger.exception(
                "Risk Manager validation failed"
            )

            return False, (
                f"Risk Manager error: {type(exc).__name__}"
            )

    # ==========================================================
    # DEMO ACCOUNT IDENTIFICATION
    # ==========================================================

    def _verify_demo_account(self):

        account = self.connection.account_info

        if not isinstance(account, dict):
            return False, "Account information unavailable"

        demo_values = []
        account_types = []

        for item in self._walk_dicts(account):

            for key in (
                "is_demo",
                "demo",
                "demo_account",
            ):

                value = item.get(key)

                if isinstance(value, bool):
                    demo_values.append(value)

            for key in (
                "account_type",
                "accountType",
                "environment",
                "account_mode",
                "mode",
            ):

                value = item.get(key)

                if isinstance(value, str):
                    account_types.append(
                        value.strip().lower()
                    )

        demo_types = {
            "demo",
            "demo_account",
            "demo account",
            "practice",
            "paper",
        }

        live_types = {
            "real",
            "live",
            "live_account",
            "real_account",
            "real account",
        }

        if True in demo_values and False in demo_values:
            return False, "Conflicting account indicators"

        if any(value in live_types for value in account_types):
            return False, "Live account detected"

        if False in demo_values:
            return False, "Live account detected"

        if True in demo_values:
            return True, "Demo account verified"

        if any(value in demo_types for value in account_types):
            return True, "Demo account verified"

        return False, "Demo account type not identified"

    # ==========================================================
    # IDEMPOTENCY
    # ==========================================================

    def _create_request_id(self, setup):

        supplied_id = (
            setup.get("setup_id")
            or setup.get("signal_id")
            or setup.get("trade_id")
        )

        if supplied_id:

            identity = (
                f"{supplied_id}|"
                f"{setup['instrument']}|"
                f"{setup['side']}"
            )

        else:

            identity = "|".join((
                setup["instrument"],
                setup["side"],
                setup["volume"],
                setup["entry_price"],
                setup["stop_loss_price"],
                setup["take_profit_price"],
                str(setup["score"]),
            ))

        digest = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

        return f"vrotex-{digest[:48]}"

    # ==========================================================
    # OPEN MARKET POSITION
    # ==========================================================

    async def _submit_order(self, setup, request_id):

        """
        Submit an actual market position through the
        ExnessConnection.open_position() method.
        """

        response = await self.connection.open_position(
            instrument=setup["instrument"],
            side=setup["side"],
            volume=setup["volume"],
            idempotency_key=request_id,
            stop_loss_price=setup["stop_loss_price"],
            take_profit_price=setup["take_profit_price"],
            comment="Vrotex Bot V1",
        )

        if not isinstance(response, dict):
            raise RuntimeError(
                "Invalid Exness order response"
            )

        return response

    # ==========================================================
    # OPERATION STATUS
    # ==========================================================

    async def _check_operation(self, operation_id):

        if operation_id is None:
            return None

        operation_id = str(operation_id)

        if not operation_id.isdigit():
            return None

        try:

            return await self.connection.get_operation_status(
                operation_id
            )

        except Exception as exc:

            logger.warning(
                "Operation check failed: %s",
                type(exc).__name__,
            )

            return None

    @staticmethod
    def _operation_state(response):

        if not isinstance(response, dict):
            return "UNKNOWN"

        status = ExnessOrderExecutor._extract_value(
            response,
            (
                "status",
                "state",
                "operation_status",
            ),
        )

        if status is None:
            return "UNKNOWN"

        status = str(status).strip().lower()

        if status in (
            "confirmed",
            "success",
            "successful",
            "completed",
            "executed",
            "filled",
            "done",
        ):
            return "CONFIRMED"

        if status in (
            "rejected",
            "failed",
            "error",
            "cancelled",
            "canceled",
        ):
            return "FAILED"

        return "PENDING"

    # ==========================================================
    # POSITION IDENTIFICATION
    # ==========================================================

    def _find_open_position(self, snapshot, setup):

        """
        Find the actual matching position in the Exness
        trading snapshot.
        """

        if not isinstance(snapshot, (dict, list)):
            return None

        target_symbol = setup["instrument"]
        target_side = setup["side"]

        target_volume = self._decimal(
            setup["volume"]
        )

        for item in self._walk_dicts(snapshot):

            symbol = self._normalise_symbol(
                item.get(
                    "instrument",
                    item.get(
                        "symbol",
                        item.get("instrument_name"),
                    ),
                )
            )

            if symbol != target_symbol:
                continue

            raw_side = (
                item.get("side")
                or item.get("direction")
                or item.get("type")
            )

            side = self._normalise_side(raw_side)

            if side is None:
                continue

            if side != target_side:
                continue

            raw_volume = (
                item.get("volume")
                or item.get("lots")
                or item.get("quantity")
            )

            position_volume = self._decimal(raw_volume)

            if position_volume is None:
                continue

            if position_volume != target_volume:
                continue

            position_id = (
                item.get("position_id")
                or item.get("positionId")
                or item.get("id")
                or item.get("ticket")
            )

            if position_id is None:
                continue

            return item

        return None

    # ==========================================================
    # POSITION AND OPERATION CONFIRMATION
    # ==========================================================

    async def _verify_execution(
        self,
        setup,
        acknowledgement,
    ):

        operation_id = self._extract_value(
            acknowledgement,
            (
                "operation_id",
                "operationId",
            ),
        )

        started = 0

        while started < self.POLL_TIMEOUT:

            operation_response = None

            if operation_id is not None:

                operation_response = (
                    await self._check_operation(
                        operation_id
                    )
                )

            operation_state = self._operation_state(
                operation_response
            )

            if operation_state == "FAILED":

                return {
                    "status": "FAILED",
                    "operation_id": operation_id,
                    "operation": operation_response,
                }

            try:

                snapshot = (
                    await self.connection.get_trading_snapshot()
                )

                position = self._find_open_position(
                    snapshot,
                    setup,
                )

                if position is not None:

                    return {
                        "status": "CONFIRMED",
                        "operation_id": operation_id,
                        "operation": operation_response,
                        "position": position,
                        "position_id": (
                            position.get("position_id")
                            or position.get("positionId")
                            or position.get("id")
                            or position.get("ticket")
                        ),
                    }

            except Exception as exc:

                logger.warning(
                    "Position verification failed: %s",
                    type(exc).__name__,
                )

            await asyncio.sleep(self.POLL_INTERVAL)

            started += self.POLL_INTERVAL

        return {
            "status": "PENDING",
            "operation_id": operation_id,
            "reason": (
                "Waiting for Exness position confirmation"
            ),
        }

    # ==========================================================
    # EXECUTION
    # ==========================================================

    async def execute(self, setup):

        async with self._execution_lock:

            if not self.auto_execution:

                return {
                    "success": False,
                    "status": "DISABLED",
                }

            valid, normalized = self.validate_setup(setup)

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
                    "reason": "Exness Access Point unavailable",
                }

            demo_ok, demo_reason = (
                self._verify_demo_account()
            )

            if not demo_ok:

                return {
                    "success": False,
                    "status": "REJECTED",
                    "reason": demo_reason,
                }

            risk_allowed, risk_reason = (
                await self._check_risk(normalized)
            )

            if not risk_allowed:

                return {
                    "success": False,
                    "status": "REJECTED",
                    "reason": risk_reason,
                }

            request_id = self._create_request_id(
                normalized
            )

            if request_id in self.completed_orders:

                return self.completed_orders[request_id]

            if request_id in self.pending_orders:

                return self.pending_orders[request_id]

            logger.warning(
                "OPENING EXNESS DEMO POSITION | "
                "%s %s | Volume=%s | Score=%s",
                normalized["side"].upper(),
                normalized["instrument"],
                normalized["volume"],
                normalized["score"],
            )

            try:

                acknowledgement = await self._submit_order(
                    normalized,
                    request_id,
                )

                self.orders_submitted += 1

                result = {
                    "success": False,
                    "status": "SUBMITTED",
                    "request_id": request_id,
                    "instrument": normalized["instrument"],
                    "side": normalized["side"],
                    "volume": normalized["volume"],
                    "entry_price": normalized["entry_price"],
                    "stop_loss_price": normalized["stop_loss_price"],
                    "take_profit_price": normalized["take_profit_price"],
                    "score": normalized["score"],
                    "acknowledgement": acknowledgement,
                }

                self.last_order = result

                verification = await self._verify_execution(
                    normalized,
                    acknowledgement,
                )

                result["verification"] = verification

                result["status"] = verification["status"]

                if result["status"] == "CONFIRMED":

                    result["success"] = True

                    self.orders_confirmed += 1

                    self.completed_orders[request_id] = result

                    self.pending_orders.pop(
                        request_id,
                        None,
                    )

                    logger.info(
                        "EXNESS POSITION OPENED AND CONFIRMED | "
                        "%s | %s | Position ID=%s",
                        normalized["instrument"],
                        normalized["side"].upper(),
                        verification.get("position_id"),
                    )

                elif result["status"] == "FAILED":

                    self.orders_failed += 1

                    self.pending_orders.pop(
                        request_id,
                        None,
                    )

                    logger.error(
                        "EXNESS ORDER FAILED | %s",
                        request_id,
                    )

                else:

                    self.orders_pending += 1

                    self.pending_orders[request_id] = result

                    logger.warning(
                        "EXNESS ORDER AWAITING POSITION "
                        "CONFIRMATION | %s",
                        request_id,
                    )

                self.last_order = result

                return result

            except Exception as exc:

                logger.exception(
                    "Exness order execution error"
                )

                # The request may have reached Exness before
                # a network error occurred. Preserve its ID.
                result = {
                    "success": False,
                    "status": "ERROR",
                    "request_id": request_id,
                    "instrument": normalized["instrument"],
                    "side": normalized["side"],
                    "reason": str(exc),
                    "reconciliation_required": True,
                }

                self.pending_orders[request_id] = result
                self.last_order = result

                return result

    # ==========================================================
    # PENDING ORDER RECONCILIATION
    # ==========================================================

    async def reconcile_pending(self):

        results = []

        for request_id, previous in list(
            self.pending_orders.items()
        ):

            setup = {
                "instrument": previous.get("instrument"),
                "side": previous.get("side"),
                "volume": previous.get("volume"),
            }

            # Recover the full setup from the original order
            # when available.
            full_setup = previous.get("_setup")

            if isinstance(full_setup, dict):
                setup = full_setup

            else:
                continue

            try:

                acknowledgement = previous.get(
                    "acknowledgement",
                    {},
                )

                verification = await self._verify_execution(
                    setup,
                    acknowledgement,
                )

                previous["verification"] = verification
                previous["status"] = verification["status"]

                if verification["status"] == "CONFIRMED":

                    previous["success"] = True

                    self.orders_confirmed += 1

                    self.completed_orders[request_id] = previous

                    self.pending_orders.pop(
                        request_id,
                        None,
                    )

                elif verification["status"] == "FAILED":

                    self.orders_failed += 1

                    self.pending_orders.pop(
                        request_id,
                        None,
                    )

                results.append(previous)

            except Exception:

                logger.exception(
                    "Pending order reconciliation failed"
                )

        return results

    # ==========================================================
    # STATUS
    # ==========================================================

    def get_status(self):

        return {
            "version": self.VERSION,
            "autonomous_execution": self.auto_execution,
            "demo_only": True,
            "orders_submitted": self.orders_submitted,
            "orders_confirmed": self.orders_confirmed,
            "orders_failed": self.orders_failed,
            "orders_pending": len(self.pending_orders),
            "last_order": self.last_order,
        }


exness_order_executor = ExnessOrderExecutor()
