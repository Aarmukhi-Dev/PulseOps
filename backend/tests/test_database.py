from sqlalchemy import text

from app.core.database import engine


def test_sqlalchemy_can_query_postgres() -> None:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()

    assert result == 1
