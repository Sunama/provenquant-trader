import json
from pydantic import field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, List, Union


class Settings(BaseSettings):
    PROJECT_NAME: str = "ProvenQuant Trader"
    API_STR: str = "/api"

    SERVER_SECRET: str

    # Database
    POSTGRES_PASSWORD: str
    TRADER_POSTGRES_USER: str
    TRADER_POSTGRES_PASSWORD: str
    TRADER_POSTGRES_DB: str
    DATABASE_URL: str | None = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Any, info: ValidationInfo) -> Any:
        if isinstance(v, str):
            return v
        return (
            f"postgresql+psycopg://{info.data.get('TRADER_POSTGRES_USER')}"
            f":{info.data.get('TRADER_POSTGRES_PASSWORD')}"
            f"@postgres:5432/{info.data.get('TRADER_POSTGRES_DB')}"
        )

    # Redis
    REDIS_USERNAME: str
    REDIS_PASSWORD: str
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_URL: str | None = None

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def assemble_redis_connection(cls, v: Any, info: ValidationInfo) -> Any:
        if isinstance(v, str):
            return v
        return (
            f"redis://{info.data.get('REDIS_USERNAME')}"
            f":{info.data.get('REDIS_PASSWORD')}"
            f"@{info.data.get('REDIS_HOST')}:{info.data.get('REDIS_PORT')}/0"
        )

    # RabbitMQ
    RABBITMQ_USER: str
    RABBITMQ_PASSWORD: str
    RABBITMQ_HOST: str = "rabbitmq"
    RABBITMQ_PORT: int = 5672
    CELERY_BROKER_URL: str | None = None

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def assemble_amqp_connection(cls, v: Any, info: ValidationInfo) -> Any:
        if isinstance(v, str):
            return v
        return (
            f"amqp://{info.data.get('RABBITMQ_USER')}"
            f":{info.data.get('RABBITMQ_PASSWORD')}"
            f"@{info.data.get('RABBITMQ_HOST')}:{info.data.get('RABBITMQ_PORT')}//"
        )

    # ProvenQuant integration (optional)
    PROVENQUANT_API_URL: str = ""
    PROVENQUANT_API_KEY: str = ""

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [i.strip() for i in v.split(",") if i.strip()]
        return []

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
