"""规则驱动的跨境电商无货源代发仿真引擎 + 四类 Agent。"""
from __future__ import annotations

import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

# ---------------- 基础数据 ----------------

SKUS = [
    {"id": "SKU-01", "name": "便携榨汁杯", "price": 25.99, "stock": 40},
    {"id": "SKU-02", "name": "LED 化妆镜", "price": 18.50, "stock": 35},
    {"id": "SKU-03", "name": "迷你投影仪", "price": 89.99, "stock": 15},
    {"id": "SKU-04", "name": "无线降噪耳机", "price": 45.00, "stock": 25},
    {"id": "SKU-05", "name": "智能跳绳", "price": 15.80, "stock": 50},
]

BUYER_PROFILES = [
    ("Mike", "美国"), ("Emma", "英国"), ("Lukas", "德国"),
    ("Yuki", "日本"), ("Chloe", "澳大利亚"), ("Lucas", "加拿大"),
]

# 订单状态流转（正常路径）
FLOW = [
    "PAID",        # 买家已付款
    "FORWARDED",   # 卖家已转发工厂
    "ACCEPTED",    # 工厂已接单
    "PRODUCING",   # 缺货补货生产（异常分支）
    "QC",          # 质检
    "PACKED",      # 打包完成
    "SHIPPED",     # 物流揽收
    "LINEHAUL",    # 国际干线
    "CUSTOMS",     # 清关
    "LAST_MILE",   # 末端派送
    "DELIVERED",   # 签收
]

STATUS_CN = {
    "PAID": "已付款", "FORWARDED": "已转发工厂", "ACCEPTED": "工厂已接单",
    "PRODUCING": "缺货生产中", "QC": "质检中", "PACKED": "已打包",
    "SHIPPED": "物流揽收", "LINEHAUL": "国际干线", "CUSTOMS": "清关中",
    "LAST_MILE": "末端派送", "DELIVERED": "已签收",
    "REFUND_REQUESTED": "退款申请中", "REFUNDED": "已退款", "CANCELLED": "缺货取消",
}

EXCEPTION_STATUSES = {"PRODUCING", "REFUND_REQUESTED", "REFUNDED", "CANCELLED"}


@dataclass
class Order:
    id: str
    buyer: str
    country: str
    sku: str
    sku_name: str
    qty: int
    amount: float
    method: str           # air / sea
    status: str = "PAID"
    created_at: int = 0   # sim hour
    updated_at: int = 0
    eta: int = 0          # 预计送达 sim hour
    note: str = ""

    def to_dict(self):
        return {
            "id": self.id, "buyer": self.buyer, "country": self.country,
            "sku": self.sku, "sku_name": self.sku_name, "qty": self.qty,
            "amount": round(self.amount, 2), "method": self.method,
            "status": self.status, "status_cn": STATUS_CN[self.status],
            "created_at": self.created_at, "eta": self.eta, "note": self.note,
        }


class Engine:
    """仿真引擎：1 tick = 1 模拟小时，驱动所有 Agent。"""

    def __init__(self):
        self.clock = 0                    # 当前模拟小时
        self.running = False
        self.speed = 0.5                  # 每个 tick 真实秒数
        self.orders: dict[str, Order] = {}
        self.sku_stock = {s["id"]: s["stock"] for s in SKUS}
        self.events: deque = deque(maxlen=300)
        self.seq = 0
        self.metrics = {
            "revenue": 0.0, "delivered": 0, "refunded": 0, "cancelled": 0,
            "total_hours": 0, "on_time": 0,
        }
        self.buyers = [BuyerAgent(*p) for p in BUYER_PROFILES]
        self.seller = SellerAgent()
        self.factory = FactoryAgent()
        self.logistics = LogisticsAgent()
        self.agents = {a.name: a for a in [self.seller, self.factory, self.logistics]}
        self.log("系统", "仿真引擎初始化完成，等待启动")

    # ---------- 事件与订单 ----------
    def log(self, who: str, msg: str, level: str = "info"):
        self.events.appendleft({
            "t": self.clock, "who": who, "msg": msg, "level": level,
        })

    def new_order(self, buyer: str, country: str, sku: dict, qty: int, method: str) -> Order:
        self.seq += 1
        o = Order(
            id=f"DD{self.seq:05d}", buyer=buyer, country=country,
            sku=sku["id"], sku_name=sku["name"], qty=qty,
            amount=round(sku["price"] * qty, 2), method=method,
            created_at=self.clock, updated_at=self.clock,
            eta=self.clock + (60 if method == "air" else 180),
        )
        self.orders[o.id] = o
        self.log("买家", f"{buyer}（{country}）下单 {sku['name']} x{qty}，支付 ${o.amount}（{'空运' if method == 'air' else '海运'}）")
        return o

    def advance(self, order: Order, status: str, who: str, msg: str, level: str = "info"):
        order.status = status
        order.updated_at = self.clock
        self.log(who, f"[{order.id}] {msg}", level)

    # ---------- 主循环 ----------
    def tick(self):
        self.clock += 1
        for b in self.buyers:
            b.tick(self)
        self.seller.tick(self)
        self.factory.tick(self)
        self.logistics.tick(self)

    def snapshot(self) -> dict:
        active = [o for o in self.orders.values() if o.status not in ("DELIVERED", "REFUNDED", "CANCELLED")]
        return {
            "clock": self.clock,
            "day": self.clock // 24 + 1,
            "hour": self.clock % 24,
            "running": self.running,
            "speed": self.speed,
            "metrics": {
                **self.metrics,
                "revenue": round(self.metrics["revenue"], 2),
                "total_orders": len(self.orders),
                "active": len(active),
                "avg_hours": round(self.metrics["total_hours"] / self.metrics["delivered"], 1) if self.metrics["delivered"] else 0,
                "on_time_rate": round(self.metrics["on_time"] / self.metrics["delivered"] * 100, 1) if self.metrics["delivered"] else 100,
            },
            "agents": [a.status_dict(self) for a in [self.seller, self.factory, self.logistics]],
            "buyers": [b.status_dict(self) for b in self.buyers],
            "orders": [o.to_dict() for o in sorted(self.orders.values(), key=lambda x: -x.created_at)[:15]],
            "events": list(self.events)[:60],
            "stock": {s["id"]: {"name": s["name"], "left": self.sku_stock[s["id"]]} for s in SKUS},
        }

    def reset(self):
        self.__init__()


