"""
AIOS Configuration Management
Loads and validates configuration from YAML files and environment variables.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Pydantic settings models
# ---------------------------------------------------------------------------

class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    rate_limit_per_minute: int = 60
    task_timeout_seconds: int = 600
    cors_origins: list[str] = ["*"]


class SchedulerConfig(BaseModel):
    alpha: float = 0.3
    beta: float = 0.5
    gamma: float = 0.2
    max_retries: int = 3
    tick_interval_ms: int = 100
    agent_pool_size: int = 8
    max_concurrent_tasks: int = 16

    @field_validator("alpha", "beta", "gamma")
    @classmethod
    def validate_weights(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Scheduling weights must be in [0, 1]")
        return v


class MemoryConfig(BaseModel):
    stm_ttl_seconds: int = 3600
    ltm_staleness_threshold: int = 86400
    eviction_penalty: float = 0.1
    retrieval_top_k: int = 5
    embedding_dim: int = 1536
    consolidation_interval_seconds: int = 300
    promotion_threshold: int = 3
    stm_max_entries: int = 10000
    ltm_collection_name: str = "aios_ltm"


class LLMConfig(BaseModel):
    default_model: str = "gpt-4o-2024-05-13"
    planner_model: str = "gpt-4o-2024-05-13"
    judge_model: str = "gpt-4o-2024-05-13"
    fallback_model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_tokens: int = 4096
    max_plan_retries: int = 3
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = 32
    request_timeout: int = 60


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 50

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class ChromaConfig(BaseModel):
    host: str = "localhost"
    port: int = 8001
    collection: str = "aios_ltm"


class MonitoringConfig(BaseModel):
    websocket_port: int = 8001
    otel_endpoint: str = "http://localhost:4317"
    metrics_interval_seconds: int = 10
    enable_tracing: bool = True
    enable_metrics: bool = True


class AIOSConfig(BaseModel):
    """Root configuration object for AIOS."""
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    chromadb: ChromaConfig = Field(default_factory=ChromaConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)

    # Runtime overrides from environment variables
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    redis_password: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        """Apply environment variable overrides after model init."""
        # Pull sensitive values from environment
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", self.openai_api_key)
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", self.anthropic_api_key)
        redis_pw = os.environ.get("REDIS_PASSWORD")
        if redis_pw:
            self.redis.password = redis_pw
        # Environment override
        env = os.environ.get("AIOS_ENV")
        if env:
            self.environment = env
        log_level = os.environ.get("LOG_LEVEL")
        if log_level:
            self.log_level = log_level


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dicts; override takes precedence."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_config(path: Path) -> dict:
    """Load a YAML configuration file."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def get_config(config_path: Optional[str] = None) -> AIOSConfig:
    """
    Load and cache the AIOS configuration.

    Priority (lowest to highest):
    1. Built-in Pydantic defaults
    2. configs/aios_config.yaml
    3. Environment-specific override file (e.g., configs/aios_config.production.yaml)
    4. Environment variables

    Args:
        config_path: Optional explicit path to config file.

    Returns:
        Validated AIOSConfig instance.
    """
    repo_root = Path(__file__).resolve().parents[2]
    base_config_path = Path(config_path) if config_path else repo_root / "configs" / "aios_config.yaml"

    raw = load_yaml_config(base_config_path)

    # Load environment-specific override
    env = os.environ.get("AIOS_ENV", raw.get("aios", {}).get("environment", "development"))
    env_config_path = base_config_path.parent / f"aios_config.{env}.yaml"
    if env_config_path.exists():
        env_raw = load_yaml_config(env_config_path)
        raw = _deep_merge(raw, env_raw)

    # Flatten nested 'aios' top-level key if present
    aios_section = raw.pop("aios", {})
    flat = {**aios_section, **raw}

    return AIOSConfig(**flat)


def reload_config() -> AIOSConfig:
    """Force reload of configuration (clears cache)."""
    get_config.cache_clear()
    return get_config()
