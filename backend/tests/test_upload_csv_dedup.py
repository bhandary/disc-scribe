"""CSV import dedup against Postgres.

Needs DATABASE_URL (default below) and the unique index
uq_artist_album_lowercase on (user_id, LOWER(artist), LOWER(album_name)).
Skips when Postgres is not reachable. Both uploads belong to one user.
Two users importing the same album are covered by tests/test_accounts.py.
"""

import asyncio
import os
import unittest
import uuid
from io import BytesIO

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://discvault:discvault@127.0.0.1:5432/discvault_dedup_test",
)
os.environ.setdefault("ENCRYPTION_SECRET", "test-key-only-for-dev-32bytes")

from sqlalchemy import text
from starlette.datastructures import UploadFile

from app.api.routes import cds as cds_routes
from app.core.database import AsyncSessionLocal, engine


async def _quiet_cover(_user_id):
    return None


def _csv(body: str) -> UploadFile:
    return UploadFile(filename="collection.csv", file=BytesIO(body.encode()))


class _Owner:
    def __init__(self, user_id: uuid.UUID):
        self.id = user_id


OWNER = _Owner(uuid.UUID("11111111-1111-1111-1111-111111111111"))


class CsvDedupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            self.skipTest(f"Postgres is not reachable: {exc}")

        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS cds"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE cds (
                        id UUID PRIMARY KEY,
                        user_id UUID,
                        artist VARCHAR(255) NOT NULL,
                        album_name VARCHAR(255) NOT NULL,
                        lyricist VARCHAR(255),
                        genre VARCHAR(100) NOT NULL,
                        num_discs INTEGER NOT NULL DEFAULT 1,
                        cover_art_url TEXT,
                        release_year INTEGER,
                        ai_summary TEXT,
                        ai_sources JSONB,
                        embedding TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX uq_artist_album_lowercase
                    ON cds (user_id, LOWER(artist), LOWER(album_name))
                    """
                )
            )
        cds_routes.fetch_missing_cover_art = _quiet_cover

    async def asyncTearDown(self):
        await engine.dispose()

    async def _rows(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT artist, album_name, lyricist, genre, num_discs, ai_summary
                    FROM cds
                    ORDER BY lower(artist), lower(album_name)
                    """
                )
            )
            return [tuple(row) for row in result]

    async def test_trailing_space_and_repeat_update_one_row(self):
        body = (
            "artist,album_name,lyricist,genre,num_discs\n"
            "The Beatles,Abbey Road,Lennon,Rock,1\n"
            "the beatles,Abbey Road ,McCartney,Pop,2\n"
        )
        async with AsyncSessionLocal() as session:
            first = await cds_routes.upload_csv(_csv(body), session, OWNER)
        self.assertEqual(first["errors"], [])
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(first["updated"], 1)
        rows = await self._rows()
        self.assertEqual(len(rows), 1)
        artist, album, lyricist, genre, discs, summary = rows[0]
        self.assertEqual(artist, "The Beatles")
        self.assertEqual(album, "Abbey Road")
        self.assertEqual(lyricist, "McCartney")
        self.assertEqual(genre, "Pop")
        self.assertEqual(discs, 2)
        self.assertIsNone(summary)

        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE cds SET ai_summary = 'kept' WHERE lower(album_name) = 'abbey road'")
            )
            await session.commit()
            second = await cds_routes.upload_csv(
                _csv(
                    "artist,album_name,lyricist,genre,num_discs\n"
                    "THE BEATLES,  Abbey Road  ,Harrison,Jazz,3\n"
                ),
                session,
                OWNER,
            )
        self.assertEqual(second["errors"], [])
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["updated"], 1)
        rows = await self._rows()
        self.assertEqual(len(rows), 1)
        artist, album, lyricist, genre, discs, summary = rows[0]
        self.assertEqual(album, "Abbey Road")
        self.assertEqual(artist, "The Beatles")
        self.assertEqual(genre, "Jazz")
        self.assertEqual(lyricist, "Harrison")
        self.assertEqual(discs, 3)
        self.assertEqual(summary, "kept")

    async def test_overlapping_uploads_keep_every_album(self):
        file_a = (
            "artist,album_name,lyricist,genre,num_discs\n"
            "The Beatles,Revolver,Lennon,Rock,1\n"
            "The Beatles,Abbey Road,Lennon,Rock,1\n"
        )
        file_b = (
            "artist,album_name,lyricist,genre,num_discs\n"
            "the beatles,Abbey Road ,McCartney,Pop,2\n"
            "The Beatles,Help!,Lennon,Rock,1\n"
        )

        async def _run(body: str):
            async with AsyncSessionLocal() as session:
                return await cds_routes.upload_csv(_csv(body), session, OWNER)

        left, right = await asyncio.gather(_run(file_a), _run(file_b))
        self.assertEqual(left["errors"], [])
        self.assertEqual(right["errors"], [])
        self.assertEqual(left["inserted"] + left["updated"], 2)
        self.assertEqual(right["inserted"] + right["updated"], 2)

        rows = await self._rows()
        keys = {(artist.lower(), album.lower()) for artist, album, *_rest in rows}
        self.assertEqual(
            keys,
            {
                ("the beatles", "abbey road"),
                ("the beatles", "revolver"),
                ("the beatles", "help!"),
            },
        )
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
