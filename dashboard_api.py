
from __future__ import annotations

import asyncio
import dataclasses
import logging
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
        return {str(k): make_json_safe(v) for k, v in value.items()}
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


class DashboardLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created, timezone.utc
                ).astimezone().isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            LOGS.append(entry)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    broadcast({"type": "log", "entry": entry})
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
                detail="Dashboard file not found"
            )
        return FileResponse(dashboard_file)

    @app.head("/", include_in_schema=False)
    async def home_head():
        dashboard_file = static_dir / "index.html"
        if not dashboard_file.is_file():
            raise HTTPException(
                status_code=404,
                detail="Dashboard file not found"
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
        return {"logs": make_json_safe(list(LOGS))}

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
                    make_json_safe({"type": "log", "entry": item})
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
            errors["engine"] = f"{type(exc).__name__}: {exc}"
            engine_status = {
                "available": False,
                "error": errors["engine"]
            }

    except Exception as exc:
        engine = None
        errors["engine"] = f"{type(exc).__name__}: {exc}"
        engine_status = {
            "available": False,
            "error": errors["engine"]
        }

    try:
        from market_data_engine import market_data_engine

        try:
            market_status = market_data_engine.get_status()
        except Exception as exc:
            errors["market_data"] = f"{type(exc).__name__}: {exc}"
            market_status = {
                "available": False,
                "error": errors["market_data"]
            }

    except Exception as exc:
        market_data_engine = None
        errors["market_data"] = f"{type(exc).__name__}: {exc}"
        market_status = {
            "available": False,
            "error": errors["market_data"]
        }

    try:
        from state_manager import state_manager

        try:
            state = state_manager.get_state()
        except Exception as exc:
            errors["state"] = f"{type(exc).__name__}: {exc}"
            state = {
                "available": False,
                "error": errors["state"]
            }

    except Exception as exc:
        errors["state"] = f"{type(exc).__name__}: {exc}"
        state = {
            "available": False,
            "error": errors["state"]
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
