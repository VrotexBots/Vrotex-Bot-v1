
"""
VROTEX BOT V1
MASTER SMC INTEGRATION ENGINE

Coordinates the SMC analysis modules.

Strategy:
H1 = External structure and narrative
M5 = Confirmation
M1 = Entry

Important:
- Evidence collection only.
- No broker orders.
- No automatic execution authorization.
- Missing or invalid evidence fails closed.
"""

from typing import Any, Dict, Optional


class SMCEngine:

    REQUIRED_TIMEFRAMES = ("H1", "M5", "M1")

    def __init__(
        self,
        structure_engine=None,
        liquidity_engine=None,
        range_engine=None,
        protected_range_engine=None,
        entry_model_engine=None,
        confluence_engine=None,
        evidence_aggregator=None,
        setup_validator=None,
        opposing_liquidity_engine=None,
    ):
        self.structure_engine = structure_engine
        self.liquidity_engine = liquidity_engine
        self.range_engine = range_engine
        self.protected_range_engine = protected_range_engine
        self.entry_model_engine = entry_model_engine
        self.confluence_engine = confluence_engine
        self.evidence_aggregator = evidence_aggregator
        self.setup_validator = setup_validator
        self.opposing_liquidity_engine = opposing_liquidity_engine

        self.last_result: Dict[str, Any] = {}
        self.analysis_count = 0

    @staticmethod
    def _direction(value: Any) -> str:
        value = str(value or "").upper()

        if value in ("BULLISH", "BEARISH"):
            return value

        return "NONE"

    @staticmethod
    def _valid_result(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("valid") is True
        )

    @staticmethod
    def _safe_copy(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _validate_market_data(
        self,
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(market_data, dict):
            return {
                "valid": False,
                "error": "INVALID_MARKET_DATA",
            }

        missing = []

        for timeframe in self.REQUIRED_TIMEFRAMES:
            candles = market_data.get(timeframe)

            if not isinstance(candles, list) or len(candles) < 3:
                missing.append(timeframe)

        if missing:
            return {
                "valid": False,
                "error": "MISSING_TIMEFRAME_DATA",
                "missing_timeframes": missing,
            }

        return {
            "valid": True,
            "status": "MARKET_DATA_VALID",
        }

    def _run_module(
        self,
        module,
        method_name: str,
        *args,
        **kwargs,
    ) -> Dict[str, Any]:

        if module is None:
            return {
                "valid": False,
                "status": "MODULE_NOT_CONNECTED",
            }

        method = getattr(module, method_name, None)

        if not callable(method):
            return {
                "valid": False,
                "status": "MODULE_METHOD_UNAVAILABLE",
                "method": method_name,
            }

        try:
            result = method(*args, **kwargs)

            if not isinstance(result, dict):
                return {
                    "valid": False,
                    "status": "INVALID_MODULE_RESPONSE",
                }

            return result

        except Exception as exc:
            return {
                "valid": False,
                "status": "MODULE_ERROR",
                "error": str(exc),
            }

    def analyse_timeframes(
        self,
        market_data: Dict[str, Any],
        direction: Optional[str] = None,
    ) -> Dict[str, Any]:

        validation = self._validate_market_data(market_data)

        if not validation["valid"]:
            return validation

        results = {}

        # H1 external narrative.
        results["H1"] = self._run_module(
            self.structure_engine,
            "analyse",
            market_data["H1"],
        )

        # M5 confirmation.
        results["M5"] = self._run_module(
            self.structure_engine,
            "analyse",
            market_data["M5"],
        )

        # M1 entry structure.
        results["M1"] = self._run_module(
            self.structure_engine,
            "analyse",
            market_data["M1"],
        )

        for timeframe, result in results.items():
            if not isinstance(result, dict):
                return {
                    "valid": False,
                    "status": "TIMEFRAME_ANALYSIS_FAILED",
                    "timeframe": timeframe,
                }

        return {
            "valid": True,
            "status": "TIMEFRAME_ANALYSIS_COMPLETE",
            "timeframes": results,
        }

    def evaluate_alignment(
        self,
        timeframe_results: Dict[str, Any],
    ) -> Dict[str, Any]:

        directions = {}

        for timeframe in self.REQUIRED_TIMEFRAMES:
            result = self._safe_copy(
                timeframe_results.get(timeframe)
            )

            directions[timeframe] = self._direction(
                result.get("direction")
            )

        missing = [
            timeframe
            for timeframe, value in directions.items()
            if value == "NONE"
        ]

        aligned = (
            not missing
            and len(set(directions.values())) == 1
        )

        return {
            "valid": not missing,
            "aligned": aligned,
            "directions": directions,
            "dominant_direction": (
                next(iter(set(directions.values())))
                if aligned else "NONE"
            ),
            "missing_directions": missing,
            "confirmed": aligned,
        }

    def analyse_ranges(
        self,
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:

        h1 = self._run_module(
            self.range_engine,
            "analyse",
            market_data["H1"],
            source="H1",
        )

        m5 = self._run_module(
            self.range_engine,
            "analyse",
            market_data["M5"],
            source="M5",
        )

        return {
            "valid": h1.get("valid") is True and m5.get("valid") is True,
            "H1": h1,
            "M5": m5,
        }

    def analyse_protected_levels(
        self,
        market_data: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:

        if direction not in ("BULLISH", "BEARISH"):
            return {
                "valid": False,
                "status": "DIRECTION_NOT_CONFIRMED",
            }

        h1 = self._run_module(
            self.protected_range_engine,
            "analyse",
            market_data["H1"],
            direction=direction,
        )

        m5 = self._run_module(
            self.protected_range_engine,
            "analyse",
            market_data["M5"],
            direction=direction,
        )

        return {
            "valid": h1.get("valid") is True and m5.get("valid") is True,
            "H1": h1,
            "M5": m5,
        }

    def analyse_opposing_liquidity(
        self,
        market_data: Dict[str, Any],
        direction: str,
        current_price: float,
    ) -> Dict[str, Any]:

        if self.opposing_liquidity_engine is None:
            return {
                "valid": False,
                "status": "MODULE_NOT_CONNECTED",
            }

        return self._run_module(
            self.opposing_liquidity_engine,
            "analyse",
            market_data["H1"],
            direction=direction,
            current_price=current_price,
        )

    def analyse_entry_models(
        self,
        direction: str,
        entry_evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        if self.entry_model_engine is None:
            return {
                "valid": False,
                "status": "MODULE_NOT_CONNECTED",
            }

        return self._run_module(
            self.entry_model_engine,
            "evaluate_all",
            direction,
            entry_evidence,
        )

    def run_confluence(
        self,
        h1: Dict[str, Any],
        m5: Dict[str, Any],
        m1: Dict[str, Any],
        structure: Dict[str, Any],
        liquidity: Dict[str, Any],
        poi: Dict[str, Any],
        displacement: Dict[str, Any],
        fvg: Dict[str, Any],
        entry_model: Dict[str, Any],
    ) -> Dict[str, Any]:

        if self.confluence_engine is None:
            return {
                "valid": False,
                "status": "MODULE_NOT_CONNECTED",
            }

        return self._run_module(
            self.confluence_engine,
            "analyse",
            h1=h1,
            m5=m5,
            m1=m1,
            structure=structure,
            liquidity=liquidity,
            poi=poi,
            displacement=displacement,
            fvg=fvg,
            entry_model=entry_model,
        )

    def aggregate_evidence(
        self,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        if self.evidence_aggregator is None:
            return {
                "valid": False,
                "status": "MODULE_NOT_CONNECTED",
            }

        return self._run_module(
            self.evidence_aggregator,
            "aggregate",
            evidence,
        )

    def validate_setup(
        self,
        aggregated_evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:

        if self.setup_validator is None:
            return {
                "valid": False,
                "status": "MODULE_NOT_CONNECTED",
                "execution_authorized": False,
            }

        if not aggregated_evidence.get("valid"):
            return {
                "valid": False,
                "status": "AGGREGATED_EVIDENCE_INVALID",
                "execution_authorized": False,
            }

        category_scores = aggregated_evidence.get(
            "category_scores", {}
        )

        checks = aggregated_evidence.get(
            "checks", {}
        )

        return self._run_module(
            self.setup_validator,
            "validate",
            direction=direction,
            category_scores=category_scores,
            checks=checks,
        )

    def analyse(
        self,
        market_data: Dict[str, Any],
        current_price: float,
        entry_evidence: Dict[str, Any],
        poi_evidence: Dict[str, Any],
        displacement_evidence: Dict[str, Any],
        fvg_evidence: Dict[str, Any],
        risk_checks: Dict[str, Any],
    ) -> Dict[str, Any]:

        self.analysis_count += 1

        validation = self._validate_market_data(
            market_data
        )

        if not validation["valid"]:
            return self._finish_failure(validation)

        timeframe_analysis = self.analyse_timeframes(
            market_data
        )

        if not timeframe_analysis.get("valid"):
            return self._finish_failure(timeframe_analysis)

        timeframe_results = timeframe_analysis["timeframes"]

        alignment = self.evaluate_alignment(
            timeframe_results
        )

        if not alignment["aligned"]:
            return self._finish_failure({
                "valid": False,
                "status": "TIMEFRAMES_NOT_ALIGNED",
                "alignment": alignment,
            })

        direction = alignment["dominant_direction"]

        ranges = self.analyse_ranges(market_data)

        if not ranges["valid"]:
            return self._finish_failure({
                "valid": False,
                "status": "RANGE_ANALYSIS_FAILED",
                "ranges": ranges,
            })

        protected = self.analyse_protected_levels(
            market_data,
            direction,
        )

        if not protected["valid"]:
            return self._finish_failure({
                "valid": False,
                "status": "PROTECTED_LEVEL_ANALYSIS_FAILED",
                "protected_levels": protected,
            })

        opposing = self.analyse_opposing_liquidity(
            market_data,
            direction,
            current_price,
        )

        entry_models = self.analyse_entry_models(
            direction,
            entry_evidence,
        )

        if not entry_models.get("valid"):
            return self._finish_failure({
                "valid": False,
                "status": "ENTRY_MODEL_ANALYSIS_FAILED",
                "entry_models": entry_models,
            })

        if not entry_models.get("entry_model_confirmed"):
            return self._finish_failure({
                "valid": False,
                "status": "NO_ENTRY_MODEL_CONFIRMED",
                "entry_models": entry_models,
            })

        structure = {
            "direction": direction,
            "H1": timeframe_results["H1"],
            "M5": timeframe_results["M5"],
            "M1": timeframe_results["M1"],
            "alignment": alignment,
        }

        liquidity = {
            "opposing_target": opposing,
            "evidence": entry_evidence.get("sweep", {}),
        }

        evidence = {
            "h1": timeframe_results["H1"],
            "m5": timeframe_results["M5"],
            "m1": timeframe_results["M1"],
            "structure": structure,
            "liquidity": liquidity,
            "poi": poi_evidence,
            "displacement": displacement_evidence,
            "fvg": fvg_evidence,
            "entry_model": entry_models,
            "risk_checks": risk_checks,
            "ranges": ranges,
            "protected_levels": protected,
        }

        aggregated = self.aggregate_evidence(evidence)

        if not aggregated.get("valid"):
            return self._finish_failure({
                "valid": False,
                "status": "EVIDENCE_AGGREGATION_FAILED",
                "aggregation": aggregated,
            })

        validation_result = self.validate_setup(
            aggregated,
            direction,
        )

        passed = (
            validation_result.get("valid") is True
            and validation_result.get("approved") is True
        )

        result = {
            "valid": True,
            "status": (
                "SMC_SETUP_APPROVED"
                if passed else "SMC_SETUP_REJECTED"
            ),
            "direction": direction,
            "timeframe_alignment": alignment,
            "ranges": ranges,
            "protected_levels": protected,
            "opposing_liquidity": opposing,
            "entry_models": entry_models,
            "aggregated_evidence": aggregated,
            "validation": validation_result,
            "execution_authorized": False,
        }

        self.last_result = result
        return result

    def _finish_failure(
        self,
        failure: Dict[str, Any],
    ) -> Dict[str, Any]:

        result = {
            **failure,
            "execution_authorized": False,
        }

        self.last_result = result
        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "module": "SMCEngine",
            "analysis_count": self.analysis_count,
            "required_timeframes": list(
                self.REQUIRED_TIMEFRAMES
            ),
            "execution_authorized": False,
            "last_result": self.last_result,
        }


smc_engine = SMCEngine()
