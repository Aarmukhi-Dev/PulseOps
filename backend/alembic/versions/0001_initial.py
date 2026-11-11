"""Initial empty schema.

Domain tables arrive in later phases. This revision proves Alembic can
run against PostgreSQL before those tables exist.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-03

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
