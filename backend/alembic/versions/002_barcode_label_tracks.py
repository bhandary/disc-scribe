"""add barcode, label, and tracks to cds

Revision ID: 002
Revises: 001
Create Date: 2026-10-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cds", sa.Column("barcode", sa.String(32), nullable=True))
    op.add_column("cds", sa.Column("label", sa.String(255), nullable=True))
    op.add_column("cds", sa.Column("tracks", postgresql.JSONB(), nullable=True))
    op.create_index("idx_barcode", "cds", ["barcode"])
    op.execute("CREATE UNIQUE INDEX uq_cds_barcode ON cds (barcode) WHERE barcode IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cds_barcode")
    op.drop_index("idx_barcode", table_name="cds")
    op.drop_column("cds", "tracks")
    op.drop_column("cds", "label")
    op.drop_column("cds", "barcode")