# ---------------- Agent 基类 ----------------

class Agent:
    name = "agent"
    cn = "Agent"

    def __init__(self):
        self.busy_with: str | None = None
        self.done_count = 0

    def status_dict(self, engine: Engine) -> dict:
        return {"name": self.name, "cn": self.cn, "busy_with": self.busy_with, "done": self.done_count}


class BuyerAgent(Agent):
    """海外买家：随机下单，超时未送达会申请退款。"""

    cn = "买家"

    def __init__(self, alias: str, country: str):
        super().__init__()
        self.name = f"buyer_{alias}"
        self.alias = alias
        self.country = country
        self.patience = random.randint(24, 72)   # 超过 ETA 多少小时后退款

    def tick(self, e: Engine):
        mine = [o for o in e.orders.values() if o.buyer == self.alias]
        active = [o for o in mine if o.status not in ("DELIVERED", "REFUNDED", "CANCELLED")]
        # 下单：活跃订单少于 2 时，每小时约 2% 概率
        if len(active) < 2 and random.random() < 0.02:
            sku = random.choice(SKUS)
            qty = random.randint(1, 3)
            method = "air" if random.random() < 0.6 else "sea"
            e.new_order(self.alias, self.country, sku, qty, method)
        # 催单 / 退款
        for o in active:
            if o.status != "REFUND_REQUESTED" and e.clock > o.eta + self.patience:
                e.advance(o, "REFUND_REQUESTED", "买家",
                          f"{self.alias} 等太久了，申请退款！", "warn")

    def status_dict(self, e: Engine) -> dict:
        active = sum(1 for o in e.orders.values()
                     if o.buyer == self.alias and o.status not in ("DELIVERED", "REFUNDED", "CANCELLED"))
        return {"name": self.alias, "country": self.country, "active": active}


class SellerAgent(Agent):
    """国内卖家：订单付款后转发工厂；处理退款。"""

    name = "seller"
    cn = "卖家"

    def __init__(self):
        super().__init__()
        self.forward_queue: deque = deque()
        self.refund_queue: deque = deque()

    def tick(self, e: Engine):
        for o in e.orders.values():
            if o.status == "PAID" and o.id not in self.forward_queue:
                self.forward_queue.append(o.id)
            if o.status == "REFUND_REQUESTED" and o.id not in self.refund_queue:
                self.refund_queue.append(o.id)
        # 每小时处理一笔转发（无货源：纯线上操作，快）
        if self.forward_queue:
            oid = self.forward_queue.popleft()
            o = e.orders[oid]
            self.busy_with = oid
            e.advance(o, "FORWARDED", "卖家",
                      f"卖家将订单转发给代工厂（{o.sku_name} x{o.qty} → {o.country}）")
            self.done_count += 1
        else:
            self.busy_with = None
        # 退款审批（若订单已签收则驳回）
        if self.refund_queue and random.random() < 0.5:
            oid = self.refund_queue.popleft()
            o = e.orders[oid]
            if o.status == "DELIVERED":
                e.log("卖家", f"[{oid}] 包裹已签收，驳回退款申请")
            else:
                e.advance(o, "REFUNDED", "卖家", f"卖家同意退款 ${o.amount}，订单关闭", "error")
                e.metrics["refunded"] += 1

    def status_dict(self, e: Engine) -> dict:
        d = super().status_dict(e)
        d["queue"] = len(self.forward_queue)
        return d


