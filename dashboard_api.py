
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import logging
import math

from collections import deque
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse


LOGS = deque(maxlen=500)
CLIENTS: set[WebSocket] = set()
_LOG_HANDLER = None


# ============================================================
# VROTEX V1 DASHBOARD CONFIGURATION
# ============================================================

CHART_INSTRUMENTS = {
    "EURUSD",
    "GBPUSD",
    "BTCUSD",
}

CHART_TIMEFRAMES = {
    "D1",
    "H4",
    "H1",
    "M30",
    "M15",
    "M5",
    "M1",
}

MAX_CHART_CANDLES = 1000


# ============================================================
# JSON SERIALIZATION
# ============================================================

def make_json_safe(value: Any) -> Any:

    if value is None or isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Enum):
        return make_json_safe(value.value)

    if dataclasses.is_dataclass(value):
        return make_json_safe(
            dataclasses.asdict(value)
        )

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set, deque)):
        return [
            make_json_safe(item)
            for item in value
        ]

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


# ============================================================
# ENGINE METHOD EXECUTION
# Supports synchronous and asynchronous engine methods.
# ============================================================

async def call_engine_method(
    method,
    *args,
    **kwargs,
):

    if not callable(method):
        raise RuntimeError(
            "Requested market-data method is unavailable"
        )

    if inspect.iscoroutinefunction(method):

        return await method(
            *args,
            **kwargs,
        )

    result = await asyncio.to_thread(
        method,
        *args,
        **kwargs,
    )

    if inspect.isawaitable(result):
        result = await result

    return result


# ============================================================
# LIVE TICK EXTRACTION
# Uses the actual MarketDataEngine live-tick interface.
# ============================================================

async def get_engine_tick(
    market_engine,
    symbol: str,
):

    symbol = symbol.upper().strip()

    get_tick = getattr(
        market_engine,
        "get_live_tick",
        None,
    )

    if not callable(get_tick):
        raise RuntimeError(
            "MarketDataEngine.get_live_tick is unavailable"
        )

    raw_tick = await call_engine_method(
        get_tick,
        symbol,
    )

    if raw_tick is None:
        return None

    tick = make_json_safe(raw_tick)

    if not isinstance(tick, dict):
        raise RuntimeError(
            "Live tick returned an unexpected payload"
        )

    result = dict(tick)

    bid = result.get("bid")
    ask = result.get("ask")

    try:

        bid = float(bid)
        ask = float(ask)

        if not (
            math.isfinite(bid)
            and math.isfinite(ask)
            and bid > 0
            and ask > 0
            and ask >= bid
        ):
            raise ValueError(
                "Invalid bid/ask values"
            )

    except (TypeError, ValueError, OverflowError):

        result["bid"] = None
        result["ask"] = None
        result["mid"] = None
        result["spread"] = None
        result["fresh"] = False
        result["reason"] = "INVALID LIVE QUOTE"

        return result

    result["bid"] = bid
    result["ask"] = ask

    result["mid"] = (bid + ask) / 2
    result["spread"] = ask - bid

    # --------------------------------------------------------
    # Determine quote age where a timestamp is available.
    # --------------------------------------------------------

    age = result.get(
        "age_seconds",
        result.get("age"),
    )

    stamp = result.get(
        "timestamp",
        result.get("time"),
    )

    if age is None and stamp is not None:

        try:

            if isinstance(stamp, str):

                dt = datetime.fromisoformat(
                    stamp.replace("Z", "+00:00")
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=timezone.utc
                    )

                age = max(
                    0.0,
                    (
                        datetime.now(timezone.utc)
                        - dt.astimezone(timezone.utc)
                    ).total_seconds(),
                )

            elif isinstance(stamp, (int, float)):

                seconds = float(stamp)

                if seconds > 100_000_000_000:
                    seconds /= 1000.0

                age = max(
                    0.0,
                    datetime.now(timezone.utc).timestamp()
                    - seconds,
                )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            age = None

    if age is not None:

        try:
            age = max(0.0, float(age))

            if not math.isfinite(age):
                age = None

        except (TypeError, ValueError, OverflowError):
            age = None

    result["age_seconds"] = age

    # Respect the market-data engine's freshness decision
    # when it supplies one. Otherwise calculate from age.
    source_fresh = result.get("fresh")

    if source_fresh is not None:

        fresh = bool(source_fresh)

    else:

        fresh = (
            age is not None
            and age <= 120
        )

    result["fresh"] = fresh

    if not fresh:
        result["reason"] = "STALE / MARKET CLOSED"
    else:
        result["reason"] = None

    return result


