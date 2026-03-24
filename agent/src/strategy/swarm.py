import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from openai import AsyncOpenAI
from config import settings

log = logging.getLogger(__name__)


class Verdict(str, Enum):
    YES = "YES"
    NO = "NO"
    NO_TRADE = "NO_TRADE"


SWARM_MODELS = [
    "deepseek/deepseek-chat",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-haiku",
    "qwen/qwen-2.5-72b-instruct",
    "x-ai/grok-beta",
    "meta-llama/llama-3.1-70b-instruct",
]

SYSTEM_PROMPT = """You are a prediction market analyst. Respond with ONLY one word:
YES, NO, or NO_TRADE.
- YES: event resolves YES with >60% confidence
- NO: event resolves NO with >60% confidence
- NO_TRADE: insufficient information or too close to call"""


@dataclass
class ModelPrediction:
    model: str
    verdict: Verdict
    latency_ms: float


@dataclass
class SwarmSignal:
    market_id: str
    question: str
    predictions: list[ModelPrediction]
    yes_count: int
    no_count: int
    no_trade_count: int
    consensus: Verdict
    confidence: float
    yes_price: float = 0.5
    no_price: float = 0.5
    timestamp: datetime = field(default_factory=datetime.utcnow)


class AgentSwarm:
    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        self.signals: list[SwarmSignal] = []

    async def analyse_batch(self, market_ids: list[str], meta_lookup) -> list[SwarmSignal]:
        actionable = []
        tasks, metas = [], []
        for mid in market_ids:
            meta = meta_lookup(mid)
            if meta is None:
                continue
            metas.append(meta)
            tasks.append(self._query_swarm(meta))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for meta, result in zip(metas, results):
            if isinstance(result, Exception):
                log.error(f"Swarm error for {meta.market_id}: {result}")
                continue
            if result is not None:
                actionable.append(result)
        self.signals.extend(actionable)
        if len(self.signals) > 1000:
            self.signals = self.signals[-1000:]
        return actionable

    async def _query_swarm(self, meta) -> SwarmSignal | None:
        prompt = (
            f"Market: {meta.question}\n"
            f"YES price: {meta.yes_price:.3f} | NO price: {meta.no_price:.3f}\n"
            f"Category: {meta.category} | Resolves: {meta.end_date}"
        )
        raw_results = await asyncio.gather(
            *[self._query_model(m, prompt) for m in SWARM_MODELS],
            return_exceptions=True,
        )
        predictions = []
        for model, result in zip(SWARM_MODELS, raw_results):
            if isinstance(result, Exception):
                predictions.append(ModelPrediction(model=model,
                    verdict=Verdict.NO_TRADE, latency_ms=0))
            else:
                predictions.append(result)
        yes_count = sum(1 for p in predictions if p.verdict == Verdict.YES)
        no_count  = sum(1 for p in predictions if p.verdict == Verdict.NO)
        nt_count  = sum(1 for p in predictions if p.verdict == Verdict.NO_TRADE)
        total = len(predictions)
        if yes_count >= settings.swarm_consensus_required:
            consensus, confidence = Verdict.YES, yes_count / total
        elif no_count >= settings.swarm_consensus_required:
            consensus, confidence = Verdict.NO, no_count / total
        else:
            log.info(f"No consensus: {meta.question[:50]} (Y={yes_count} N={no_count})")
            return None
        signal = SwarmSignal(
            market_id=meta.market_id, question=meta.question,
            predictions=predictions, yes_count=yes_count,
            no_count=no_count, no_trade_count=nt_count,
            consensus=consensus, confidence=confidence,
            yes_price=meta.yes_price, no_price=meta.no_price,
        )
        log.info(f"✅ Consensus: {consensus.value} ({yes_count}/{total}) | {meta.question[:50]}")
        return signal

    async def _query_model(self, model: str, prompt: str) -> ModelPrediction:
        start = time.perf_counter()
        response = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": prompt}],
            max_tokens=5, temperature=0.1,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        raw = response.choices[0].message.content.strip().upper()
        if "YES" in raw:
            verdict = Verdict.YES
        elif "NO_TRADE" in raw or "NO TRADE" in raw:
            verdict = Verdict.NO_TRADE
        elif "NO" in raw:
            verdict = Verdict.NO
        else:
            verdict = Verdict.NO_TRADE
        return ModelPrediction(model=model, verdict=verdict, latency_ms=latency_ms)