class FactoryAgent(Agent):
    """代工厂：接单→（缺货则生产）→质检→打包→交付物流。并发产能 3。"""

    name = "factory"
    cn = "代工厂"

    CAPACITY = 3
    RESTOCK_HOURS = 30
    QC_FAIL_RATE = 0.03
    CANCEL_RATE = 0.02

    def __init__(self):
        super().__init__()
        self.jobs: dict[str, int] = {}   # order_id -> 剩余小时

    def tick(self, e: Engine):
        # 接新单
        for o in e.orders.values():
            if o.status == "FORWARDED" and o.id not in self.jobs:
                if len(self.jobs) >= self.CAPACITY:
                    continue
                if e.sku_stock[o.sku] >= o.qty:
                    e.sku_stock[o.sku] -= o.qty
                    self.jobs[o.id] = random.randint(2, 4)   # 质检+打包
                    e.advance(o, "ACCEPTED", "工厂", f"工厂接单，开始质检打包（剩余库存 {e.sku_stock[o.sku]}）")
                else:
                    if random.random() < self.CANCEL_RATE:
                        e.advance(o, "CANCELLED", "工厂", f"{o.sku_name} 缺货且排产已满，订单取消，自动退款 ${o.amount}", "error")
                        e.metrics["cancelled"] += 1
                    else:
                        self.jobs[o.id] = self.RESTOCK_HOURS + random.randint(2, 4)
                        e.advance(o, "PRODUCING", "工厂", f"{o.sku_name} 缺货，紧急排产补货中（约 {self.RESTOCK_HOURS}h）", "warn")
        # 推进工单（已关闭的订单直接丢弃）
        for oid in list(self.jobs):
            if e.orders[oid].status in ("REFUNDED", "CANCELLED"):
                del self.jobs[oid]
                continue
            self.jobs[oid] -= 1
            o = e.orders[oid]
            if o.status == "ACCEPTED" and random.random() < self.QC_FAIL_RATE:
                self.jobs[oid] += 12
                o.note = "质检返工"
                e.log("工厂", f"[{oid}] 质检不合格，返工 +12h", "warn")
                continue
            if self.jobs[oid] <= 0:
                del self.jobs[oid]
                was_producing = o.status == "PRODUCING"
                e.advance(o, "PACKED", "工厂",
                          ("补货完成，" if was_producing else "") + "质检通过，打包贴单完成，交付物流")
                self.done_count += 1
        self.busy_with = next(iter(self.jobs), None)

    def status_dict(self, e: Engine) -> dict:
        d = super().status_dict(e)
        d["queue"] = len(self.jobs)
        d["capacity"] = self.CAPACITY
        return d


class LogisticsAgent(Agent):
    """物流：揽收→干线→清关→末端→签收，空运快海运慢，清关可能延误。"""

    name = "logistics"
    cn = "物流"

    CUSTOMS_DELAY_RATE = 0.12

    STAGES = {  # status -> (下一状态, 时长函数)
        "SHIPPED": ("LINEHAUL", lambda m: 4),
        "LINEHAUL": ("CUSTOMS", lambda m: random.randint(12, 24) if m == "air" else random.randint(96, 160)),
        "CUSTOMS": ("LAST_MILE", lambda m: random.randint(6, 20)),
        "LAST_MILE": ("DELIVERED", lambda m: random.randint(10, 30)),
    }

    def __init__(self):
        super().__init__()
        self.jobs: dict[str, list] = {}   # order_id -> [剩余小时, 当前物流环节]

    def tick(self, e: Engine):
        for o in e.orders.values():
            if o.status == "PACKED" and o.id not in self.jobs:
                self.jobs[o.id] = [2, "SHIPPED"]
                e.advance(o, "SHIPPED", "物流",
                          f"包裹已揽收，运单号 YT{random.randint(10**9, 10**10 - 1)}（{'空运' if o.method == 'air' else '海运'}）")
        for oid in list(self.jobs):
            if e.orders[oid].status in ("REFUNDED", "CANCELLED"):
                del self.jobs[oid]
                continue
            job = self.jobs[oid]
            job[0] -= 1
            if job[0] > 0:
                continue
            o = e.orders[oid]
            nxt, dur_fn = self.STAGES[job[1]]
            if nxt == "DELIVERED":
                del self.jobs[oid]
                hours = e.clock - o.created_at
                e.advance(o, "DELIVERED", "物流",
                          f"客户 {o.buyer} 签收！全程 {hours}h" + ("，准时送达" if e.clock <= o.eta else "，超出预期时效"))
                e.metrics["delivered"] += 1
                e.metrics["revenue"] += o.amount
                e.metrics["total_hours"] += hours
                if e.clock <= o.eta:
                    e.metrics["on_time"] += 1
                self.done_count += 1
            else:
                dur = dur_fn(o.method)
                if nxt == "LAST_MILE" and random.random() < self.CUSTOMS_DELAY_RATE:
                    dur += 48
                    e.log("物流", f"[{oid}] 清关查验延误 +48h", "warn")
                self.jobs[oid] = [dur, nxt]
                e.advance(o, nxt, "物流", f"进入{STATUS_CN[nxt]}环节（预计 {dur}h）")
        self.busy_with = next(iter(self.jobs), None)

    def status_dict(self, e: Engine) -> dict:
        d = super().status_dict(e)
        d["queue"] = len(self.jobs)
        return d
