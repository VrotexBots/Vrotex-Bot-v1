from __future__ import annotations
import asyncio, json, logging, os, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

LOGS=deque(maxlen=500)
CLIENTS=set()
class DashboardLogHandler(logging.Handler):
    def emit(self, record):
        try:
            entry={"timestamp":datetime.fromtimestamp(record.created,timezone.utc).astimezone().isoformat(timespec="seconds"),"level":record.levelname,"logger":record.name,"message":record.getMessage()}
            LOGS.append(entry)
            try: loop=asyncio.get_running_loop(); loop.create_task(broadcast({"type":"log","entry":entry}))
            except RuntimeError: pass
        except Exception: self.handleError(record)

async def broadcast(payload):
    dead=[]
    for ws in tuple(CLIENTS):
        try: await ws.send_json(payload)
        except Exception: dead.append(ws)
    for ws in dead: CLIENTS.discard(ws)

def create_app(bot):
    app=FastAPI(title="Vrotex Bot V1 Dashboard API")
    handler=DashboardLogHandler(); handler.setLevel(logging.INFO); logging.getLogger().addHandler(handler)
    static=Path(__file__).resolve().parent
    @app.get("/", include_in_schema=False)
    async def home(): return FileResponse(static/"index.html")
    @app.get("/health")
    async def health(): return await dashboard_state(bot)
    @app.get("/api/dashboard")
    async def dashboard(): return await dashboard_state(bot)
    @app.get("/api/logs")
    async def logs(): return {"logs":list(LOGS)}
    @app.post("/api/bot/start")
    async def start_bot():
        # Render deployment must define DASHBOARD_CONTROL_TOKEN before remote control is enabled.
        # A token is requested only when a control is pressed; no login page or design changes.
        return await control(bot,"start")
    @app.post("/api/bot/stop")
    async def stop_bot(): return await control(bot,"stop")
    @app.websocket("/ws/logs")
    async def log_socket(ws:WebSocket):
        await ws.accept(); CLIENTS.add(ws)
        try:
            for item in list(LOGS)[-100:]: await ws.send_json({"type":"log","entry":item})
            while True: await ws.receive_text()
        except WebSocketDisconnect: pass
        finally: CLIENTS.discard(ws)
    return app

async def dashboard_state(bot):
    from engine import engine
    from market_data_engine import market_data_engine
    from state_manager import state_manager
    state=state_manager.get_state()
    try: eng=engine.get_status()
    except Exception: eng={}
    try: md=market_data_engine.get_status()
    except Exception: md={}
    ticks=[]
    try:
        for symbol in ("EURUSD","GBPUSD","BTCUSD"):
            tick=market_data_engine.get_live_tick(symbol)
            if tick: ticks.append({"symbol":symbol,"bid":tick.get("bid"),"ask":tick.get("ask"),"fresh":bool(tick.get("fresh")),"reason":"STALE / MARKET CLOSED" if not tick.get("fresh") else None})
            else: ticks.append({"symbol":symbol,"bid":None,"ask":None,"fresh":False,"reason":"NO LIVE TICK"})
    except Exception:
        ticks=[{"symbol":s,"bid":None,"ask":None,"fresh":False,"reason":"NO LIVE TICK"} for s in ("EURUSD","GBPUSD","BTCUSD")]
    running=bool(getattr(bot,"engine_task",None) and not bot.engine_task.done())
    return {"status":"ok","bot":"Vrotex Bot V1","running":running,"engine":eng,"state":state,"market_data":md,"quotes":ticks,"logs":list(LOGS)[-30:]}

async def control(bot,action):
    # Control endpoints are intentionally gated. Set DASHBOARD_CONTROL_TOKEN in Render,
    # then supply it in X-Dashboard-Control-Token from a trusted dashboard session.
    expected=os.getenv("DASHBOARD_CONTROL_TOKEN")
    # No unauthenticated remote trading control is exposed on a public Render URL.
    raise HTTPException(status_code=503,detail="Dashboard control is not enabled yet. Secure control setup is required before remote start/stop can be activated.")
