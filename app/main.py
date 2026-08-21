"""跨境电商无货源代发 · Agent Team 仿真服务。"""
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from simulation import Engine, SKUS

app = FastAPI(title="Dropshipping Sim")
engine = Engine()
STATIC = Path(__file__).parent / "static"


async def tick_loop():
    while True:
        if engine.running:
            engine.tick()
        await asyncio.sleep(engine.speed)


@app.on_event("startup")
async def startup():
    asyncio.create_task(tick_loop())


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
async def state():
    return engine.snapshot()


class Control(BaseModel):
    action: str           # start / pause / reset
    speed: float | None = None


@app.post("/api/control")
async def control(c: Control):
    global engine
    if c.action == "start":
        engine.running = True
        engine.log("系统", "仿真启动")
    elif c.action == "pause":
        engine.running = False
        engine.log("系统", "仿真暂停")
    elif c.action == "reset":
        running = engine.running
        engine = Engine()
        engine.running = running
        engine.log("系统", "仿真已重置")
    if c.speed is not None:
        engine.speed = max(0.1, min(2.0, c.speed))
    return engine.snapshot()


class ManualOrder(BaseModel):
    sku: str
    qty: int = 1
    method: str = "air"
    country: str = "美国"


@app.post("/api/order")
async def manual_order(mo: ManualOrder):
    sku = next((s for s in SKUS if s["id"] == mo.sku), None)
    if not sku:
        return {"ok": False, "msg": "SKU 不存在"}
    o = engine.new_order("手动客户", mo.country, sku, max(1, min(9, mo.qty)), mo.method)
    return {"ok": True, "order": o.to_dict()}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
