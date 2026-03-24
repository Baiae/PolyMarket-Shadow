# PolyMarket-Shadow

Automated Polymarket trading agent + Flutter monitoring dashboard.

## Structure

```
PolyMarket-Shadow/
├── agent/      # Python backend — FastAPI + WebSocket + AI swarm
└── flutter/    # Flutter dashboard — BLoC, Material 3, iOS/iPad Pro
```

## Quickstart

### Agent (GitHub Codespaces)
```bash
cd agent
cp .env.example .env   # fill in your keys
python src/main.py
```

### Flutter Dashboard
```bash
cd flutter
flutter pub get
flutter run --dart-define=API_BASE_URL=https://your-codespaces-url/api
```

## Docs
- `agent/README.md` — full agent setup, API endpoints, risk rules
- `flutter/README.md` — dashboard setup and architecture
