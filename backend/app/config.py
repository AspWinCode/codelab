from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://codelab:codelab@localhost:5433/codelab"
    secret_key: str = "dev-only-not-secure-change-me-please-32chars"
    sso_kodex_shared_secret: str = ""
    lms_base_url: str = "https://tirskix.space"
    frontend_base_url: str = "http://localhost:5174"
    cors_origins: str = "http://localhost:5174"

    # JDG-002/003, SEC-004: "docker" — единственный режим, годный для чужого кода.
    # "subprocess" — только для разработки на машине без Docker, без изоляции.
    runner_backend: str = "docker"
    runner_docker_image: str = "codelab-runner:python3.12"
    runner_cpus: float = 1.0
    runner_pids_limit: int = 64

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
