
from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
from collections import deque
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse


LOGS = deque(maxlen=500)
CLIENTS: set[WebSocket] = set()
_LOG_HANDLER = None

CHART_INSTRUMENTS = {"EURUSD", "GBPUSD", "BTCUSD"}
CHART_TIMEFRAMES = {"D1", "H4", "H1", "M30", "M15", "M5", "M1"}
MAX_CHART_CANDLES = 1000


def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Enum):
        return make_json_safe(value.value)

    if dataclasses.is_dataclass(value):
        return make_json_safe(dataclasses.asdict(value))

    if isinstance(value, dict):
        return {
            str(k): make_json_safe(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple, set, deque)):
        return [make_json_safe(v) for v in value]

    try:
        attributes = vars(value)
        if attributes:
            return make_json_safe(attributes)
    except (TypeError, AttributeError):
        pass

    try:
        return jsonable_encoder(value)
    except Exception:
        return str(value)


def candle_time_to_unix(value: Any) -> int | None:
    if value is None:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())

        if isinstance(value, date):
            dt = datetime(
                value.year,
                value.month,
                value.day,
                tzinfo=timezone.utc,
            )
            return int(dt.timestamp())

        if isinstance(value, (int, float)):
            timestamp = float(value)

            if not math.isfinite(timestamp):
                return None

            # Convert milliseconds to seconds.
            if timestamp > 100_000_000_000:
                timestamp /= 1000

            return int(timestamp)

        if isinstance(value, str):
            text = value.strip()

            if not text:
                return None

            # Numeric timestamp represented as text.
            try:
                timestamp = float(text)

                if not math.isfinite(timestamp):
                    return None

                if timestamp > 100_000_000_000:
                    timestamp /= 1000

                return int(timestamp)
            except ValueError:
                pass

            # ISO-8601 date/time.
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"

            dt = datetime.fromisoformat(text)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return int(dt.timestamp())

    except (ValueError, TypeError, OverflowError, OSError):
        return None

    return None


def normalize_chart_candles(candles: Any) -> list[dict[str, Any]]:
    if isinstance(candles, dict):
        candles = candles.get(
            "candles",
            candles.get("data", []),
        )

    if not isinstance(candles, (list, tuple)):
        return []

    normalized = []
    seen_times = set()

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        candle_time = candle_time_to_unix(
            candle.get(
                "time",
                candle.get(
                    "timestamp",
                    candle.get("datetime"),
                ),
            )
        )

        if candle_time is None or candle_time in seen_times:
            continue

        try:
            open_price = float(candle["open"])
            high_price = float(candle["high"])
            low_price = float(candle["low"])
            close_price = float(candle["close"])

            values = (
                open_price,
                high_price,
                low_price,
                close_price,
            )

            if not all(math.isfinite(v) for v in values):
                continue

            if high_price < low_price:
                continue

            if high_price < max(open_price, close_price):
                continue

            if low_price > min(open_price, close_price):
                continue

            normalized.append({
                "time": candle_time,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
            })

            seen_times.add(candle_time)

        except (KeyError, TypeError, ValueError, OverflowError):
            continue

    normalized.sort(key=lambda item: item["time"])
    return normalized


class DashboardLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created,
                    timezone.utc,
                ).astimezone().isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }

            LOGS.append(entry)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    broadcast({
                        "type": "log",
                        "entry": entry,
                    })
                )
            except RuntimeError:
                pass

        except Exception:
            self.handleError(record)


async def broadcast(payload: dict[str, Any]) -> None:
    dead = []

    for ws in tuple(CLIENTS):
        try:
            await ws.send_json(make_json_safe(payload))
        except Exception:
            dead.append(ws)

    for ws in dead:
        CLIENTS.discard(ws)


