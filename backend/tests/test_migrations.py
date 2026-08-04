from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings


def test_fresh_sqlite_database_upgrades_to_single_head(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}"
    )
    with engine.connect() as connection:
        revisions = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all()
        assert revisions == ["f6a7b8c9d0e1"]

    user_columns = {
        column["name"]
        for column in inspect(engine).get_columns("users")
    }
    assert "hashed_password" not in user_columns
    assert {
        "first_name",
        "last_name",
        "created_at",
        "updated_at",
    } <= user_columns
    engine.dispose()
    get_settings.cache_clear()
