from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres
    database_url: str = Field(
        default="postgresql+asyncpg://bdhost:bdhost@localhost:5432/bdhost",
        alias="DATABASE_URL",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
    )

    # R2 / S3-compatible storage
    r2_endpoint_url: str = Field(
        default="http://localhost:9000",
        alias="R2_ENDPOINT_URL",
    )
    r2_access_key_id: str = Field(
        default="minioadmin",
        alias="R2_ACCESS_KEY_ID",
    )
    r2_secret_access_key: str = Field(
        default="minioadmin",
        alias="R2_SECRET_ACCESS_KEY",
    )
    r2_bucket: str = Field(
        default="bdappshub-apps",
        alias="R2_BUCKET",
    )
    r2_region: str = Field(
        default="auto",
        alias="R2_REGION",
    )

    # Auth
    jwt_secret: str = Field(
        default="development-secret-key-do-not-use-in-production-1234567890",
        alias="JWT_SECRET",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        alias="JWT_ALGORITHM",
    )
    access_token_expire_minutes: int = Field(
        default=15,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=30,
        alias="REFRESH_TOKEN_EXPIRE_DAYS",
    )

    # Application & Environment
    base_domain: str = Field(
        default="bdappshub.com",
        alias="BASE_DOMAIN",
    )
    environment: str = Field(
        default="development",
        alias="ENVIRONMENT",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000,https://app.bdappshub.com",
        alias="CORS_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
