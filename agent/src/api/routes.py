from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from config import settings


class HealthStatus(BaseModel):
    status: str
    timestamp: str
    paper_trading: bool = True
    version: str = "0.2.0"
    feed_healthy: bool
    last_error: str


class AgentStatus(BaseModel):
    running: bool
    paper_trading: bool = True
    kill_switch_active: bool
    kill_reason: str
    feed_healthy: bool
    markets_tracked: int
    books_tracked: int
    open_positions: int
    risk_stats: dict


class TradeItem(BaseModel):
    condition_id: str
    token_id: str
    price: str
    size: str | None
    side: str
    fee_rate_bps: str | None
    timestamp_ms: int | None


class SignalItem(BaseModel):
    condition_id: str
    question: str
    matched_shares: str
    total_cost: str
    locked_payout: str
    net_profit: str
    roi: str
    timestamp_ms: int


class PositionItem(BaseModel):
    condition_id: str
    token_id: str
    side: str
    shares: str
    cost_basis: str
    average_cost: str


class KillResponse(BaseModel):
    success: bool
    message: str


def _authorize_control(request: Request, provided_token: str | None) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="control endpoint is local-only")
    if settings.control_token and provided_token != settings.control_token:
        raise HTTPException(status_code=403, detail="invalid control token")


def build_router(orchestrator) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthStatus, tags=["health"])
    async def health_check():
        return HealthStatus(
            status=(
                "healthy"
                if orchestrator.running and orchestrator.feed_healthy
                else "degraded"
            ),
            timestamp=datetime.now(timezone.utc).isoformat(),
            feed_healthy=orchestrator.feed_healthy,
            last_error=orchestrator.last_error,
        )

    @router.get("/status", response_model=AgentStatus, tags=["agent"])
    async def get_status():
        orchestrator._evaluate_risk_if_marked()
        return AgentStatus(
            running=orchestrator.running,
            kill_switch_active=orchestrator.risk.is_killed,
            kill_reason=orchestrator.risk.kill_reason,
            feed_healthy=orchestrator.feed_healthy,
            markets_tracked=len(orchestrator.markets_by_condition),
            books_tracked=len(orchestrator.books),
            open_positions=len(orchestrator.ledger.positions()),
            risk_stats=orchestrator.risk.stats,
        )

    @router.get("/trades", response_model=list[TradeItem], tags=["data"])
    async def get_trades(limit: int = 50):
        bounded_limit = max(0, min(limit, 500))
        return [
            TradeItem(
                condition_id=trade.condition_id,
                token_id=trade.token_id,
                price=str(trade.price),
                size=str(trade.size) if trade.size is not None else None,
                side=trade.side,
                fee_rate_bps=(
                    str(trade.fee_rate_bps)
                    if trade.fee_rate_bps is not None
                    else None
                ),
                timestamp_ms=trade.timestamp_ms,
            )
            for trade in reversed(orchestrator.recent_trades[-bounded_limit:])
        ]

    @router.get("/signals", response_model=list[SignalItem], tags=["signals"])
    async def get_signals(limit: int = 50):
        bounded_limit = max(0, min(limit, 500))
        return [
            SignalItem(
                condition_id=signal.condition_id,
                question=signal.question,
                matched_shares=str(signal.matched_shares),
                total_cost=str(signal.total_cost),
                locked_payout=str(signal.locked_payout),
                net_profit=str(signal.net_profit),
                roi=str(signal.roi),
                timestamp_ms=max(
                    signal.yes_book_timestamp_ms,
                    signal.no_book_timestamp_ms,
                ),
            )
            for signal in reversed(orchestrator.arbitrage.signals[-bounded_limit:])
        ]

    @router.get("/positions", response_model=list[PositionItem], tags=["execution"])
    async def get_positions():
        return [
            PositionItem(
                condition_id=position.condition_id,
                token_id=position.token_id,
                side=position.side,
                shares=str(position.shares),
                cost_basis=str(position.cost_basis),
                average_cost=str(position.average_cost),
            )
            for position in orchestrator.ledger.positions()
        ]

    @router.post("/kill", response_model=KillResponse, tags=["control"])
    async def trigger_kill_switch(
        request: Request,
        x_poly_shadow_control_token: str | None = Header(default=None),
    ):
        _authorize_control(request, x_poly_shadow_control_token)
        if orchestrator.risk.is_killed:
            return KillResponse(success=False, message="Kill switch already active")
        orchestrator.risk.kill("Manually triggered through local control API")
        return KillResponse(success=True, message="Paper order generation stopped")

    @router.post("/resume", response_model=KillResponse, tags=["control"])
    async def resume_trading(
        request: Request,
        x_poly_shadow_control_token: str | None = Header(default=None),
    ):
        _authorize_control(request, x_poly_shadow_control_token)
        if not orchestrator.risk.is_killed:
            return KillResponse(success=False, message="Kill switch not active")
        orchestrator.risk.resume()
        return KillResponse(success=True, message="Paper order generation resumed")

    return router
