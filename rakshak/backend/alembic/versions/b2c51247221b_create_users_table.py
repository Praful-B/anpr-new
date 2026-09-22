"""create_users_table

Revision ID: b2c51247221b
Revises:
Create Date: 2026-09-21 14:37:34.215638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c51247221b"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_user_role_enum(bind) -> None:
    """Create user_role enum type if it does not exist."""
    row = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": "user_role"},
    ).first()
    if row is None:
        bind.execute(
            sa.text(
                "CREATE TYPE user_role AS ENUM (:c1, :c2, :c3, :c4)"
            ),
            {"c1": "CITIZEN", "c2": "VOLUNTEER", "c3": "COP", "c4": "ADMIN"},
        )


def upgrade() -> None:
    """Create the users table with UUID PK and role ENUM."""
    conn = op.get_bind()
    _create_user_role_enum(conn)
    op.execute(
        sa.text(
            """CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(20),
                password_hash VARCHAR(255) NOT NULL,
                role user_role NOT NULL DEFAULT 'CITIZEN',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"
        )
    )


def downgrade() -> None:
    """Drop the users table and the user_role ENUM type."""
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_email"))
    op.execute(sa.text("DROP TABLE IF EXISTS users"))
    op.execute(sa.text("DROP TYPE IF EXISTS user_role"))
