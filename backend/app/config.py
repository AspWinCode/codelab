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

    # EDT-002/008, SEC-005: allowlist форматов и лимиты размера для загрузок редактора.
    # Объектное хранилище (раздел 4 ТЗ) сюда не входит — файлы лежат на локальном диске,
    # см. README.
    uploads_dir: str = "uploads"
    upload_max_image_mb: int = 10
    upload_max_video_mb: int = 200
    upload_allowed_image_ext: str = "jpg,jpeg,png,gif,webp"
    upload_allowed_video_ext: str = "mp4,webm"

    @property
    def upload_allowed_extensions(self) -> dict[str, int]:
        """Расширение (без точки, lowercase) → лимит размера в байтах."""
        result = {}
        for ext in self.upload_allowed_image_ext.split(","):
            if ext.strip():
                result[ext.strip().lower()] = self.upload_max_image_mb * 1024 * 1024
        for ext in self.upload_allowed_video_ext.split(","):
            if ext.strip():
                result[ext.strip().lower()] = self.upload_max_video_mb * 1024 * 1024
        return result

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
