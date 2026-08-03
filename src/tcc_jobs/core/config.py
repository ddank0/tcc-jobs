from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração lida de variáveis de ambiente ou do .env.

    No compose, as variáveis vêm do serviço; o .env só é usado fora do
    container.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str
    data_dir: Path = Path("data")


settings = Settings()  # type: ignore[call-arg]
