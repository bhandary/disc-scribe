import asyncio
import re
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from app.core.config import settings
from app.services.musicbrainz import MusicBrainzService


USER_AGENT = "TheRack/1.0 (https://github.com/bhandary/disc-scribe)"
DISCOGS_SEARCH = "https://api.discogs.com/database/search"
DISCOGS_ARTIST_DISAMBIG = re.compile(r"\s*\(\d+\)$")


@dataclass
class AlbumMatch:
    barcode: str
    artist: str
    album_name: str
    genre: str
    source: str
    lyricist: Optional[str] = None
    num_discs: int = 1
    cover_art_url: Optional[str] = None
    release_year: Optional[int] = None
    label: Optional[str] = None
    tracks: List[dict] = field(default_factory=list)


class BarcodeLookupService:
    """Look up a CD by barcode via MusicBrainz, then Discogs."""

    @staticmethod
    def normalize(raw: str) -> str:
        return re.sub(r"[^\d]", "", raw or "")

    @staticmethod
    def variants(code: str) -> List[str]:
        """UPC-A and EAN-13 are the same number with/without a leading zero."""
        if not code:
            return []
        seen = []
        for candidate in (code, f"0{code}" if len(code) == 12 else None, code[1:] if len(code) == 13 and code.startswith("0") else None):
            if candidate and candidate not in seen:
                seen.append(candidate)
        return seen

    @staticmethod
    def _parse_year(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        digits = re.match(r"(\d{4})", str(value))
        if not digits:
            return None
        year = int(digits.group(1))
        if 1900 <= year <= 2100:
            return year
        return None

    @staticmethod
    def _format_ms(ms: Optional[int]) -> Optional[str]:
        if not ms or ms <= 0:
            return None
        seconds = int(ms) // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _artist_credit(credit: Optional[list]) -> str:
        parts: List[str] = []
        for item in credit or []:
            name = item.get("name") or (item.get("artist") or {}).get("name") or ""
            parts.append(name)
            parts.append(item.get("joinphrase") or "")
        return "".join(parts).strip()

    @staticmethod
    def _genre_from_mb(release: dict) -> str:
        buckets = []
        for key in ("genres", "tags"):
            buckets.extend(release.get(key) or [])
            buckets.extend((release.get("release-group") or {}).get(key) or [])
        ranked = sorted(
            [item for item in buckets if item.get("name")],
            key=lambda item: item.get("count") or 0,
            reverse=True,
        )
        if ranked:
            return ranked[0]["name"].title()
        return "Unknown"

    @staticmethod
    def _tracks_from_mb(release: dict) -> List[dict]:
        tracks = []
        for medium in release.get("media") or []:
            disc = medium.get("position")
            for track in medium.get("tracks") or []:
                position = str(track.get("number") or track.get("position") or "")
                if disc and len(release.get("media") or []) > 1 and position and not position.startswith(f"{disc}-"):
                    position = f"{disc}-{position}"
                title = (track.get("title") or (track.get("recording") or {}).get("title") or "").strip()
                if not title:
                    continue
                tracks.append({
                    "position": position or str(len(tracks) + 1),
                    "title": title,
                    "duration": BarcodeLookupService._format_ms(track.get("length") or (track.get("recording") or {}).get("length")),
                })
        return tracks

    @staticmethod
    def _pick_mb_release(releases: list) -> Optional[dict]:
        if not releases:
            return None
        return max(
            releases,
            key=lambda rel: (
                1 if (rel.get("status") or "").lower() == "official" else 0,
                rel.get("score") or 0,
                1 if rel.get("date") else 0,
            ),
        )

    @staticmethod
    async def _lookup_musicbrainz(client: httpx.AsyncClient, code: str) -> Optional[AlbumMatch]:
        try:
            resp = await client.get(
                f"{MusicBrainzService.BASE_URL}/release",
                params={"query": f"barcode:{code}", "fmt": "json", "limit": 5},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            picked = BarcodeLookupService._pick_mb_release(resp.json().get("releases") or [])
            if not picked or not picked.get("id"):
                return None

            await asyncio.sleep(1.0)
            detail = await client.get(
                f"{MusicBrainzService.BASE_URL}/release/{picked['id']}",
                params={
                    "fmt": "json",
                    "inc": "recordings+labels+artist-credits+release-groups+tags+genres",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if detail.status_code != 200:
                return None
            release = detail.json()

            artist = BarcodeLookupService._artist_credit(release.get("artist-credit"))
            album = (release.get("title") or "").strip()
            if not artist or not album:
                return None

            labels = release.get("label-info") or []
            label = None
            if labels:
                label = ((labels[0].get("label") or {}).get("name") or "").strip() or None

            cover = await MusicBrainzService._fetch_cover(client, "release", picked["id"])
            if not cover:
                cover = await MusicBrainzService._fetch_itunes_cover(client, artist, album)

            return AlbumMatch(
                barcode=release.get("barcode") or code,
                artist=artist,
                album_name=album,
                genre=BarcodeLookupService._genre_from_mb(release),
                source="musicbrainz",
                num_discs=max(len(release.get("media") or []) or 1, 1),
                cover_art_url=cover,
                release_year=BarcodeLookupService._parse_year(release.get("date")),
                label=label,
                tracks=BarcodeLookupService._tracks_from_mb(release),
            )
        except Exception as e:
            print(f"MusicBrainz barcode lookup failed for {code}: {type(e).__name__}: {e}")
            return None

    @staticmethod
    def _discogs_headers() -> dict:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if settings.DISCOGS_TOKEN:
            headers["Authorization"] = f"Discogs token={settings.DISCOGS_TOKEN}"
        return headers

    @staticmethod
    def _clean_discogs_artist(name: str) -> str:
        return DISCOGS_ARTIST_DISAMBIG.sub("", name or "").strip()

    @staticmethod
    async def _lookup_discogs(client: httpx.AsyncClient, code: str) -> Optional[AlbumMatch]:
        try:
            resp = await client.get(
                DISCOGS_SEARCH,
                params={"barcode": code, "type": "release"},
                headers=BarcodeLookupService._discogs_headers(),
            )
            if resp.status_code != 200:
                return None
            results = resp.json().get("results") or []
            if not results:
                return None

            resource_url = results[0].get("resource_url")
            if not resource_url:
                return None

            detail = await client.get(resource_url, headers=BarcodeLookupService._discogs_headers())
            if detail.status_code != 200:
                return None
            release = detail.json()

            artists = release.get("artists") or []
            artist = BarcodeLookupService._clean_discogs_artist(
                artists[0].get("name") if artists else ""
            )
            album = (release.get("title") or "").strip()
            if not artist or not album:
                return None

            labels = release.get("labels") or []
            label = BarcodeLookupService._clean_discogs_artist(labels[0].get("name") if labels else "") or None
            genres = release.get("genres") or release.get("styles") or []
            genre = genres[0] if genres else "Unknown"

            tracks = []
            for item in release.get("tracklist") or []:
                if (item.get("type_") or "track") not in ("track", "index"):
                    continue
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                tracks.append({
                    "position": str(item.get("position") or len(tracks) + 1),
                    "title": title,
                    "duration": (item.get("duration") or "").strip() or None,
                })

            formats = release.get("formats") or []
            num_discs = 1
            for fmt in formats:
                if "CD" in (fmt.get("name") or "").upper() or "CD" in " ".join(fmt.get("descriptions") or []).upper():
                    try:
                        num_discs = max(int(fmt.get("qty") or 1), 1)
                    except (TypeError, ValueError):
                        num_discs = 1
                    break

            cover = (release.get("images") or [{}])[0].get("uri") or results[0].get("cover_image")
            if cover and "spacer.gif" in cover:
                cover = None
            if not cover:
                cover = await MusicBrainzService._fetch_itunes_cover(client, artist, album)

            return AlbumMatch(
                barcode=code,
                artist=artist,
                album_name=album,
                genre=str(genre),
                source="discogs",
                num_discs=num_discs,
                cover_art_url=cover,
                release_year=BarcodeLookupService._parse_year(str(release.get("year") or "")),
                label=label,
                tracks=tracks,
            )
        except Exception as e:
            print(f"Discogs barcode lookup failed for {code}: {type(e).__name__}: {e}")
            return None

    @staticmethod
    async def lookup(raw_barcode: str) -> Optional[AlbumMatch]:
        code = BarcodeLookupService.normalize(raw_barcode)
        if len(code) < 8 or len(code) > 14:
            return None

        async with httpx.AsyncClient(timeout=15.0) as client:
            for variant in BarcodeLookupService.variants(code):
                match = await BarcodeLookupService._lookup_musicbrainz(client, variant)
                if match:
                    return match
                await asyncio.sleep(0.4)

            for variant in BarcodeLookupService.variants(code):
                match = await BarcodeLookupService._lookup_discogs(client, variant)
                if match:
                    return match

        return None
