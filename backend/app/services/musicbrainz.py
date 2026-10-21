import httpx
from typing import Optional, List
import asyncio
import re


class MusicBrainzService:
    """Fetch cover art from MusicBrainz/Cover Art Archive, with iTunes fallback."""

    BASE_URL = "https://musicbrainz.org/ws/2"
    COVER_ART_URL = "https://coverartarchive.org"
    ITUNES_URL = "https://itunes.apple.com/search"
    USER_AGENT = "DiscVaultAI/1.0 (educational project)"

    # Lucene reserved characters that must be escaped in field queries
    _LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')

    @staticmethod
    def _normalize_title(value: str) -> str:
        """Strip catalog junk (leading +, extra whitespace) before searching."""
        cleaned = re.sub(r"^[+\s]+", "", value or "")
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _escape_lucene(value: str) -> str:
        """Escape Lucene special chars so values are safe inside field queries."""
        return MusicBrainzService._LUCENE_SPECIAL.sub(r"\\\1", value).strip()

    @staticmethod
    async def _search_ids(client: httpx.AsyncClient, path: str, query: str) -> List[str]:
        """Search MusicBrainz and return matching MBIDs (up to 5)."""
        try:
            resp = await client.get(
                f"{MusicBrainzService.BASE_URL}/{path}",
                params={"query": query, "fmt": "json", "limit": 5},
                headers={"User-Agent": MusicBrainzService.USER_AGENT, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            key = "releases" if path == "release" else "release-groups"
            return [item["id"] for item in data.get(key, []) if item.get("id")]
        except Exception as e:
            print(f"MusicBrainz search failed for {path} '{query}': {type(e).__name__}: {e}")
            return []

    @staticmethod
    async def _fetch_cover(client: httpx.AsyncClient, kind: str, mbid: str) -> Optional[str]:
        """Fetch front cover art URL from Cover Art Archive for a release or release-group."""
        try:
            resp = await client.get(
                f"{MusicBrainzService.COVER_ART_URL}/{kind}/{mbid}",
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
            print(f"CoverArtArchive fetch failed for {kind} {mbid}: {type(e).__name__}: {e}")
            return None

    @staticmethod
    async def _fetch_itunes_cover(client: httpx.AsyncClient, artist: str, album: str) -> Optional[str]:
        """
        iTunes Search is unauthenticated and has strong Bollywood coverage.
        artworkUrl100 is upscaled to 600x600 via Apple's conventional size swap.
        """
        try:
            album_lower = album.lower()
            artist_lower = artist.lower()
            terms = [f"{artist} {album}", album]
            for term in terms:
                resp = await client.get(
                    MusicBrainzService.ITUNES_URL,
                    params={
                        "term": term,
                        "media": "music",
                        "entity": "album",
                        "limit": 5,
                    },
                    headers={"User-Agent": MusicBrainzService.USER_AGENT, "Accept": "application/json"},
                )
                if resp.status_code != 200:
                    continue
                results = resp.json().get("results") or []
                ranked = []
                for item in results:
                    name = (item.get("collectionName") or "").lower()
                    artist_name = (item.get("artistName") or "").lower()
                    art = item.get("artworkUrl100")
                    if not art:
                        continue
                    score = 0
                    if album_lower in name or name in album_lower:
                        score += 2
                    if artist_lower in artist_name or artist_name in artist_lower:
                        score += 1
                    if score:
                        ranked.append((score, art))
                if ranked:
                    ranked.sort(key=lambda pair: pair[0], reverse=True)
                    art = ranked[0][1]
                    return art.replace("100x100bb", "600x600bb").replace("100x100", "600x600")
            return None
        except Exception as e:
            print(f"iTunes cover fetch failed for {artist} - {album}: {type(e).__name__}: {e}")
            return None

    @staticmethod
    async def fetch_cover_art(artist: str, album: str) -> Optional[str]:
        """
        Search for cover art with progressive fallbacks:
          1. MusicBrainz release search + Cover Art Archive
          2. MusicBrainz release-group search + Cover Art Archive
          3. iTunes Search artwork (strong for Bollywood / Hindi Film)
        """
        artist = MusicBrainzService._normalize_title(artist)
        album = MusicBrainzService._normalize_title(album)
        a_escaped = MusicBrainzService._escape_lucene(artist)
        al_escaped = MusicBrainzService._escape_lucene(album)
        if not a_escaped or not al_escaped:
            return None

        queries = [
            f'artist:"{a_escaped}" AND release:"{al_escaped}"',
            f'artist:({a_escaped}) AND release:({al_escaped})',
            f'release:"{al_escaped}"',
        ]

        async with httpx.AsyncClient(timeout=12.0) as client:
            # iTunes first: unauthenticated, fast, and much better coverage
            # for Hindi-film soundtracks than MusicBrainz.
            itunes_url = await MusicBrainzService._fetch_itunes_cover(client, artist, album)
            if itunes_url:
                return itunes_url

            for query in queries:
                release_ids = await MusicBrainzService._search_ids(client, "release", query)
                await asyncio.sleep(1.0)
                for release_id in release_ids[:2]:
                    cover_url = await MusicBrainzService._fetch_cover(client, "release", release_id)
                    if cover_url:
                        return cover_url
                    await asyncio.sleep(1.0)

            group_query = f'artist:({a_escaped}) AND releasegroup:({al_escaped})'
            group_ids = await MusicBrainzService._search_ids(client, "release-group", group_query)
            await asyncio.sleep(1.0)
            for group_id in group_ids[:2]:
                cover_url = await MusicBrainzService._fetch_cover(client, "release-group", group_id)
                if cover_url:
                    return cover_url
                await asyncio.sleep(1.0)

        return None
