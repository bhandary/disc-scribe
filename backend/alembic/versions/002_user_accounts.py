"""user accounts and per-user CD ownership

Revision ID: 002
Revises: 001
Create Date: 2026-11-08 00:00:00.000000

Existing cds rows keep user_id NULL. They stay in the table and are hidden:
every CD query filters to the signed-in user, and NULL matches no account.
They are not assigned to the first person who signs in.

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("google_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("picture", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("uq_users_google_sub", "users", ["google_sub"], unique=True)

    op.add_column(
        "cds",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cds_user_id",
        "cds",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # The catalog key is per user. Drop the global artist/album index first.
    op.drop_index("uq_artist_album_lowercase", table_name="cds")
    op.create_index(
        "uq_artist_album_lowercase",
        "cds",
        ["user_id", sa.text("LOWER(artist)"), sa.text("LOWER(album_name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_artist_album_lowercase", table_name="cds")
    op.create_index(
        "uq_artist_album_lowercase",
        "cds",
        [sa.text("LOWER(artist)"), sa.text("LOWER(album_name)")],
        unique=True,
    )
    op.drop_constraint("fk_cds_user_id", "cds", type_="foreignkey")
    op.drop_column("cds", "user_id")
    op.drop_index("uq_users_google_sub", table_name="users")
    op.drop_table("users")
