
"""
VROTEX BOT V1
INTELLIGENCE CORE
Version 1.0

Purpose:
- Coordinate the existing Technical Analysis Engine.
- Coordinate the existing Fundamental Analysis Engine.
- Publish analysis results to the Intelligence Registry.
- Provide a shared intelligence interface to Vrotex modules.

Scope:
- Technical Analysis
- Fundamental Analysis
- Intelligence Registry communication

Does NOT:
- Duplicate TA or FA calculations.
- Execute trades.
- Generate SMC entry signals.
- Fetch external economic data.
- Modify trading strategy or risk settings.
"""

from typing import Any, Dict, List, Optional

from technical_analysis_engine import technical_analysis_engine
from fundamental_analysis_engine import fundamental_analysis_engine
from intelligence_registry import intelligence_registry


class IntelligenceCore:

    VERSION = "1.0"

    def __init__(self):
        self.technical_engine = technical_analysis_engine
        self.fundamental_engine = fundamental_analysis_engine
        self.registry = intelligence_registry

        self.last_results: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # REGISTRY COMMUNICATION
    # ---------------------------------------------------------

    def _publish(
        self,
        key: str,
        value: Any,
        source: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:

        self.registry.publish(
            key=key,
            value=value,
            source=source,
            metadata=metadata or {}
        )

    def get_intelligence(
        self,
        key: str,
        default: Any = None
    ) -> Any:

        return self.registry.get(key, default)

    def get_intelligence_record(
        self,
        key: str
    ) -> Optional[Dict[str, Any]]:

        return self.registry.get_record(key)

    # ---------------------------------------------------------
    # TECHNICAL ANALYSIS
    # ---------------------------------------------------------

    def analyze_technical(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Dict[str, Any]],
        previous_bias: str = "UNKNOWN",
        liquidity_tolerance: Optional[float] = None
    ) -> Dict[str, Any]:

        symbol = str(symbol).upper().strip()
        timeframe = str(timeframe).upper().strip()

        if not symbol or not timeframe:
            return {
                "success": False,
                "reason": "INVALID_SYMBOL_OR_TIMEFRAME"
            }

        if not isinstance(candles, list):
            return {
                "success": False,
                "reason": "INVALID_CANDLE_INPUT",
                "symbol": symbol,
                "timeframe": timeframe
            }

        try:

            result = self.technical_engine.analyze(
                candles=candles,
                symbol=symbol,
                timeframe=timeframe,
                previous_bias=previous_bias,
                liquidity_tolerance=liquidity_tolerance
            )

            if not isinstance(result, dict):
                raise TypeError(
                    "Technical Analysis Engine returned an invalid result"
                )

            result["intelligence_source"] = (
                "TECHNICAL_ANALYSIS_ENGINE"
            )

            result["intelligence_version"] = self.VERSION

            self._publish(
                key=f"technical_analysis:{symbol}:{timeframe}",
                value=result,
                source="TECHNICAL_ANALYSIS_ENGINE",
                metadata={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "version": self.VERSION
                }
            )

            self.last_results[
                f"technical:{symbol}:{timeframe}"
            ] = result

            return result

        except Exception as exc:

            error = {
                "success": False,
                "symbol": symbol,
                "timeframe": timeframe,
                "reason": "TECHNICAL_ANALYSIS_FAILED",
                "error": str(exc)
            }

            self._publish(
                key=f"technical_analysis:{symbol}:{timeframe}",
                value=error,
                source="INTELLIGENCE_CORE",
                metadata={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "error": True
                }
            )

            return error

    # ---------------------------------------------------------
    # FUNDAMENTAL DATA INPUT
    # ---------------------------------------------------------

    def update_currency_data(
        self,
        currency: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:

        currency = str(currency).upper().strip()

        if not isinstance(data, dict):
            return {
                "success": False,
                "reason": "INVALID_CURRENCY_DATA"
            }

        try:

            self.fundamental_engine.update_currency_data(
                currency,
                data
            )

            self._publish(
                key=f"fundamental_input:{currency}",
                value=data,
                source="FUNDAMENTAL_DATA_INPUT",
                metadata={
                    "currency": currency
                }
            )

            return {
                "success": True,
                "currency": currency,
                "status": "CURRENCY_DATA_UPDATED"
            }

        except Exception as exc:

            return {
                "success": False,
                "currency": currency,
                "reason": "CURRENCY_DATA_UPDATE_FAILED",
                "error": str(exc)
            }

    def update_economic_events(
        self,
        events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:

        if not isinstance(events, list):
            return {
                "success": False,
                "reason": "INVALID_EVENTS_INPUT"
            }

        try:

            self.fundamental_engine.update_events(events)

            self._publish(
                key="fundamental_economic_events",
                value=events,
                source="FUNDAMENTAL_DATA_INPUT",
                metadata={
                    "event_count": len(events)
                }
            )

            return {
                "success": True,
                "event_count": len(events),
                "status": "ECONOMIC_EVENTS_UPDATED"
            }

        except Exception as exc:

            return {
                "success": False,
                "reason": "ECONOMIC_EVENT_UPDATE_FAILED",
                "error": str(exc)
            }

    # ---------------------------------------------------------
    # FUNDAMENTAL ANALYSIS
    # ---------------------------------------------------------

    def analyze_fundamental(
        self,
        symbol: str
    ) -> Dict[str, Any]:

        symbol = str(symbol).upper().strip()

        if not symbol:
            return {
                "success": False,
                "reason": "INVALID_SYMBOL"
            }

        try:

            result = self.fundamental_engine.analyze_pair(
                symbol
            )

            if not isinstance(result, dict):
                raise TypeError(
                    "Fundamental Analysis Engine returned an invalid result"
                )

            result["intelligence_source"] = (
                "FUNDAMENTAL_ANALYSIS_ENGINE"
            )

            result["intelligence_version"] = self.VERSION

            self._publish(
                key=f"fundamental_analysis:{symbol}",
                value=result,
                source="FUNDAMENTAL_ANALYSIS_ENGINE",
                metadata={
                    "symbol": symbol,
                    "version": self.VERSION
                }
            )

            self.last_results[
                f"fundamental:{symbol}"
            ] = result

            return result

        except Exception as exc:

            error = {
                "success": False,
                "symbol": symbol,
                "reason": "FUNDAMENTAL_ANALYSIS_FAILED",
                "error": str(exc)
            }

            self._publish(
                key=f"fundamental_analysis:{symbol}",
                value=error,
                source="INTELLIGENCE_CORE",
                metadata={
                    "symbol": symbol,
                    "error": True
                }
            )

            return error

    # ---------------------------------------------------------
    # COMPLETE INSTRUMENT INTELLIGENCE
    # ---------------------------------------------------------

    def analyze_instrument(
        self,
        symbol: str,
        candles_by_timeframe: Dict[str, List[Dict[str, Any]]],
        previous_biases: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:

        symbol = str(symbol).upper().strip()

        if not isinstance(candles_by_timeframe, dict):
            return {
                "success": False,
                "reason": "INVALID_TIMEFRAME_DATA"
            }

        previous_biases = previous_biases or {}

        technical_results = {}

        for timeframe, candles in candles_by_timeframe.items():

            timeframe = str(timeframe).upper().strip()

            technical_results[timeframe] = (
                self.analyze_technical(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles,
                    previous_bias=previous_biases.get(
                        timeframe,
                        "UNKNOWN"
                    )
                )
            )

        fundamental_result = self.analyze_fundamental(
            symbol
        )

        result = {
            "success": True,
            "version": self.VERSION,
            "symbol": symbol,
            "technical_analysis": technical_results,
            "fundamental_analysis": fundamental_result,
            "sources": [
                "TECHNICAL_ANALYSIS_ENGINE",
                "FUNDAMENTAL_ANALYSIS_ENGINE"
            ]
        }

        self._publish(
            key=f"intelligence:{symbol}",
            value=result,
            source="INTELLIGENCE_CORE",
            metadata={
                "symbol": symbol,
                "version": self.VERSION,
                "timeframes": list(technical_results.keys())
            }
        )

        self.last_results[
            f"instrument:{symbol}"
        ] = result

        return result

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:

        return {
            "component": "VROTEX_INTELLIGENCE_CORE",
            "version": self.VERSION,
            "status": "ACTIVE",
            "components": {
                "technical_analysis": (
                    self.technical_engine.get_status()
                ),
                "fundamental_analysis": (
                    self.fundamental_engine.get_status()
                ),
                "intelligence_registry": (
                    self.registry.status()
                )
            },
            "last_result_count": len(self.last_results)
        }

    def get_last_results(self) -> Dict[str, Any]:
        return dict(self.last_results)


# -------------------------------------------------------------
# SHARED INTELLIGENCE CORE INSTANCE
# -------------------------------------------------------------

intelligence_core = IntelligenceCore()
