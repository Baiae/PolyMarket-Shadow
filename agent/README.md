# Poly-Shadow — Polymarket Trading Agent

> **MVP: Paper Trading Only.**
> Do not deploy real capital until >= 2 weeks of validated paper results.

## Architecture

```
[ DATA ]   Polymarket WebSocket + Gamma API
    ↓
[ ANALYSIS ]
    ├── Engine A: Structural Arbitrage (YES + NO < $0.98)
    └── Engine B: AI Swarm (6 LLMs via OpenRouter, 4/6 consensus)
    ↓
[ RISK ]   Quarter-Kelly sizing + 30% drawdown kill switch
    ↓
[ EXECUTION ]  Paper trades → CSV log
    ↓
[ API ]    FastAPI REST → Flutter Dashboard
```

## Quickstart (GitHub Codespaces)

1. Open repo in Codespaces — packages install automatically via `.devcontainer/`
2. Copy `.env.example` → `.env` and fill in your keys
3. Start the agent:
   ```bash
   cd src && python main.py
   ```
4. API: `http://localhost:8000`
5. Swagger docs: `http://localhost:8000/docs`

## API Endpoints (Flutter Dashboard)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/healthz` | Agent health + mode |
| GET | `/api/status` | Full status + risk stats |
| GET | `/api/trades` | Recent whale trades |
| GET | `/api/signals` | Swarm + arb signals |
| GET | `/api/positions` | Paper trade history |
| POST | `/api/kill` | Activate kill switch |
| POST | `/api/resume` | Resume after kill |

## Module Map

| File | Spec Module |
|------|-------------|
| `src/config.py` | Settings |
| `src/data_collector.py` | Module 1 — WebSocket + Gamma + whale filter |
| `src/strategy/arbitrage.py` | Module 2A — Structural arb |
| `src/strategy/swarm.py` | Module 2B — 6-model AI swarm |
| `src/risk.py` | Risk framework |
| `src/execution.py` | Module 3 — Paper trading engine |
| `src/feedback_logger.py` | Module 4 — CSV logger |
| `src/api/` | FastAPI bridge |
| `src/main.py` | Async orchestrator |

## QuantVPS Migration (when ready)

```bash
ssh ubuntu@your-quantvps-ip
bash deploy-quantvps.sh
```

That's it. See `deploy-quantvps.sh` and `poly-shadow.service` for details.
