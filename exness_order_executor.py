
# exness_order_executor.py
# Vrotex Bot V1
# Autonomous Exness Order Execution
#
# Opens market positions, checks operation status,
# verifies opened positions, and registers confirmed
# positions with Trade Manager.

import asyncio
import hashlib
from decimal import Decimal, InvalidOperation

from logging_config import get_logger
from exness_connection import exness_connection


logger = get_logger("broker.exness_order_executor")


class ExnessOrderExecutor:

    VERSION = "2.3"

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

        strategy = str(setup.get("strategy", "SMC")).strip().upper()
        if strategy not in ("SMC", "ORB"):
            return False, f"Unsupported strategy: {strategy}"

        if strategy == "ORB":
            # ORB uses its own Central Authorization + shared Risk route.
            # It must never be forced through Master SMC scoring.
            if setup.get("strategy_authorized") is not True:
                return False, "ORB central strategy authorization missing"
            if setup.get("risk_approved") is not True:
                return False, "ORB shared Risk Manager approval missing"
            if setup.get("execution_authorized") is not True:
                return False, "ORB final execution authorization missing"

            risk_result = setup.get("risk")
            if not isinstance(risk_result, dict):
                return False, "ORB shared risk result missing"
            if risk_result.get("risk_approved") is not True:
                return False, "ORB shared risk result not approved"
            if risk_result.get("position_size_required") is True:
                return False, "ORB broker-based position size still required"
            risk_volume = self._decimal(risk_result.get("volume_lots"))
            supplied_volume = self._decimal(setup.get("volume"))
            if risk_volume is None or supplied_volume is None:
                return False, "ORB verified position volume missing"
            if risk_volume != supplied_volume:
                return False, "ORB volume does not match shared Risk Manager sizing"

        else:
            # Preserve the existing Master SMC authorization and A+ threshold.
            if setup.get("execution_authorized") is not True:
                return False, "Master SMC authorization missing"

            score = self._decimal(
                setup.get("score", setup.get("final_score"))
            )
            if score is None or score < self.MIN_SCORE:
                return False, "Score below 85"

        if setup.get("approved") is False:
            return False, "Setup rejected upstream"

        instrument = self._normalise_symbol(
            setup.get("instrument", setup.get("symbol"))
        )
        if instrument not in self.ALLOWED_INSTRUMENTS:
            return False, f"Instrument not approved: {instrument}"

        side = self._normalise_side(
            setup.get("side", setup.get("direction"))
        )
        if side is None:
            return False, "Invalid trade direction"

        volume = self._decimal(setup.get("volume"))
        entry = self._decimal(setup.get("entry_price", setup.get("entry")))
        sl = self._decimal(setup.get("stop_loss_price", setup.get("sl")))
        tp = self._decimal(setup.get("take_profit_price", setup.get("tp")))
        risk_percent = self._decimal(setup.get("risk_percent"))

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
            "strategy": strategy,
            "instrument": instrument,
            "symbol": instrument,
            "side": side,
            "direction": side,
            "volume": str(volume),
            "entry_price": str(entry),
            "stop_loss_price": str(sl),
            "take_profit_price": str(tp),
            "risk_percent": str(risk_percent),
        })

        if strategy == "SMC":
            normalized["score"] = float(score)
        else:
            # ORB does not inherit or fabricate an SMC score.
            normalized.pop("score", None)
            normalized.pop("final_score", None)

        return True, normalized

    # ==========================================================
    # RISK MANAGER
    # ==========================================================

    async def _check_risk(self, setup):

        try:
            from risk_manager import risk_manager

            strategy = str(setup.get("strategy", "SMC")).upper()

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

            if strategy == "ORB":
                # ORB's detailed checks and broker-based sizing are performed
                # by ORBSharedRiskGate before the final execution handoff.
                if setup.get("risk_approved") is not True:
                    return False, "ORB shared risk approval missing"
                risk_result = setup.get("risk")
                if not isinstance(risk_result, dict):
                    return False, "ORB shared risk result missing"
                if risk_result.get("risk_approved") is not True:
                    return False, "ORB shared risk result rejected"
                if risk_result.get("position_size_required") is True:
                    return False, "ORB position size is not finalized"
                sized_volume = self._decimal(risk_result.get("volume_lots"))
                setup_volume = self._decimal(setup.get("volume"))
                if sized_volume is None or setup_volume != sized_volume:
                    return False, "ORB volume does not match approved risk sizing"
                return True, "ORB shared risk approval rechecked"

            validator = getattr(risk_manager, "validate_trade", None)
            if not callable(validator):
                return False, "Risk Manager validator unavailable"

            result = validator(setup)
            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, tuple):
                allowed = result[0] is True
                reason = result[1] if len(result) > 1 else "Trade risk rejected"
                if not allowed:
                    return False, str(reason)
            elif isinstance(result, dict):
                allowed = any(
                    result.get(key) is True
                    for key in ("allowed", "approved", "valid", "success", "passed")
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
            logger.exception("Risk Manager validation failed")
            return False, f"Risk Manager error: {type(exc).__name__}"

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
                f"{setup.get('strategy', 'SMC')}|"
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
                str(setup.get("strategy", "SMC")),
                str(setup.get("score", "N/A")),
            ))

        digest = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

        return f"vrotex-{digest[:48]}"

    # ==========================================================
    # TRADE MANAGER INTEGRATION
    # ==========================================================

    async def _register_with_trade_manager(
        self,
        result,
        setup,
    ):

        """
        Register a broker-confirmed position with Trade Manager.

        This is called only after the Exness snapshot confirms
        that the position is actually open.
        """

        if not isinstance(result, dict):
            return False

        if result.get("status") != "CONFIRMED":
            return False

        if result.get("trade_manager_registered") is True:
            return True

        verification = result.get("verification")

        if not isinstance(verification, dict):
            return False

        if not isinstance(
            verification.get("position"),
            dict,
        ):
            return False

        try:

            from trade_management import trade_manager

            register = getattr(
                trade_manager,
                "register_confirmed_position",
                None,
            )

            if not callable(register):

                raise RuntimeError(
                    "Trade Manager registration method unavailable"
                )

            registration_result = register(
                result,
                setup=setup,
            )

            if asyncio.iscoroutine(registration_result):
                registration_result = await registration_result

            result["trade_manager_registered"] = True
            result["trade_manager_result"] = (
                registration_result
            )

            logger.info(
                "TRADE MANAGER REGISTERED POSITION | "
                "%s | Position ID=%s",
                setup.get("instrument"),
                verification.get("position_id"),
            )

            # Register the filled trade in shared account-risk statistics
            # only after Exness confirms the position is open.
            if result.get("risk_manager_registered") is not True:
                try:
                    from risk_manager import risk_manager

                    register_trade = getattr(
                        risk_manager,
                        "register_trade",
                        None,
                    )
                    if not callable(register_trade):
                        raise RuntimeError(
                            "Risk Manager register_trade method unavailable"
                        )

                    risk_registered = register_trade(
                        symbol=setup.get("instrument"),
                        risk_percent=setup.get("risk_percent"),
                    )
                    result["risk_manager_registered"] = (
                        risk_registered is True
                    )
                    if risk_registered is not True:
                        result["risk_manager_registration_error"] = (
                            "Risk Manager did not register confirmed position"
                        )
                        logger.error(
                            "Confirmed position was not registered in Risk Manager | %s",
                            setup.get("instrument"),
                        )
                except Exception as risk_exc:
                    result["risk_manager_registered"] = False
                    result["risk_manager_registration_error"] = str(risk_exc)
                    logger.exception(
                        "Risk Manager trade registration failed"
                    )

            return True

        except Exception as exc:

            result["trade_manager_registered"] = False
            result["trade_manager_error"] = str(exc)

            logger.exception(
                "Trade Manager registration failed"
            )

            return False

    # ==========================================================
    # OPEN MARKET POSITION
    # ==========================================================

    async def _submit_order(self, setup, request_id):

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

    async def execute_automatic_demo_once(self):
        """
        One-time automatic Exness DEMO market order.
        Fixed order: BUY EURUSD, 0.01 lot.
        Does not use the normal strategy approval or risk manager.
        """

        import os
        import json
        from pathlib import Path

        async with self._execution_lock:

            request_id = "vrotex-auto-demo-eurusd-buy-001"

            setup = {
                "instrument": "EURUSD",
                "side": "BUY",
                "volume": "0.01",
                "execution_authorized": True,
                "approved": True,
                "demo_only": True,
            }

            # Confirm the Exness connection.
            if not self.connection.connected:
                try:
                    connection_result = await self.connection.connect()
                    if not connection_result:
                        return {
                            "success": False,
                            "status": "CONNECTION_FAILED",
                        }
                except Exception as exc:
                    return {
                        "success": False,
                        "status": "CONNECTION_FAILED",
                        "error": str(exc),
                    }

            # Never submit this order to a real account.
            if not self._verify_demo_account():
                return {
                    "success": False,
                    "status": "DEMO_ACCOUNT_NOT_VERIFIED",
                }

            # Persistent one-time execution lock.
            marker = (
                Path(__file__).resolve().parent
                / "data"
                / "vrotex_automatic_demo_once.json"
            )

            marker.parent.mkdir(parents=True, exist_ok=True)

            try:
                descriptor = os.open(
                    str(marker),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )

                with os.fdopen(descriptor, "w") as file:
                    json.dump({
                        "request_id": request_id,
                        "instrument": "EURUSD",
                        "side": "BUY",
                        "volume": "0.01",
                        "status": "SUBMISSION_STARTED",
                    }, file)

            except FileExistsError:
                return {
                    "success": False,
                    "status": "ALREADY_EXECUTED_OR_ATTEMPTED",
                    "message": "One-time execution is locked.",
                }

            except Exception as exc:
                return {
                    "success": False,
                    "status": "EXECUTION_LOCK_FAILED",
                    "error": str(exc),
                }

            # Submit the actual market order.
            try:
                acknowledgement = await self.connection.open_position(
                    instrument="EURUSD",
                    side="BUY",
                    volume="0.01",
                    idempotency_key=request_id,
                    comment="Vrotex one-time automatic DEMO execution",
                )

                if not acknowledgement:
                    return {
                        "success": False,
                        "status": "BROKER_REJECTED_OR_NO_ACKNOWLEDGEMENT",
                        "acknowledgement": acknowledgement,
                    }

                self.last_order = {
                    "request_id": request_id,
                    "instrument": "EURUSD",
                    "side": "BUY",
                    "volume": "0.01",
                    "status": "SUBMITTED",
                    "acknowledgement": acknowledgement,
                }

                # Verify that Exness actually opened the position.
                verification = await self._verify_execution(
                    setup,
                    request_id,
                )

                if isinstance(verification, dict):
                    status = verification.get("status")

                    if status == "CONFIRMED":
                        self.successful_orders += 1
                        self.last_order["status"] = "CONFIRMED"

                        await self._register_with_trade_manager(
                            verification,
                            setup,
                        )

                    return {
                        "success": status == "CONFIRMED",
                        "status": status or "PENDING",
                        "acknowledgement": acknowledgement,
                        "verification": verification,
                    }

                return {
                    "success": False,
                    "status": "PENDING_CONFIRMATION",
                    "acknowledgement": acknowledgement,
                    "verification": verification,
                }

            except Exception as exc:
                self.last_order = {
                    "request_id": request_id,
                    "status": "SUBMISSION_ERROR",
                    "error": str(exc),
                }

                return {
                    "success": False,
                    "status": "SUBMISSION_ERROR",
                    "error": str(exc),
                    }
                
    
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
                "Strategy=%s | %s %s | Volume=%s | Score=%s",
                normalized.get("strategy", "SMC"),
                normalized["side"].upper(),
                normalized["instrument"],
                normalized["volume"],
                normalized.get("score", "N/A"),
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
                    "strategy": normalized.get("strategy", "SMC"),
                    "instrument": normalized["instrument"],
                    "side": normalized["side"],
                    "volume": normalized["volume"],
                    "entry_price": normalized["entry_price"],
                    "stop_loss_price": normalized["stop_loss_price"],
                    "take_profit_price": normalized["take_profit_price"],
                    "risk_percent": normalized["risk_percent"],
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

                    await self._register_with_trade_manager(
                        result,
                        normalized,
                    )

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

                    # Keep the original normalized setup so
                    # reconciliation can verify and register it.
                    result["_setup"] = dict(normalized)

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
                # a network error occurred. Preserve its ID
                # and setup for later reconciliation.
                result = {
                    "success": False,
                    "status": "ERROR",
                    "request_id": request_id,
                    "instrument": normalized["instrument"],
                    "side": normalized["side"],
                    "volume": normalized["volume"],
                    "reason": str(exc),
                    "reconciliation_required": True,
                    "_setup": dict(normalized),
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

            full_setup = previous.get("_setup")

            if not isinstance(full_setup, dict):
                continue

            try:

                acknowledgement = previous.get(
                    "acknowledgement",
                    {},
                )

                verification = await self._verify_execution(
                    full_setup,
                    acknowledgement,
                )

                previous["verification"] = verification
                previous["status"] = verification["status"]

                if verification["status"] == "CONFIRMED":

                    previous["success"] = True

                    self.orders_confirmed += 1

                    await self._register_with_trade_manager(
                        previous,
                        full_setup,
                    )

                    previous.pop("_setup", None)

                    self.completed_orders[request_id] = previous

                    self.pending_orders.pop(
                        request_id,
                        None,
                    )

                    logger.info(
                        "PENDING POSITION CONFIRMED AND "
                        "REGISTERED | %s | Position ID=%s",
                        previous.get("instrument"),
                        verification.get("position_id"),
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