def create_app(bot: Any) -> FastAPI:
    global _LOG_HANDLER

    app = FastAPI(title="Vrotex Bot V1 Dashboard API")
    static_dir = Path(__file__).resolve().parent

    if _LOG_HANDLER is None:
        _LOG_HANDLER = DashboardLogHandler()
        _LOG_HANDLER.setLevel(logging.INFO)
        logging.getLogger().addHandler(_LOG_HANDLER)

    @app.get("/", include_in_schema=False)
    async def home():
        dashboard_file = static_dir / "index.html"

        if not dashboard_file.is_file():
            raise HTTPException(
                status_code=404,
                detail="Dashboard file not found",
            )

        return FileResponse(dashboard_file)

    @app.head("/", include_in_schema=False)
    async def home_head():
        dashboard_file = static_dir / "index.html"

        if not dashboard_file.is_file():
            raise HTTPException(
                status_code=404,
                detail="Dashboard file not found",
            )

        return FileResponse(dashboard_file)

    @app.get("/health")
    async def health():
        return await dashboard_state(bot)

    @app.get("/api/dashboard")
    async def dashboard():
        return await dashboard_state(bot)

    @app.get("/api/logs")
    async def logs():
        return {
            "logs": make_json_safe(list(LOGS))
        }

    # ---------------------------------------------------------
    # CHART API: HISTORICAL CANDLES
    # Uses the existing Exness market-data engine.
    # ---------------------------------------------------------

    @app.get("/api/chart/candles")
    async def chart_candles(
        symbol: str = "EURUSD",
        timeframe: str = "M5",
        count: int = 500,
    ):
        symbol = symbol.upper().strip()
        timeframe = timeframe.upper().strip()

        if symbol not in CHART_INSTRUMENTS:
            raise HTTPException(
                status_code=400,
                detail="Unsupported chart instrument",
            )

        if timeframe not in CHART_TIMEFRAMES:
            raise HTTPException(
                status_code=400,
                detail="Unsupported chart timeframe",
            )

        if count < 1 or count > MAX_CHART_CANDLES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Count must be between 1 and "
                    f"{MAX_CHART_CANDLES}"
                ),
            )

        try:
            from market_data_engine import market_data_engine

            candles = await market_data_engine.request_candles(
                symbol,
                timeframe,
                count,
                price_type="bid",
            )

            normalized = normalize_chart_candles(candles)

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "price_type": "bid",
                "candles": normalized,
                "count": len(normalized),
            }

        except HTTPException:
            raise

        except Exception as exc:
            logging.getLogger(__name__).exception(
                "Chart candle request failed for %s %s",
                symbol,
                timeframe,
            )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Chart candle data is temporarily unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

    # ---------------------------------------------------------
    # CHART API: LIVE BID / ASK TICK
    # Uses the existing Exness live-tick engine.
    # ---------------------------------------------------------

    @app.get("/api/chart/tick")
    async def chart_tick(symbol: str = "EURUSD"):
        symbol = symbol.upper().strip()

        if symbol not in CHART_INSTRUMENTS:
            raise HTTPException(
                status_code=400,
                detail="Unsupported chart instrument",
            )

        try:
            from market_data_engine import market_data_engine

            tick = market_data_engine.get_live_tick(symbol)

            if not tick:
                return {
                    "symbol": symbol,
                    "bid": None,
                    "ask": None,
                    "mid": None,
                    "spread": None,
                    "age_seconds": None,
                    "fresh": False,
                    "reason": "NO LIVE TICK",
                }

            tick = make_json_safe(tick)

            if not isinstance(tick, dict):
                tick = {}

            return {
                "symbol": symbol,
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
                "mid": tick.get("mid"),
                "spread": tick.get("spread"),
                "age_seconds": tick.get(
                    "age_seconds",
                    tick.get("age"),
                ),
                "fresh": bool(tick.get("fresh", False)),
                "reason": tick.get("reason"),
            }

        except HTTPException:
            raise

        except Exception as exc:
            logging.getLogger(__name__).exception(
                "Chart live tick request failed for %s",
                symbol,
            )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Live chart tick is temporarily unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

    @app.post("/api/bot/start")
    async def start_bot():
        return await control(bot, "start")

    @app.post("/api/bot/stop")
    async def stop_bot():
        return await control(bot, "stop")

    @app.websocket("/ws/logs")
    async def log_socket(ws: WebSocket):
        await ws.accept()
        CLIENTS.add(ws)

        try:
            for item in list(LOGS)[-100:]:
                await ws.send_json(
                    make_json_safe({
                        "type": "log",
                        "entry": item,
                    })
                )

            while True:
                await ws.receive_text()

        except WebSocketDisconnect:
            pass

        except Exception:
            logging.getLogger(__name__).exception(
                "Dashboard log WebSocket failed"
            )

        finally:
            CLIENTS.discard(ws)

    return app


