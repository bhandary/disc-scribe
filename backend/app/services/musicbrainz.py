import httpx
from typing import Optional
import asyncio


class MusicBrainzService:
    """Fetch cover art from MusicBrainz/Cover Art Archive"""
    
    BASE_URL = "https://musicbrainz.org/ws/2"
    COVER_ART_URL = "https://coverartarchive.org"
    
    @staticmethod
    async def fetch_cover_art(artist: str, album: str) -> Optional[str]:
        """
        Search MusicBrainz for release and fetch cover art URL
        Returns the front cover image URL or None
        """
        headers = {
            "User-Agent": "LinerNotes/1.0 (educational project)",
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                # Search for release
                search_params = {
                    "query": f'artist:"{artist}" AND release:"{album}"',
                    "fmt": "json",
                    "limit": 1
                }
                
                response = await client.get(
                    f"{MusicBrainzService.BASE_URL}/release",
                    params=search_params,
                    headers=headers
                )
                
                if response.status_code != 200:
                    return None
                
                data = response.json()
                releases = data.get("releases", [])
                
                if not releases:
                    return None
                
                release_id = releases[0]["id"]
                
                # Fetch cover art
                await asyncio.sleep(1)  # Rate limiting
                
                cover_response = await client.get(
                    f"{MusicBrainzService.COVER_ART_URL}/release/{release_id}",
                    headers=headers
                )
                
                if cover_response.status_code == 200:
                    cover_data = cover_response.json()
                    images = cover_data.get("images", [])
                    
                    for img in images:
                        if img.get("front"):
                            return img.get("image")
                    
                    if images:
                        return images[0].get("image")
                
                return None
                
            except Exception as e:
                print(f"MusicBrainz error for {artist} - {album}: {e}")
                return None
