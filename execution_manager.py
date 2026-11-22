
# execution_manager.py
# Vrotex Bot V1
# Autonomous Execution Integration

from logging_config import get_logger
from risk_manager import risk_manager
from decision_engine import decision_engine

logger = get_logger("execution_manager")


class ExecutionManager:

    VERSION = "1.0"

    def __init__(self):

        self.execution_enabled = True
        self.auto_execution = True

        self.orders_attempted = 0
        self.orders_approved = 0
        self.orders_rejected = 0

        self.last_execution = None

    def execution_allowed(self):

        """
        Risk validation.
        No manual approval requirement.
        """

        try:

            result = risk_manager.can_trade()

            if isinstance(result, tuple):

                allowed, reason = result

                if not allowed:
                    return False, reason

                return True, reason

            if result is True:

                return True, "Risk checks passed"

            return False, "Risk manager rejected trading"

        except Exception as exc:

            logger.exception(
                "Risk validation failed"
            )

            return False, (
                f"Risk validation error: "
                f"{type(exc).__name__}"
            )

    def validate_setup(self, setup):

        if not isinstance(setup, dict):

            return False, {
                "approved": False,
                "reason": "Invalid setup",
            }

        # Master SMC authorization must originate
        # from the upstream SMC engine.
        if not setup.get(
            "execution_authorized",
            False
        ):

            return False, {
                "approved": False,
                "reason": (
                    "Master SMC authorization missing"
                ),
            }

        try:

            decision = decision_engine.evaluate(
                setup
            )

        except Exception as exc:

            logger.exception(
                "Decision Engine evaluation failed"
            )

            return False, {
                "approved": False,
                "reason": (
                    f"Decision Engine error: "
                    f"{type(exc).__name__}"
                ),
            }

        if not isinstance(decision, dict):

            return False, {
                "approved": False,
                "reason": (
                    "Decision Engine returned "
                    "invalid response"
                ),
            }

        if decision.get("approved") is not True:

            return False, decision

        risk_allowed, risk_reason = (
            self.execution_allowed()
        )

        if not risk_allowed:

            return False, {
                "approved": False,
                "reason": risk_reason,
                "score": decision.get(
                    "score",
                    setup.get("score", 0)
                ),
            }

        return True, decision

    async def execute(self, setup):

        """
        Autonomous execution pipeline:

        Scanner
            -> Master SMC authorization
            -> Decision Engine
            -> Risk Manager
            -> Exness Order Executor

        No manual approval per trade.
        """

        if not self.auto_execution:

            return {
                "success": False,
                "status": "DISABLED",
                "reason": "Autonomous execution disabled",
            }

        allowed, decision = (
            self.validate_setup(setup)
        )

        if not allowed:

            self.orders_rejected += 1

            logger.warning(
                "Execution rejected: %s",
                decision.get("reason")
            )

            result = {
                "success": False,
                "status": "REJECTED",
                "reason": decision.get("reason"),
                "decision": decision,
            }

            self.last_execution = result

            return result

        # Import at execution time to avoid
        # circular imports during module startup.
        try:

            from exness_order_executor import (
                exness_order_executor,
            )

        except Exception as exc:

            logger.exception(
                "Executor import failed"
            )

            return {
                "success": False,
                "status": "ERROR",
                "reason": (
                    f"Executor unavailable: "
                    f"{type(exc).__name__}"
                ),
            }

        # Preserve the original setup and merge
        # the Decision Engine's evidence.
        execution_setup = dict(setup)

        execution_setup.update(decision)

        # Approval comes from Decision Engine.
        execution_setup["approved"] = (
            decision.get("approved") is True
        )

        # Do NOT manufacture SMC authorization.
        execution_setup["execution_authorized"] = (
            setup.get("execution_authorized")
            is True
        )

        # Preserve score from the Decision Engine
        # if present, otherwise original setup.
        if "score" not in decision:

            execution_setup["score"] = (
                setup.get("score")
            )

        self.orders_attempted += 1

        logger.info(
            "AUTONOMOUS EXECUTION APPROVED | "
            "Score=%s",
            execution_setup.get("score"),
        )

        try:

            result = (
                await exness_order_executor.execute(
                    execution_setup
                )
            )

            if not isinstance(result, dict):

                result = {
                    "success": False,
                    "status": "ERROR",
                    "reason": (
                        "Executor returned invalid result"
                    ),
                }

            if result.get("success"):

                self.orders_approved += 1

            elif result.get("status") == "REJECTED":

                self.orders_rejected += 1

            self.last_execution = result

            logger.info(
                "Execution pipeline result: %s",
                result.get("status"),
            )

            return result

        except Exception as exc:

            logger.exception(
                "Execution pipeline failure"
            )

            result = {
                "success": False,
                "status": "ERROR",
                "reason": str(exc),
            }

            self.last_execution = result

            return result

    def get_status(self):

        return {
            "version": self.VERSION,
            "execution_enabled": (
                self.execution_enabled
            ),
            "autonomous_execution": (
                self.auto_execution
            ),
            "orders_attempted": (
                self.orders_attempted
            ),
            "orders_approved": (
                self.orders_approved
            ),
            "orders_rejected": (
                self.orders_rejected
            ),
            "last_execution": (
                self.last_execution
            ),
        }


execution_manager = ExecutionManager()
