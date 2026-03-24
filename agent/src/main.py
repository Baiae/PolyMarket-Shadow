import asyncio
import logging
import sys

import uvicorn

from config import settings
from data_collector import DataCollector
from strategy.arbitrage import ArbitrageDetector
from strategy.swarm import AgentSwarm
from risk import RiskManager
from execution import ExecutionEngine
from feedback_logger import FeedbackLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"{settings.log_dir}/agent.log"),
    ],
)
log = logging.getLogger("main")


class AgentOrchestrator:
    def __init__(self):
        self.running = False
        self.market_queue: list[str] = []
        self.risk = RiskManager(initial_bankroll=1000.0)
        self.collector = DataCollector(on_queue_full=self._on_queue_full)
        self.arbitrage = ArbitrageDetector()
        self.swarm = AgentSwarm()
        self.execution = ExecutionEngine(self.risk)
        self.logger = FeedbackLogger()

    async def run(self) -> None:
        self.running = True
        log.info("=" * 55)
        log.info("  POLY-SHADOW AGENT STARTING")
        log.info(f"  Mode:     {'📋 PAPER TRADING' if settings.paper_trading else '🔴 LIVE'}")
        log.info(f"  Whale ≥:  ${settings.whale_threshold_usd:,.0f}")
        log.info(f"  Trigger:  {settings.market_queue_trigger} markets queued")
        log.info(f"  Consensus:{settings.swarm_consensus_required}/6 models")
        log.info(f"  Kill at:  {settings.max_drawdown_pct:.0%} drawdown")
        log.info("=" * 55)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.collector.start())
            tg.create_task(self._arb_scan_loop())

    def stop(self) -> None:
        self.running = False
        self.collector.stop()
        log.info("Agent stopped.")

    def _on_queue_full(self, market_ids: list[str]) -> None:
        self.market_queue = market_ids
        asyncio.create_task(self._run_swarm(market_ids))

    async def _run_swarm(self, market_ids: list[str]) -> None:
        log.info(f"🤖 Swarm firing on {len(market_ids)} markets")
        signals = await self.swarm.analyse_batch(
            market_ids, meta_lookup=self.collector.get_meta)
        for signal in signals:
            if self.risk.is_killed:
                break
            order = await self.execution.execute_signal(signal)
            self.logger.log_swarm_signal(signal, order)

    async def _arb_scan_loop(self) -> None:
        while self.running:
            if not self.risk.is_killed:
                arb_signals = self.arbitrage.scan(self.collector.all_meta())
                for signal in arb_signals:
                    meta = self.collector.get_meta(signal.market_id)
                    if meta:
                        orders = await self.execution.execute_arb(signal, meta)
                        self.logger.log_arb_signal(signal, orders)
            await asyncio.sleep(5)


# ── Global orchestrator + FastAPI app (used by uvicorn) ──────────────────────
orchestrator = AgentOrchestrator()

from api.server import create_app
api_app = create_app(orchestrator)


@api_app.on_event("startup")
async def start_agent():
    asyncio.create_task(orchestrator.run())


@api_app.on_event("shutdown")
async def stop_agent():
    orchestrator.stop()


if __name__ == "__main__":
    uvicorn.run(
        "main:api_app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )
