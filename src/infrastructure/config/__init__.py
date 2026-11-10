"""Infrastructure Configuration & Environment Variables."""
import os


class AppConfig:
    ENV = os.getenv("VERCEL_ENV", os.getenv("ENV", "development"))
    IS_PROD = ENV == "production"
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    JWT_SECRET = os.getenv("JWT_SECRET", "")
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")


config = AppConfig()
