import httpx
from typing import Optional
import asyncio
import re


class MusicBrainzService:
    """Fetch cover art from MusicBrainz/Cover Art Archive"""

    BASE_URL = "https://musicbrainz.org/ws/2"
    COVER_ART_URL = "https://coverartarchive.org"
    USER_AGENT = "DiscVaultAI/1.0 (educational project)"

    # Lucene reserved characters that must be escaped in field queries
    _LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')

    @staticmethod
    def _escape_lucene(value: str) -> str:
        """Escape Lucene special chars so values are safe inside field queries."""
        return MusicBrainzService._LUCENE_SPECIAL.sub(r"\\\1", value).strip()

    @staticmethod
    async def _search_release(client: httpx.AsyncClient, query: str) -> Optional[str]:
        """Run a MusicBrainz release search and return the first release MBID, or None."""
        try:
            resp = await client.get(
                f"{MusicBrainzService.BASE_URL}/release",
                params={"query": query, "fmt": "json", "limit": 5},
                headers={"User-Agent": MusicBrainzService.USER_AGENT, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            releases = resp.json().get("releases", [])
            return releases[0]["id"] if releases else None
        except Exception as e:
            print(f"MusicBrainz search failed for query '{query}': {type(e).__name__}: {e}")
            return None

    @staticmethod
    async def _fetch_cover_for_release(client: httpx.AsyncClient, release_id: str) -> Optional[str]:
        """Fetch front cover art URL for a MusicBrainz release MBID."""
        try:
            resp = await client.get(
                f"{MusicBrainzService.COVER_ART_URL}/release/{release_id}",
                headers={"User-Agent": MusicBrainzService.USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            images = resp.json().get("images", [])
            for img in images:
                if img.get("front"):
                    return img.get("image")
            return images[0].get("image") if images else None
        except Exception as e:
            print(f"CoverArtArchive fetch failed for release {release_id}: {type(e).__name__}: {e}")
            return None

    @staticmethod
    async def fetch_cover_art(artist: str, album: str) -> Optional[str]:
        """
        Search MusicBrainz for a release matching artist+album and return the front
        cover image URL from the Cover Art Archive, or None if no match is found.

        Uses progressive fallbacks since many catalog items (e.g. Bollywood soundtracks)
        don't match an exact-quoted artist+release query:
          1. artist:X AND release:Y   (fielded, exact phrase — strict)
          2. artist:X AND release:Y   (fielded, no quotes — Lucene fuzzy per-term)
          3. release:Y                (album-only fallback; a release with cover art
                                       beats no cover art at all)
        """
        a_escaped = MusicBrainzService._escape_lucene(artist)
        al_escaped = MusicBrainzService._escape_lucene(album)
        if not a_escaped or not al_escaped:
            return None

        queries = [
            f'artist:"{a_escaped}" AND release:"{al_escaped}"',
            f'artist:({a_escaped}) AND release:({al_escaped})',
            f'release:"{al_escaped}"',
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            for idx, query in enumerate(queries):
                release_id = await MusicBrainzService._search_release(client, query)
                if release_id is None:
                    # Be a good MB citizen even on empty results (1 req/sec limit).
                    await asyncio.sleep(1.0)
                    continue

                await asyncio.sleep(1.0)
                cover_url = await MusicBrainzService._fetch_cover_for_release(client, release_id)
                if cover_url:
                    return cover_url
                # Found a release but no cover art — try next, less-strict query.
                await asyncio.sleep(1.0)

        return None
