"""Provider interface and OpenAI-compatible implementation."""

from __future__ import annotations

import json
from typing import Protocol

from openai import AsyncOpenAI

from .forecast import (
    ForecastRequest,
    ProbabilisticForecast,
    make_forecast_id,
    probability,
)

SYSTEM_PROMPT = """You are a probabilistic forecaster.
Return JSON only with these keys:
probability_yes: number in [0,1]
uncertainty: number in [0,1]
abstain: boolean
rationale: short string
Use only the evidence supplied in the request. Do not infer confidence from model agreement.
If evidence is insufficient, set abstain=true and keep uncertainty high."""


class ForecastProvider(Protocol):
    provider_name: str
    model_name: str

    async def forecast(self, request: ForecastRequest) -> ProbabilisticForecast:
        """Produce one explicit probability forecast."""


class OpenAICompatibleForecastProvider:
    """Provider-neutral adapter for OpenAI-compatible local or remote endpoints."""

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        api_key: str,
        base_url: str,
        client: AsyncOpenAI | None = None,
        include_market_baseline: bool = False,
    ):
        if not provider_name.strip() or not model_name.strip():
            raise ValueError("provider_name and model_name are required")
        self.provider_name = provider_name
        self.model_name = model_name
        self.include_market_baseline = include_market_baseline
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _prompt(request: ForecastRequest, *, include_market_baseline: bool) -> str:
        evidence_lines = [
            (
                f"- id={item.evidence_id} source={item.source} "
                f"retrieved={item.retrieved_at.isoformat()} "
                f"published={item.published_at.isoformat() if item.published_at else 'unknown'} "
                f"sha256={item.content_sha256} title={item.title!r}\n"
                f"  content={item.content}"
            )
            for item in request.evidence
        ]
        lines = [
            f"Question: {request.question}",
            f"Condition ID: {request.condition_id}",
            (
                f"Resolution time: {request.resolves_at.isoformat()}"
                if request.resolves_at
                else "Resolution time: unknown"
            ),
            "Evidence:",
            *(evidence_lines or ["- none"]),
        ]
        if include_market_baseline and request.baseline is not None:
            lines.append(
                "Market baseline at issuance: "
                f"{request.baseline.probability_yes} "
                f"(source={request.baseline.source})"
            )
        return "\n".join(lines)

    async def forecast(self, request: ForecastRequest) -> ProbabilisticForecast:
        response = await self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._prompt(
                        request,
                        include_market_baseline=self.include_market_baseline,
                    ),
                },
            ],
            temperature=0,
            max_tokens=220,
        )
        raw = response.choices[0].message.content or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("forecast provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("forecast provider JSON must be an object")
        probability_yes = probability(payload.get("probability_yes"))
        uncertainty = probability(payload.get("uncertainty"))
        abstain = payload.get("abstain")
        if not isinstance(abstain, bool):
            raise ValueError("forecast provider abstain must be boolean")
        rationale = str(payload.get("rationale") or "").strip()
        return ProbabilisticForecast(
            forecast_id=make_forecast_id(
                request.request_id,
                self.provider_name,
                self.model_name,
            ),
            request_id=request.request_id,
            condition_id=request.condition_id,
            provider=self.provider_name,
            model=self.model_name,
            probability_yes=probability_yes,
            uncertainty=uncertainty,
            abstain=abstain,
            issued_at=request.issued_at,
            evidence_ids=tuple(item.evidence_id for item in request.evidence),
            baseline_probability=(
                request.baseline.probability_yes if request.baseline else None
            ),
            rationale=rationale,
        )
