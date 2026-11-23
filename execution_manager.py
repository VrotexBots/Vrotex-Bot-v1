
# Vrotex Bot V1
# Autonomous Execution Integration
# Version 1.1

from logging_config import get_logger
from risk_manager import risk_manager
from decision_engine import decision_engine

logger = get_logger("execution_manager")


class ExecutionManager:

    VERSION = "1.1"

    def __init__(self):
        self.execution_enabled = True
        self.auto_execution = True

        self.orders_attempted = 0
        self.orders_approved = 0
        self.orders_rejected = 0

        self.last_execution = None

    def execution_allowed(self):
        try:
            result = risk_manager.can_trade()

            if isinstance(result, tuple):
                allowed, reason = result
                return bool(allowed), str(reason)

            if result is True:
                return True, "Risk checks passed"

            return False, "Risk manager rejected trading"

        except Exception as exc:
            logger.exception("Risk validation failed")
            return False, (
                f"Risk validation error: {type(exc).__name__}"
            )

    @staticmethod
    def _get_payload(setup):
        payload = setup.get("execution_payload")

        if isinstance(payload, dict):
            return payload

        return setup

    @staticmethod
    def _get_trade_plan(setup, payload):
        plan = payload.get("trade_plan")

        if not isinstance(plan, dict):
            plan = setup.get("trade_plan")

        if not isinstance(plan, dict):
            plan = setup.get("execution_plan")

        return plan if isinstance(plan, dict) else {}

    def _build_execution_setup(self, setup, decision):
        payload = self._get_payload(setup)
        plan = self._get_trade_plan(setup, payload)

        execution_setup = dict(setup)
        execution_setup.update(payload)

        # Keep the real SMC authorization.
        smc_authorized = (
            setup.get("execution_authorized") is True
            or payload.get("authorized") is True
        )

        execution_setup["execution_authorized"] = (
            smc_authorized
        )

        execution_setup["approved"] = (
            decision.get("approved") is True
        )

        execution_setup["symbol"] = (
            decision.get("symbol")
            or payload.get("symbol")
            or setup.get("symbol")
        )

        execution_setup["instrument"] = (
            plan.get("instrument")
            or plan.get("symbol")
            or payload.get("symbol")
            or setup.get("instrument")
            or setup.get("symbol")
        )

        execution_setup["direction"] = (
            decision.get("direction")
            or payload.get("direction")
            or setup.get("direction")
        )

        execution_setup["side"] = (
            plan.get("side")
            or plan.get("direction")
            or execution_setup["direction"]
        )

        execution_setup["score"] = decision.get("score")

        # Copy only real order-plan values.
        aliases = {
            "volume": ("volume", "lot_size", "units"),
            "entry_price": (
                "entry_price",
                "entry",
                "current_price",
            ),
            "stop_loss_price": (
                "stop_loss_price",
                "stop_loss",
                "sl",
            ),
            "take_profit_price": (
                "take_profit_price",
                "take_profit",
                "tp",
            ),
        }

        for target, names in aliases.items():
            value = None

            for name in names:
                if plan.get(name) is not None:
                    value = plan[name]
                    break

            if value is None:
                for name in names:
                    if payload.get(name) is not None:
                        value = payload[name]
                        break

            if value is None:
                for name in names:
                    if setup.get(name) is not None:
                        value = setup[name]
                        break

            if value is not None:
                execution_setup[target] = value

        execution_setup["trade_plan"] = dict(plan)

        return execution_setup

    def validate_setup(self, setup):
        if not isinstance(setup, dict):
            return False, {
                "approved": False,
                "reason": "Invalid setup",
            }

        payload = self._get_payload(setup)

        smc_authorized = (
            setup.get("execution_authorized") is True
            or payload.get("authorized") is True
        )

        if not smc_authorized:
            return False, {
                "approved": False,
                "reason": "Master SMC authorization missing",
            }

        try:
            decision = decision_engine.evaluate(setup)
        except Exception as exc:
            logger.exception("Decision Engine evaluation failed")

            return False, {
                "approved": False,
                "reason": (
                    f"Decision Engine error: {type(exc).__name__}"
                ),
            }

        if not isinstance(decision, dict):
            return False, {
                "approved": False,
                "reason": "Decision Engine returned invalid response",
            }

        if decision.get("approved") is not True:
            return False, decision

        risk_allowed, risk_reason = self.execution_allowed()

        if not risk_allowed:
            return False, {
                "approved": False,
                "reason": risk_reason,
                "score": decision.get("score"),
            }

        return True, decision

    async def execute(self, setup):

        if not self.execution_enabled:
            return {
                "success": False,
                "status": "DISABLED",
                "reason": "Execution switch disabled",
            }

        if not self.auto_execution:
            return {
                "success": False,
                "status": "DISABLED",
                "reason": "Autonomous execution disabled",
            }

        allowed, decision = self.validate_setup(setup)

        if not allowed:
            self.orders_rejected += 1

            result = {
                "success": False,
                "status": "REJECTED",
                "reason": decision.get("reason"),
                "decision": decision,
            }

            self.last_execution = result

            logger.warning(
                "Execution rejected: %s",
                result["reason"],
            )

            return result

        execution_setup = self._build_execution_setup(
            setup,
            decision,
        )

        # Do not send incomplete order plans to the broker.
        required = (
            "instrument",
            "side",
            "volume",
            "entry_price",
            "stop_loss_price",
            "take_profit_price",
        )

        missing = [
            name
            for name in required
            if execution_setup.get(name) is None
        ]

        if missing:
            self.orders_rejected += 1

            result = {
                "success": False,
                "status": "REJECTED",
                "reason": (
                    "Trade plan missing required order fields: "
                    + ", ".join(missing)
                ),
            }

            self.last_execution = result
            return result

        try:
            from exness_order_executor import (
                exness_order_executor,
            )
        except Exception as exc:
            logger.exception("Executor import failed")

            result = {
                "success": False,
                "status": "ERROR",
                "reason": (
                    f"Executor unavailable: {type(exc).__name__}"
                ),
            }

            self.last_execution = result
            return result

        self.orders_attempted += 1

        logger.info(
            "AUTHORIZED EXECUTION | %s | %s | Score=%s",
            execution_setup["side"],
            execution_setup["instrument"],
            execution_setup["score"],
        )

        try:
            result = await exness_order_executor.execute(
                execution_setup
            )

            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "status": "ERROR",
                    "reason": "Executor returned invalid result",
                }

            if result.get("status") == "CONFIRMED":
                self.orders_approved += 1

            elif result.get("status") in (
                "REJECTED",
                "FAILED",
            ):
                self.orders_rejected += 1

            self.last_execution = result

            logger.info(
                "Execution pipeline result: %s",
                result.get("status"),
            )

            return result

        except Exception as exc:
            logger.exception("Execution pipeline failure")

            result = {
                "success": False,
                "status": "ERROR",
                "reason": f"{type(exc).__name__}: {exc}",
            }

            self.last_execution = result
            return result

    def get_status(self):
        return {
            "version": self.VERSION,
            "execution_enabled": self.execution_enabled,
            "autonomous_execution": self.auto_execution,
            "orders_attempted": self.orders_attempted,
            "orders_approved": self.orders_approved,
            "orders_rejected": self.orders_rejected,
            "last_execution": self.last_execution,
        }


execution_manager = ExecutionManager()