# ============================================================
# CANDLE NORMALIZATION
# ============================================================

def candle_time_to_unix(value: Any) -> int:

    if isinstance(value, datetime):
        dt = value

    elif isinstance(value, date):

        dt = datetime(
            value.year,
            value.month,
            value.day,
            tzinfo=timezone.utc,
        )

    elif isinstance(value, (int, float)):

        stamp = float(value)

        if stamp > 100_000_000_000:
            stamp /= 1000.0

        return int(stamp)

    elif isinstance(value, str):

        raw = value.strip()

        if not raw:
            raise ValueError(
                "Candle is missing its time value"
            )

        try:

            stamp = float(raw)

            if stamp > 100_000_000_000:
                stamp /= 1000.0

            return int(stamp)

        except ValueError:
            pass

        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"

        dt = datetime.fromisoformat(raw)

    else:

        raise ValueError(
            f"Unsupported candle time type: "
            f"{type(value).__name__}"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return int(
        dt.astimezone(timezone.utc).timestamp()
    )


def normalize_chart_candles(
    raw_candles: Any,
) -> list[dict[str, Any]]:

    if isinstance(raw_candles, dict):

        raw_candles = raw_candles.get(
            "candles",
            raw_candles.get(
                "data",
                raw_candles.get("items", []),
            ),
        )

    if not isinstance(raw_candles, (list, tuple)):

        raise ValueError(
            "Market-data engine returned an unexpected candle payload"
        )

    by_time = {}

    for candle in raw_candles:

        if not isinstance(candle, dict):
            continue

        try:

            stamp = candle_time_to_unix(
                candle.get(
                    "time",
                    candle.get("timestamp"),
                )
            )

            bar = {
                "time": stamp,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
            }

            values = (
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"],
            )

            if not all(
                math.isfinite(number)
                for number in values
            ):
                continue

            if bar["high"] < max(
                bar["open"],
                bar["close"],
                bar["low"],
            ):
                continue

            if bar["low"] > min(
                bar["open"],
                bar["close"],
                bar["high"],
            ):
                continue

            by_time[stamp] = bar

        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            continue

    return [
        by_time[stamp]
        for stamp in sorted(by_time)
    ]


# ============================================================
# DASHBOARD LOGGING
# ============================================================

class DashboardLogHandler(logging.Handler):

    def emit(self, record: logging.LogRecord):

        try:

            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created,
                    timezone.utc,
                ).astimezone().isoformat(
                    timespec="seconds"
                ),

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


async def broadcast(payload: dict[str, Any]):

    dead = []

    for ws in tuple(CLIENTS):

        try:
            await ws.send_json(
                make_json_safe(payload)
            )

        except Exception:
            dead.append(ws)

    for ws in dead:
        CLIENTS.discard(ws)


# ============================================================
# DASHBOARD APPLICATION
# ============================================================

