
from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections import deque
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
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


# ---------------------------------------------------------
# MARKET DATA ENGINE RESOLUTION
# ---------------------------------------------------------

def resolve_market_data_engine(bot: Any):
    """
    Resolve the existing MarketDataEngine instance.

    The running Vrotex runtime stores this instance in:
        runtime["market_data_engine"]

    Do not instantiate another MarketDataEngine here.
    A second instance would not contain the live runtime's
    candles, ticks, or connection state.
    """

    candidates = []

    if isinstance(bot, dict):
        candidates.append(bot.get("market_data_engine"))
        candidates.append(bot.get("runtime"))
        candidates.append(bot.get("engine"))

    else:
        candidates.append(getattr(bot, "market_data_engine", None))
        candidates.append(getattr(bot, "runtime", None))
        candidates.append(getattr(bot, "engine", None))

    # Also inspect an existing engine module if available.
    try:
        import engine as engine_module

        candidates.append(getattr(engine_module, "engine", None))
        candidates.append(getattr(engine_module, "runtime", None))

    except Exception:
        pass

    seen = set()
    queue = list(candidates)

    for _ in range(30):
        if not queue:
            break

        obj = queue.pop(0)

        if obj is None or id(obj) in seen:
            continue

        seen.add(id(obj))

        # Runtime dictionary used by the Vrotex main application.
        if isinstance(obj, dict):
            market_engine = obj.get("market_data_engine")

            if market_engine is not None:
                queue.append(market_engine)

            for key in ("runtime", "engine", "bot"):
                child = obj.get(key)
                if child is not None:
                    queue.append(child)

            continue

        # Identify the actual market-data engine by its methods.
        if (
            callable(getattr(obj, "get_historical_candles", None))
            and callable(getattr(obj, "get_status", None))
        ):
            return obj

        for name in (
            "market_data_engine",
            "market_data",
            "data_engine",
            "market_engine",
            "md_engine",
            "runtime",
        ):
            try:
                child = getattr(obj, name, None)
                if child is not None:
                    queue.append(child)
            except Exception:
                pass

    raise RuntimeError(
        "The running Vrotex runtime does not expose its existing "
        "MarketDataEngine instance. No second engine was created."
    )


# ---------------------------------------------------------
# LIVE TICK EXTRACTION
# ---------------------------------------------------------

def get_engine_tick(engine, symbol: str):
    """Read the latest tick from the existing market-data engine."""

    ticks = getattr(engine, "last_tick_by_instrument", None)

    if isinstance(ticks, dict):
        tick = ticks.get(symbol) or ticks.get(symbol.upper())

        if isinstance(tick, dict):
            result = dict(tick)
            stamp = result.get("timestamp")

            try:
                if isinstance(stamp, str):
                    dt = datetime.fromisoformat(
                        stamp.replace("Z", "+00:00")
                    )

                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    age = max(
                        0.0,
                        (
                            datetime.now(timezone.utc)
                            - dt.astimezone(timezone.utc)
                        ).total_seconds(),
                    )

                elif isinstance(stamp, (int, float)):
                    seconds = (
                        float(stamp) / 1000
                        if float(stamp) > 100_000_000_000
                        else float(stamp)
                    )

                    age = max(
                        0.0,
                        datetime.now(timezone.utc).timestamp() - seconds,
                    )

                else:
                    age = None

            except Exception:
                age = None

            result["age_seconds"] = age
            result["fresh"] = age is not None and age <= 120

            if result.get("bid") is not None and result.get("ask") is not None:
                result["mid"] = (
                    float(result["bid"]) + float(result["ask"])
                ) / 2

                result["spread"] = (
                    float(result["ask"]) - float(result["bid"])
                )

            return result

    # Support engines that expose a getter instead of a public dictionary.
    getter = getattr(engine, "get_live_tick", None)

    if callable(getter):
        try:
            tick = getter(symbol)
            if isinstance(tick, dict):
                return tick
        except Exception:
            pass

    return None


# ---------------------------------------------------------
# CANDLE NORMALIZATION
# ---------------------------------------------------------

def candle_time_to_unix(value: Any) -> int:
    """Convert candle timestamps to Lightweight Charts Unix seconds."""

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
            raise ValueError("Candle is missing its time value")

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
            f"Unsupported candle time type: {type(value).__name__}"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return int(dt.astimezone(timezone.utc).timestamp())


