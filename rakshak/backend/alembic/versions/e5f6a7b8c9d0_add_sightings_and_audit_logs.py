"""add_sightings_and_audit_logs

Enables the PostGIS extension and creates the sightings and audit_logs
tables with their foreign keys and indexes.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lookup and composite indexes required by the analytics queries.
SIGHTINGS_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_sightings_hotlist_id ON sightings (hotlist_id)",
    "CREATE INDEX IF NOT EXISTS ix_sightings_device_id ON sightings (device_id)",
    "CREATE INDEX IF NOT EXISTS ix_sightings_hotlist_id_captured_at "
    "ON sightings (hotlist_id, captured_at)",
    "CREATE INDEX IF NOT EXISTS ix_sightings_device_id_captured_at "
    "ON sightings (device_id, captured_at)",
)


def _enable_postgis() -> None:
    """Enable the PostGIS extension required for spatial queries."""
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))


def _create_sightings_table() -> None:
    """Create the sightings table with its lookup indexes."""
    op.execute(
        sa.text(
            """CREATE TABLE IF NOT EXISTS sightings (
                id UUID PRIMARY KEY,
                hotlist_id UUID NOT NULL REFERENCES hotlist(id),
                device_id UUID NOT NULL REFERENCES devices(id),
                lat DOUBLE PRECISION NOT NULL,
                lng DOUBLE PRECISION NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL,
                photo_url VARCHAR(1024) NOT NULL,
                confidence INTEGER NOT NULL DEFAULT 0,
                cluster_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
    )
    for statement in SIGHTINGS_INDEX_STATEMENTS:
        op.execute(sa.text(statement))


def _create_audit_logs_table() -> None:
    """Create the audit_logs table with its actor index."""
    op.execute(
        sa.text(
            """CREATE TABLE IF NOT EXISTS audit_logs (
                id UUID PRIMARY KEY,
                actor_id UUID NOT NULL REFERENCES users(id),
                action VARCHAR(100) NOT NULL,
                target_type VARCHAR(50) NOT NULL,
                target_id UUID NOT NULL,
                metadata_json JSON,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_id "
            "ON audit_logs (actor_id)"
        )
    )


def upgrade() -> None:
    """Enable PostGIS and create the sightings and audit_logs tables."""
    _enable_postgis()
    _create_sightings_table()
    _create_audit_logs_table()


def downgrade() -> None:
    """Drop the audit_logs and sightings tables."""
    op.execute(sa.text("DROP TABLE IF EXISTS audit_logs"))
    op.execute(sa.text("DROP TABLE IF EXISTS sightings"))