def create_app(bot: Any) -> FastAPI:

    global _LOG_HANDLER

    app = FastAPI(
        title="Vrotex Bot V1 Dashboard API"
    )

    static_dir = Path(__file__).resolve().parent

    if _LOG_HANDLER is None:

        _LOG_HANDLER = DashboardLogHandler()
        _LOG_HANDLER.setLevel(logging.INFO)

        logging.getLogger().addHandler(
            _LOG_HANDLER
        )

    # --------------------------------------------------------
    # HOMEPAGE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # HEALTH
    # --------------------------------------------------------

    @app.get("/health")
    async def health():

        return await dashboard_state(bot)

    # --------------------------------------------------------
    # DASHBOARD STATUS
    # --------------------------------------------------------

    @app.get("/api/dashboard")
    async def dashboard():

        return await dashboard_state(bot)

    # --------------------------------------------------------
    # LIVE LOGS
    # --------------------------------------------------------

    @app.get("/api/logs")
    async def logs():

        return {
            "logs": make_json_safe(
                list(LOGS)
            )
        }

    # --------------------------------------------------------
    # HISTORICAL CHART CANDLES
    # --------------------------------------------------------

    @app.get("/api/chart/candles")
    async def chart_candles(

        symbol: str = Query(
            "EURUSD",
            min_length=6,
            max_length=10,
        ),

        timeframe: str = Query(
            "M5",
            min_length=2,
            max_length=3,
        ),

        count: int = Query(
            500,
            ge=1,
            le=MAX_CHART_CANDLES,
        ),

    ):

        symbol = symbol.upper().strip()
        timeframe = timeframe.upper().strip()

        if symbol not in CHART_INSTRUMENTS:

            raise HTTPException(
                status_code=400,
                detail="Instrument is not enabled for Vrotex V1",
            )

        if timeframe not in CHART_TIMEFRAMES:

            raise HTTPException(
                status_code=400,
                detail="Unsupported chart timeframe",
            )

        try:

            from market_data_engine import market_data_engine

            get_candles = getattr(
                market_data_engine,
                "get_recent_candles",
                None,
            )

            if not callable(get_candles):
                raise RuntimeError(
                    "MarketDataEngine.get_recent_candles is unavailable"
                )

            raw = await call_engine_method(
                get_candles,
                symbol,
                timeframe,
                count=count,
                price_type="bid",
            )

            bars = normalize_chart_candles(raw)[-count:]

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "price_type": "bid",
                "candles": bars,
                "count": len(bars),

                "source": (
                    "MARKET_DATA_ENGINE"
                    if bars
                    else "UNAVAILABLE"
                ),

                "message": (
                    None
                    if bars
                    else "No historical candles available from the market-data engine"
                ),
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
                    "Historical candle data unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ) from exc

    # --------------------------------------------------------
    # EXNESS ACCOUNT SNAPSHOT
    # --------------------------------------------------------

    @app.get("/api/account")
    async def account_snapshot():

        try:

            from exness_connection import exness_connection


            if not exness_connection.connected:
                raise RuntimeError("No Exness account is connected.")

            details = await exness_connection.get_trading_snapshot()

            connection = exness_connection.get_connection_status()


            if not isinstance(details, dict):

                raise RuntimeError(
                    "Exness account endpoint returned an unexpected payload"
                )

                        account_state = details.get("account_state", {})

            if not isinstance(account_state, dict):
                account_state = {}

            def to_number(value):
                try:
                    number = float(value)
                    return number if math.isfinite(number) else None
                except (TypeError, ValueError):
                    return None

            balance = to_number(account_state.get("balance"))
            equity = to_number(account_state.get("equity"))
            margin = to_number(account_state.get("used_margin"))

            profit = (
                round(equity - balance, 2)
                if equity is not None and balance is not None
                else None
            )

            free_margin = (
                round(equity - margin, 2)
                if equity is not None and margin is not None
                else None
            )

            margin_level = (
                round((equity / margin) * 100, 2)
                if equity is not None and margin is not None and margin > 0
                else None
            )

            normalized = {
                "balance": balance,
                "equity": equity,
                "profit": profit,
                "margin": margin,
                "free_margin": free_margin,
                "margin_level": margin_level,
                "currency": account_state.get("currency"),
            }

            return {
                "status": "ok",
                "connected": (
                    bool(connection.get("connected"))
                    if isinstance(connection, dict)
                    else False
                ),

                "account_id": (
                    connection.get("account_id")
                    if isinstance(connection, dict)
                    else None
                ),

                "account": normalized,
                "raw": make_json_safe(details),

                "updated_at": (
                    datetime.now(timezone.utc).isoformat()
                ),
            }

        except Exception as exc:

            logging.getLogger(__name__).exception(
                "Exness account snapshot failed"
            )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Account data unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ) from exc
    # --------------------------------------------------------
    # EXNESS OPEN POSITIONS AND PENDING ORDERS
    # --------------------------------------------------------

    @app.get("/api/positions")
    async def positions_snapshot():

        try:
            from exness_connection import exness_connection

            if not exness_connection.connected:
                raise RuntimeError("No Exness account is connected.")

            details = await exness_connection.get_trading_snapshot()

            if not isinstance(details, dict):
                raise RuntimeError(
                    "Exness trading snapshot returned an unexpected payload"
                )

            positions = details.get("positions", [])
            orders = details.get("orders", [])

            if not isinstance(positions, list):
                positions = []

            if not isinstance(orders, list):
                orders = []

            connection = exness_connection.get_connection_status()

            return {
                "status": "ok",
                "connected": (
                    bool(connection.get("connected"))
                    if isinstance(connection, dict)
                    else False
                ),
                "positions": make_json_safe(positions),
                "orders": make_json_safe(orders),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as exc:
            logging.getLogger(__name__).exception(
                "Exness positions snapshot failed"
            )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Position data unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ) from exc
    
    # --------------------------------------------------------
    # LIVE CHART TICK
    # --------------------------------------------------------

    @app.get("/api/chart/tick")
    async def chart_tick(

        symbol: str = Query(
            "EURUSD",
            min_length=6,
            max_length=10,
        ),

    ):

        symbol = symbol.upper().strip()

        if symbol not in CHART_INSTRUMENTS:

            raise HTTPException(
                status_code=400,
                detail="Instrument is not enabled for Vrotex V1",
            )

        try:

            from market_data_engine import market_data_engine

            tick = await get_engine_tick(
                market_data_engine,
                symbol,
            )

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

            return {
                "symbol": symbol,
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
                "mid": tick.get("mid"),
                "spread": tick.get("spread"),
                "age_seconds": tick.get("age_seconds"),
                "fresh": bool(tick.get("fresh", False)),
                "reason": tick.get("reason"),
            }

        except HTTPException:
            raise

        except Exception as exc:

            logging.getLogger(__name__).exception(
                "Chart tick request failed for %s",
                symbol,
            )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Live quote unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ) from exc

    # --------------------------------------------------------
    # START BOT
    # --------------------------------------------------------

    @app.post("/api/bot/start")
    async def start_bot():

        return await control(
            bot,
            "start",
        )

    # --------------------------------------------------------
    # STOP BOT
    # --------------------------------------------------------

    @app.post("/api/bot/stop")
    async def stop_bot():

        return await control(
            bot,
            "stop",
        )

    # --------------------------------------------------------
    # LIVE LOG WEBSOCKET
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EXNESS BROKER CONNECTION
    # --------------------------------------------------------

    @app.post("/api/broker/connect")
    async def connect_broker(request: Request):

        try:
            payload = await request.json()

            api_key = payload.get("api_key") or payload.get("apiKey")
            private_key = (
                payload.get("private_key")
                or payload.get("privateKey")
                or payload.get("secret")
            )
            account_id = (
                payload.get("account_id")
                or payload.get("accountId")
            )
            gateway = (
                payload.get("gateway_host")
                or payload.get("gateway")
                or payload.get("server")
            )
            account_type = str(
                payload.get("account_type")
                or payload.get("account_mode")
                or payload.get("mode")
                or ""
            ).strip().upper()

            if account_type not in {"DEMO", "LIVE"}:
                raise HTTPException(
                    status_code=400,
                    detail="Select DEMO or LIVE."
                )

            if not all((api_key, private_key, account_id, gateway)):
                raise HTTPException(
                    status_code=400,
                    detail="Complete all Exness connection fields."
                )

            from exness_connection import exness_connection

            await exness_connection.disconnect()

            exness_connection.api_key = str(api_key).strip()
            exness_connection.private_key_text = str(private_key)
            exness_connection.account_id = str(account_id).strip()
            exness_connection.gateway_host = str(gateway).strip().rstrip("/")

            exness_connection.access_point = None
            exness_connection.account_info = None
            exness_connection.account_type = account_type

            result = await exness_connection.connect()

            return {
                "success": True,
                "connected": True,
                "broker": "Exness",
                "account_type": account_type,
                "account_id": exness_connection.account_id,
                "account": make_json_safe(result.get("account")),
                "connection": exness_connection.get_connection_status(),
            }

        except HTTPException:
            raise

        except Exception as exc:
            logging.getLogger(__name__).exception(
                "Exness Broker connection failed."
            )

            raise HTTPException(
                status_code=502,
                detail=f"Exness connection failed: {type(exc).__name__}: {exc}"
            ) from exc


    # --------------------------------------------------------
    # VROTEX AI CHAT API
    # Connects the dashboard chat to the AI brain.
    # --------------------------------------------------------

    @app.post("/api/ai/chat")
    async def ai_chat(request: Request):

        try:

            payload = await request.json()

            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid chat request."
                )

            message = str(
                payload.get("message") or ""
            ).strip()

            conversation_id = payload.get(
                "conversation_id"
            )

            if not message:
                raise HTTPException(
                    status_code=400,
                    detail="Please enter a message."
                )

            if len(message) > 12000:
                raise HTTPException(
                    status_code=400,
                    detail="Message is too long."
                )

            from vrotex_ai_brain import (
                vrotex_ai_brain,
                AIConfigurationError,
                AIProviderError,
            )

            result = await vrotex_ai_brain.chat(
                message=message,
                conversation_id=conversation_id,
            )

            return {
                "success": True,
                "conversation_id": result["conversation_id"],
                "reply": result["reply"],
                "model": result["model"],
            }

        except HTTPException:
            raise

        except AIConfigurationError as exc:

            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc

        except AIProviderError as exc:

            logging.getLogger(__name__).exception(
                "Vrotex AI provider request failed."
            )

            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        except ValueError as exc:

            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        except Exception as exc:

            logging.getLogger(__name__).exception(
                "Vrotex AI chat endpoint failed."
            )

            raise HTTPException(
                status_code=500,
                detail="Vrotex AI chat encountered an internal error."
            ) from exc

    
    return app


