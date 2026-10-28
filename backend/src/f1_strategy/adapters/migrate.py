import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import NullPool, create_engine, make_url

from f1_strategy.adapters.settings import PostgresSettings

MIGRATIONS = "f1_strategy.adapters:migrations"
DRIVER = "postgresql+psycopg"


def upgrade(postgres_uri: str, connect_timeout_s: int) -> None:
    """Bring the schema to the latest migration, all of them in one transaction."""
    engine = create_engine(
        make_url(postgres_uri).set(drivername=DRIVER),
        poolclass=NullPool,
        connect_args={"connect_timeout": connect_timeout_s},
    )
    try:
        with engine.begin() as connection:
            config = Config()
            config.set_main_option("script_location", MIGRATIONS)
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def main() -> int:
    settings = PostgresSettings()
    upgrade(settings.postgres_uri.get_secret_value(), settings.postgres_connect_timeout_s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