def normalize_chart_candles(raw_candles: Any) -> list[dict[str, Any]]:
    """Return sorted, unique OHLC bars in Lightweight Charts format."""

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

    by_time: dict[int, dict[str, Any]] = {}

    for candle in raw_candles:
        if not isinstance(candle, dict):
            continue

        try:
            stamp = candle_time_to_unix(
                candle.get("time", candle.get("timestamp"))
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
                map(
                    lambda number:
                    number == number
                    and abs(number) != float("inf"),
                    values,
                )
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


# ---------------------------------------------------------
# CANDLE CACHE ACCESS
# ---------------------------------------------------------

def get_cached_candles(engine, symbol, timeframe, count):
    """
    Read the existing engine candle cache.

    The Vrotex MarketDataEngine cache uses:
        (instrument, timeframe, price_type)

    This function does not create or replace the cache.
    """

    cache = getattr(engine, "candle_cache", None)

    if not isinstance(cache, dict):
        return []

    keys = (
        (symbol, timeframe, "bid"),
        (symbol.upper(), timeframe.upper(), "bid"),
    )

    for key in keys:
        candles = cache.get(key)

        if isinstance(candles, (list, tuple)):
            return list(candles)[-count:]

    return []


# ---------------------------------------------------------
# DASHBOARD LOGGING
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# FASTAPI APPLICATION
# ---------------------------------------------------------

def create_app(bot: Any) -> FastAPI:
    global _LOG_HANDLER

    app = FastAPI(
        title="Vrotex Bot V1 Dashboard API"
    )

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

    # -----------------------------------------------------
    # HISTORICAL CHART CANDLES
    # -----------------------------------------------------

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

        timeframe_seconds = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }

        try:
            # Resolve the actual running engine from the bot runtime.
            market_engine = resolve_market_data_engine(bot)

            # First read the existing in-memory candle cache.
            raw = await asyncio.to_thread(
                get_cached_candles,
                market_engine,
                symbol,
                timeframe,
                count,
            )

            bars = normalize_chart_candles(raw)

            # Request additional history only when the cache is short.
            if len(bars) < count:

                end = datetime.now(timezone.utc)

                start = end - timedelta(
                    seconds=timeframe_seconds[timeframe] * count
                )

                fetched = await asyncio.to_thread(
                    market_engine.get_historical_candles,
                    symbol,
                    timeframe,
                    start,
                    end,
                    "bid",
                )

                # Merge cache and fetched candles without duplicates.
                bars = normalize_chart_candles(
                    list(raw or []) + list(fetched or [])
                )

            bars = bars[-count:]

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "price_type": "bid",
                "candles": bars,
                "count": len(bars),

                "source": (
                    "ENGINE_CACHE_AND_EXNESS"
                    if bars
                    else "UNAVAILABLE"
                ),

                "message": (
                    None
                    if bars
                    else "No historical candles available from cache or Exness"
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

    # -----------------------------------------------------
    # EXNESS ACCOUNT API
    # -----------------------------------------------------

    @app.get("/api/account")
    async def account_snapshot():

        try:
            from exness_connection import (
                get_account_details,
                engine_status,
            )

            details = await asyncio.to_thread(
                get_account_details
            )

            connection = await asyncio.to_thread(
                engine_status
            )

            if not isinstance(details, dict):
                raise RuntimeError(
                    "Exness account endpoint returned an unexpected payload"
                )

            def find_value(data, aliases):

                if isinstance(data, dict):

                    for key, value in data.items():
                        if (
                            str(key).lower() in aliases
                            and value is not None
                        ):
                            return value

                    for value in data.values():
                        found = find_value(
                            value,
                            aliases,
                        )

                        if found is not None:
                            return found

                elif isinstance(data, (list, tuple)):

                    for item in data:
                        found = find_value(
                            item,
                            aliases,
                        )

                        if found is not None:
                            return found

                return None

            fields = {
                "balance": {
                    "balance",
                    "account_balance",
                },

                "equity": {
                    "equity",
                    "account_equity",
                },

                "profit": {
                    "profit",
                    "floating_profit",
                    "unrealized_profit",
                    "pnl",
                    "pl",
                },

                "margin": {
                    "margin",
                    "used_margin",
                },

                "free_margin": {
                    "free_margin",
                    "available_margin",
                },

                "margin_level": {
                    "margin_level",
                    "marginlevel",
                },

                "currency": {
                    "currency",
                    "account_currency",
                },
            }

            normalized = {
                key: find_value(details, aliases)
                for key, aliases in fields.items()
            }

            return {
                "status": "ok",
                "connected": bool(
                    connection.get("connected")
                ) if isinstance(connection, dict) else False,

                "account_id": (
                    connection.get("account_id")
                    if isinstance(connection, dict)
                    else None
                ),

                "account": normalized,

                "raw": make_json_safe(details),

                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
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

    # -----------------------------------------------------
    # LIVE TICK API
    # -----------------------------------------------------

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
            market_engine = resolve_market_data_engine(bot)

            tick = get_engine_tick(
                market_engine,
                symbol,
            )

            if not tick:
                return {
                    "symbol": symbol,
                    "bid": None,
                    "ask": None,
                    "fresh": False,
                    "reason": "NO LIVE TICK",
                }

            safe_tick = make_json_safe(tick)

            if not isinstance(safe_tick, dict):
                safe_tick = {}

            return {
                "symbol": symbol,
                "bid": safe_tick.get("bid"),
                "ask": safe_tick.get("ask"),
                "mid": safe_tick.get("mid"),
                "spread": safe_tick.get("spread"),

                "age_seconds": safe_tick.get(
                    "age_seconds",
                    safe_tick.get("age"),
                ),

                "fresh": bool(
                    safe_tick.get("fresh", False)
                ),

                "reason": (
                    None
                    if safe_tick.get("fresh")
                    else "STALE / MARKET CLOSED"
                ),
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

    # -----------------------------------------------------
    # BOT CONTROL — EXISTING SECURITY GATE
    # -----------------------------------------------------

    @app.post("/api/bot/start")
    async def start_bot():
        return await control(bot, "start")

    @app.post("/api/bot/stop")
    async def stop_bot():
        return await control(bot, "stop")

    # -----------------------------------------------------
    # LIVE LOG WEBSOCKET
    # -----------------------------------------------------

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


# ---------------------------------------------------------
# DASHBOARD STATE
# ---------------------------------------------------------

async def dashboard_state(bot: Any) -> dict[str, Any]:

    errors = {}
    engine_status = {}
    market_status = {}
    state = {}
    quotes = []
    market_engine = None

    # Trading engine status.
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

    # Resolve the actual market-data instance.
    try:
        market_engine = resolve_market_data_engine(bot)

        market_status = await asyncio.to_thread(
            market_engine.get_status
        )

    except Exception as exc:
        errors["market_data"] = (
            f"{type(exc).__name__}: {exc}"
        )

        market_status = {
            "available": False,
            "error": errors["market_data"],
        }

    # State manager.
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

    # Live quotes.
    for symbol in (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    ):

        try:
            if market_engine is None:
                raise RuntimeError(
                    "Market-data engine unavailable"
                )

            tick = get_engine_tick(
                market_engine,
                symbol,
            )

            if tick:
                tick = make_json_safe(tick)

                if not isinstance(tick, dict):
                    tick = {}

                fresh = bool(
                    tick.get("fresh", False)
                )

                quotes.append({
                    "symbol": symbol,
                    "bid": tick.get("bid"),
                    "ask": tick.get("ask"),
                    "fresh": fresh,

                    "reason": (
                        None
                        if fresh
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

    # Engine task state.
    engine_task = getattr(
        bot,
        "engine_task",
        None,
    )

    # Support a runtime dictionary without assuming it has an asyncio task.
    if isinstance(bot, dict):
        engine_task = bot.get("engine_task")

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


# ---------------------------------------------------------
# CONTROL SECURITY
# ---------------------------------------------------------

async def control(bot: Any, action: str) -> dict[str, Any]:

    # Preserve the existing security gate.
    # Remote bot control remains disabled.

    raise HTTPException(
        status_code=503,
        detail=(
            "Dashboard control is not enabled yet. "
            "Secure control setup is required before "
            "remote start/stop can be activated."
        ),
    )
