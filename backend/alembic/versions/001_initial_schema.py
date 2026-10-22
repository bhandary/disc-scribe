"""initial schema

Revision ID: 001
Revises: 
Create Date: 2026-10-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    # pgvector is optional: local Docker has it, Railway's managed Postgres may not.
    # embedding is stored as TEXT, so the app runs without the extension.
    op.execute("""
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector extension not available, skipping';
END
$$;
""")
    
    # Create cds table
    op.create_table(
        'cds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('artist', sa.String(255), nullable=False),
        sa.Column('album_name', sa.String(255), nullable=False),
        sa.Column('lyricist', sa.String(255), nullable=True),
        sa.Column('genre', sa.String(100), nullable=False),
        sa.Column('num_discs', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('cover_art_url', sa.Text(), nullable=True),
        sa.Column('release_year', sa.Integer(), nullable=True),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_sources', postgresql.JSONB(), nullable=True),
        sa.Column('embedding', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    
    # Create indexes
    op.create_index('idx_artist', 'cds', ['artist'])
    op.create_index('idx_album_name', 'cds', ['album_name'])
    op.create_index('idx_lyricist', 'cds', ['lyricist'])
    op.create_index('idx_genre', 'cds', ['genre'])
    
    # Create GIN indexes for pg_trgm
    op.execute('CREATE INDEX idx_artist_trgm ON cds USING gin (artist gin_trgm_ops)')
    op.execute('CREATE INDEX idx_album_trgm ON cds USING gin (album_name gin_trgm_ops)')
    op.execute('CREATE INDEX idx_lyricist_trgm ON cds USING gin (lyricist gin_trgm_ops)')
    
    # Create unique constraint
    op.create_index(
        'uq_artist_album_lowercase',
        'cds',
        [sa.text('LOWER(artist)'), sa.text('LOWER(album_name)')],
        unique=True
    )
    
    # Create app_settings table
    op.create_table(
        'app_settings',
        sa.Column('key_name', sa.String(100), primary_key=True),
        sa.Column('encrypted_value', sa.String(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_table('cds')
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "vector"')
