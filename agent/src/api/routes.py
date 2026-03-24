from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    timestamp: str
    paper_trading: bool
    version: str = "0.1.0"


class AgentStatus(BaseModel):
    running: bool
    kill_switch_active: bool
    kill_reason: str
    paper_trading: bool
    risk_stats: dict
    queue_depth: int


class TradeItem(BaseModel):
    market_id: str
    question: str
    outcome: str
    amount_usd: float
    price: float
    timestamp: str
    category: str


class SignalItem(BaseModel):
    market_id: str
    question: str
    source: str
    consensus: str
    confidence: float
    yes_count: int
    no_count: int
    timestamp: str


class OrderItem(BaseModel):
    market_id: str
    question: str
    side: str
    size_usd: float
    price: float
    status: str
    source: str
    timestamp: str


class KillResponse(BaseModel):
    success: bool
    message: str


def build_router(orchestrator) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthStatus, tags=["health"])
    async def health_check():
        from config import settings
        return HealthStatus(
            status="healthy" if orchestrator.running else "idle",
            timestamp=datetime.utcnow().isoformat(),
            paper_trading=settings.paper_trading,
        )

    @router.get("/status", response_model=AgentStatus, tags=["agent"])
    async def get_status():
        return AgentStatus(
            running=orchestrator.running,
            kill_switch_active=orchestrator.risk.is_killed,
            kill_reason=orchestrator.risk.kill_reason,
            paper_trading=orchestrator.risk.stats.get("kill_switch_active", False),
            risk_stats=orchestrator.risk.stats,
            queue_depth=len(orchestrator.market_queue),
        )

    @router.get("/trades", response_model=list[TradeItem], tags=["data"])
    async def get_trades(limit: int = 50):
        trades = orchestrator.collector.recent_trades[-limit:]
        return [TradeItem(
            market_id=t.market_id,
            question=t.question or t.market_id[:20],
            outcome=t.outcome, amount_usd=t.amount_usd,
            price=t.price, timestamp=t.timestamp.isoformat(),
            category=t.category,
        ) for t in reversed(trades)]

    @router.get("/signals", response_model=list[SignalItem], tags=["signals"])
    async def get_signals(limit: int = 50):
        results = []
        for s in reversed(orchestrator.swarm.signals[-limit:]):
            results.append(SignalItem(
                market_id=s.market_id, question=s.question,
                source="SWARM", consensus=s.consensus.value,
                confidence=s.confidence, yes_count=s.yes_count,
                no_count=s.no_count, timestamp=s.timestamp.isoformat()))
        for s in reversed(orchestrator.arbitrage.signals[-limit:]):
            results.append(SignalItem(
                market_id=s.market_id, question=s.question,
                source="ARB", consensus="ARB", confidence=s.edge_usd,
                yes_count=0, no_count=0,
                timestamp=datetime.utcnow().isoformat()))
        return results[:limit]

    @router.get("/positions", response_model=list[OrderItem], tags=["execution"])
    async def get_positions(limit: int = 100):
        return [OrderItem(
            market_id=o.market_id, question=o.question,
            side=o.side, size_usd=o.size_usd, price=o.price,
            status=o.status.value, source=o.source,
            timestamp=o.timestamp.isoformat(),
        ) for o in reversed(orchestrator.execution.orders[-limit:])]

    @router.post("/kill", response_model=KillResponse, tags=["control"])
    async def trigger_kill_switch():
        if orchestrator.risk.is_killed:
            return KillResponse(success=False, message="Kill switch already active")
        orchestrator.risk._killed = True
        orchestrator.risk._kill_reason = "Manually triggered via Flutter dashboard"
        return KillResponse(success=True, message="Kill switch activated")

    @router.post("/resume", response_model=KillResponse, tags=["control"])
    async def resume_trading():
        if not orchestrator.risk.is_killed:
            return KillResponse(success=False, message="Kill switch not active")
        orchestrator.risk.resume()
        return KillResponse(success=True, message="Trading resumed")

    return router