# ============================================================
# DASHBOARD STATE
# ============================================================

async def dashboard_state(
    bot: Any,
) -> dict[str, Any]:

    errors = {}

    engine_status = {}
    market_status = {}
    state = {}
    quotes = []

    market_data_engine = None

    # --------------------------------------------------------
    # TRADING ENGINE STATUS
    # --------------------------------------------------------

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

        errors["engine"] = (
            f"{type(exc).__name__}: {exc}"
        )

        engine_status = {
            "available": False,
            "error": errors["engine"],
        }

    # --------------------------------------------------------
    # MARKET DATA STATUS
    # --------------------------------------------------------

    try:

        from market_data_engine import market_data_engine

        try:

            market_status = (
                market_data_engine.get_status()
            )

        except Exception as exc:

            errors["market_data"] = (
                f"{type(exc).__name__}: {exc}"
            )

            market_status = {
                "available": False,
                "error": errors["market_data"],
            }

    except Exception as exc:

        errors["market_data"] = (
            f"{type(exc).__name__}: {exc}"
        )

        market_status = {
            "available": False,
            "error": errors["market_data"],
        }

    # --------------------------------------------------------
    # STATE MANAGER
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # LIVE QUOTES
    # --------------------------------------------------------

    if market_data_engine is not None:

        for symbol in (
            "EURUSD",
            "GBPUSD",
            "BTCUSD",
        ):

            try:

                tick = await get_engine_tick(
                    market_data_engine,
                    symbol,
                )

                if tick:

                    quotes.append({
                        "symbol": symbol,
                        "bid": tick.get("bid"),
                        "ask": tick.get("ask"),
                        "mid": tick.get("mid"),
                        "spread": tick.get("spread"),
                        "age_seconds": tick.get("age_seconds"),
                        "fresh": bool(tick.get("fresh", False)),
                        "reason": tick.get("reason"),
                    })

                else:

                    quotes.append({
                        "symbol": symbol,
                        "bid": None,
                        "ask": None,
                        "mid": None,
                        "spread": None,
                        "age_seconds": None,
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
                    "mid": None,
                    "spread": None,
                    "age_seconds": None,
                    "fresh": False,
                    "reason": "QUOTE UNAVAILABLE",
                })

    else:

        quotes = [
            {
                "symbol": symbol,
                "bid": None,
                "ask": None,
                "mid": None,
                "spread": None,
                "age_seconds": None,
                "fresh": False,
                "reason": "MARKET DATA ENGINE UNAVAILABLE",
            }

            for symbol in (
                "EURUSD",
                "GBPUSD",
                "BTCUSD",
            )
        ]

    # --------------------------------------------------------
    # ENGINE RUNNING STATE
    # --------------------------------------------------------

    engine_task = getattr(
        bot,
        "engine_task",
        None,
    )

    try:

        running = bool(
            engine_task is not None
            and not engine_task.done()
        )

    except Exception:
        running = False

    response = {
        "status": "ok",
        "bot": "Vrotex Bot V1",
        "running": running,

        "engine": make_json_safe(
            engine_status
        ),

        "state": make_json_safe(
            state
        ),

        "market_data": make_json_safe(
            market_status
        ),

        "quotes": make_json_safe(
            quotes
        ),

        "logs": make_json_safe(
            list(LOGS)[-30:]
        ),
    }

    if errors:
        response["component_errors"] = errors

    return response


