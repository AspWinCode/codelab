from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://codelab:codelab@localhost:5433/codelab"
    secret_key: str = "dev-only-not-secure-change-me-please-32chars"
    sso_kodex_shared_secret: str = ""
    lms_base_url: str = "https://tirskix.space"
    frontend_base_url: str = "http://localhost:5174"
    cors_origins: str = "http://localhost:5174"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
