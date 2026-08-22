from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Polymarket public data
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    market_discovery_limit: int = 50
    market_max_book_age_ms: int = 60_000

    # v0.2 paper core
    initial_bankroll: float = 1000.0
    database_path: str = "data/poly_shadow.db"
    arb_min_net_profit: float = 0.01
    arb_max_shares: float = 50.0
    arb_slippage_reserve_per_share: float = 0.0
    max_drawdown_pct: float = 0.30
    max_position_pct: float = 0.05

    # API server: local control plane by default
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_allowed_origins: list[str] = []
    control_token: str = Field(default="")

    # Logging
    log_dir: str = "logs"

    # v0.2 invariant: retained for compatibility but false is rejected at runtime.
    paper_trading: bool = True

    # Reserved for P1 forecasting; unused by the v0.2 paper core.
    openrouter_api_key: str = Field(default="")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"


settings = Settings()