async def dashboard_state(bot: Any) -> dict[str, Any]:
    errors = {}
    engine_status = {}
    market_status = {}
    state = {}
    quotes = []

    try:
        from engine import engine

        try:
            engine_status = engine.get_status()

        except Exception as exc:
            errors["engine"] = (
                f"{type(exc).__name__}: {exc}"
            )

            engine_status = {
                "available": False,
                "error": errors["engine"],
            }

    except Exception as exc:
        engine = None

        errors["engine"] = (
            f"{type(exc).__name__}: {exc}"
        )

        engine_status = {
            "available": False,
            "error": errors["engine"],
        }

    try:
        from market_data_engine import market_data_engine

        try:
            market_status = market_data_engine.get_status()

        except Exception as exc:
            errors["market_data"] = (
                f"{type(exc).__name__}: {exc}"
            )

            market_status = {
                "available": False,
                "error": errors["market_data"],
            }

    except Exception as exc:
        market_data_engine = None

        errors["market_data"] = (
            f"{type(exc).__name__}: {exc}"
        )

        market_status = {
            "available": False,
            "error": errors["market_data"],
        }

    try:
        from state_manager import state_manager

        try:
            state = state_manager.get_state()

        except Exception as exc:
            errors["state"] = (
                f"{type(exc).__name__}: {exc}"
            )

            state = {
                "available": False,
                "error": errors["state"],
            }

    except Exception as exc:
        errors["state"] = (
            f"{type(exc).__name__}: {exc}"
        )

        state = {
            "available": False,
            "error": errors["state"],
        }

    if market_data_engine is not None:
        for symbol in ("EURUSD", "GBPUSD", "BTCUSD"):
            try:
                tick = market_data_engine.get_live_tick(symbol)

                if tick:
                    tick = make_json_safe(tick)

                    if not isinstance(tick, dict):
                        tick = {}

                    fresh = bool(tick.get("fresh", False))

                    quotes.append({
                        "symbol": symbol,
                        "bid": tick.get("bid"),
                        "ask": tick.get("ask"),
                        "fresh": fresh,
                        "reason": (
                            None if fresh
                            else "STALE / MARKET CLOSED"
                        ),
                    })

                else:
                    quotes.append({
                        "symbol": symbol,
                        "bid": None,
                        "ask": None,
                        "fresh": False,
                        "reason": "NO LIVE TICK",
                    })

            except Exception as exc:
                errors[f"quote_{symbol}"] = (
                    f"{type(exc).__name__}: {exc}"
                )

                quotes.append({
                    "symbol": symbol,
                    "bid": None,
                    "ask": None,
                    "fresh": False,
                    "reason": "QUOTE UNAVAILABLE",
                })

    else:
        quotes = [
            {
                "symbol": symbol,
                "bid": None,
                "ask": None,
                "fresh": False,
                "reason": "MARKET DATA ENGINE UNAVAILABLE",
            }
            for symbol in ("EURUSD", "GBPUSD", "BTCUSD")
        ]

    engine_task = getattr(bot, "engine_task", None)

    try:
        running = bool(
            engine_task is not None and not engine_task.done()
        )
    except Exception:
        running = False

    response = {
        "status": "ok",
        "bot": "Vrotex Bot V1",
        "running": running,
        "engine": make_json_safe(engine_status),
        "state": make_json_safe(state),
        "market_data": make_json_safe(market_status),
        "quotes": make_json_safe(quotes),
        "logs": make_json_safe(list(LOGS)[-30:]),
    }

    if errors:
        response["component_errors"] = errors

    return response


async def control(bot: Any, action: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=503,
        detail=(
            "Dashboard control is not enabled yet. "
            "Secure control setup is required before "
            "remote start/stop can be activated."
        ),
    )
