from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )

    # Polymarket
    polymarket_api_key: str = Field(default="")
    polymarket_secret: str = Field(default="")
    polymarket_passphrase: str = Field(default="")
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"

    # OpenRouter
    openrouter_api_key: str = Field(default="")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Strategy
    whale_threshold_usd: float = 500.0
    whale_threshold_large: float = 2000.0
    market_queue_trigger: int = 25
    swarm_consensus_required: int = 4
    arb_threshold: float = 0.98
    kelly_fraction: float = 0.25
    max_drawdown_pct: float = 0.30
    excluded_categories: list[str] = ["crypto", "sports"]

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Logging
    log_dir: str = "logs"
    csv_path: str = "data/signals.csv"

    # Mode — ALWAYS true until manually overridden after 2 weeks paper validation
    paper_trading: bool = True


settings = Settings()
