from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration settings loaded from environment variables or .env file.
    """
    APP_NAME: str = "AI Paper Generator"
    APP_ENV: str = "development"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@db:5432/ai_paper_generator"

    JWT_SECRET_KEY: str = "change-me-secret-key-for-jwt-authentication"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    GOOGLE_WEB_CLIENT_ID: str = ""
    GOOGLE_ANDROID_CLIENT_ID: str = ""
    GOOGLE_IOS_CLIENT_ID: str = ""

    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"

    LOCAL_STORAGE_PATH: str = "/app/storage"
    MAX_UPLOAD_SIZE_MB: int = 50

    OCR_ENABLED: bool = True
    OCR_LANGUAGE: str = "eng"

    DOCUMENT_PROCESSING_STALE_MINUTES: int = 15

    GEMINI_API_KEY: str = ""
    GEMINI_GENERATION_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"
    EMBEDDING_DIMENSION: int = 768

    RAG_RATE_LIMIT_REQUESTS: int = 10
    RAG_RATE_LIMIT_WINDOW_SECONDS: int = 60

    RAG_RELEVANCE_THRESHOLD: float = 0.45

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
