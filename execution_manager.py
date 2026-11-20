from config import settings
from logging_config import get_logger
from risk_manager import risk_manager
from decision_engine import decision_engine

logger = get_logger("execution_manager")


class ExecutionManager:

    def __init__(self):

        self.execution_enabled = (
            settings.ORDER_EXECUTION_ENABLED
        )

        self.mode = settings.BOT_MODE

    def execution_allowed(self):

        if not self.execution_enabled:
            return False, "Order execution is disabled"

        if self.mode != "DEMO":
            return False, "Only DEMO mode is permitted"

        allowed, reason = risk_manager.can_trade()

        if not allowed:
            return False, reason

        return True, "Execution checks passed"

    def validate_setup(self, setup):

        decision = decision_engine.evaluate(setup)

        if not decision.get("approved"):
            return False, decision

        allowed, reason = self.execution_allowed()

        if not allowed:

            return False, {
                "approved": False,
                "reason": reason,
                "score": decision.get("score", 0),
            }

        return True, decision

    async def execute(self, setup):

        allowed, result = self.validate_setup(setup)

        if not allowed:

            logger.warning(
                "Execution rejected: %s",
                result.get("reason")
            )

            return {
                "success": False,
                "status": "REJECTED",
                "reason": result.get("reason"),
            }

        # Broker order execution will be connected
        # through the Exness executor module.

        logger.warning(
            "Setup passed validation but no broker executor "
            "is connected yet."
        )

        return {
            "success": False,
            "status": "NOT_EXECUTED",
            "reason": "Broker executor not connected",
            "decision": result,
        }


execution_manager = ExecutionManager()
