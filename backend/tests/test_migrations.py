from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.database import engine


def test_alembic_has_a_single_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["0003_service_availability"]


def test_alembic_upgrade_records_service_availability_revision() -> None:
    command.upgrade(Config("alembic.ini"), "head")

    with engine.connect() as connection:
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()

        assert revisions == ["0003_service_availability"]