# ============================================================
# FUNCTIONAL BOT CONTROL
# ============================================================

async def control(
    bot: Any,
    action: str,
) -> dict[str, Any]:

    action = action.lower().strip()

    logger = logging.getLogger(__name__)

    if action not in ("start", "stop"):

        raise HTTPException(
            status_code=400,
            detail="Invalid bot control action",
        )

    # --------------------------------------------------------
    # START EXISTING TRADING ENGINE
    # --------------------------------------------------------

    if action == "start":

        start_method = getattr(
            bot,
            "start_engine",
            None,
        )

        if not callable(start_method):

            raise HTTPException(
                status_code=503,
                detail=(
                    "The existing Vrotex start_engine "
                    "method is unavailable."
                ),
            )

        try:

            logger.info(
                "Dashboard requested Vrotex Bot V1 START."
            )

            result = await start_method()

            is_running_method = getattr(
                bot,
                "is_engine_running",
                None,
            )

            running = (
                bool(is_running_method())
                if callable(is_running_method)
                else False
            )

            if isinstance(result, dict):

                response = dict(result)

                response["running"] = running

                response["action"] = "start"

                return response

            return {
                "success": running,
                "running": running,
                "action": "start",
                "message": (
                    "Vrotex trading engine started."
                    if running
                    else "Vrotex trading engine did not start."
                ),
            }

        except HTTPException:
            raise

        except Exception as exc:

            logger.exception(
                "Dashboard START command failed."
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    "Vrotex engine startup failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ) from exc

    # --------------------------------------------------------
    # STOP EXISTING TRADING ENGINE
    # --------------------------------------------------------

    stop_method = getattr(
        bot,
        "stop_engine",
        None,
    )

    if not callable(stop_method):

        raise HTTPException(
            status_code=503,
            detail=(
                "The existing Vrotex stop_engine "
                "method is unavailable."
            ),
        )

    try:

        logger.warning(
            "Dashboard requested Vrotex Bot V1 STOP."
        )

        result = await stop_method()

        is_running_method = getattr(
            bot,
            "is_engine_running",
            None,
        )

        running = (
            bool(is_running_method())
            if callable(is_running_method)
            else False
        )

        if isinstance(result, dict):

            response = dict(result)

            response["running"] = running

            response["action"] = "stop"

            return response

        return {
            "success": not running,
            "running": running,
            "action": "stop",
            "message": (
                "Vrotex trading engine stopped."
                if not running
                else "Vrotex trading engine is still running."
            ),
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "Dashboard STOP command failed."
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Vrotex engine shutdown failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc
