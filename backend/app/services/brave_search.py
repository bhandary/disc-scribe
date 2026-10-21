"""
Thin async client for the Brave Search API.

Docs: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started

Returns results in a dict shape intentionally compatible with the shape the
deep-agent synthesizer previously expected from Tavily:
    [{"title": "...", "url": "...", "content": "..."}, ...]
"""

from typing import List, Dict, Any, Optional
import httpx


class BraveSearchService:
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
    DEFAULT_COUNT = 5
    TIMEOUT_SECONDS = 15.0

    @staticmethod
    async def search(
        query: str,
        api_key: str,
        count: int = DEFAULT_COUNT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run a Brave web search and return a list of result dicts.

        Raises on non-2xx responses so the caller can surface a useful error in
        the SSE stream (e.g. 401 for a bad key, 429 for rate limiting).
        """
        if not api_key:
            raise ValueError("Brave Search API key is required")

        headers = {
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        params = {"q": query, "count": min(max(count, 1), 20)}

        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=BraveSearchService.TIMEOUT_SECONDS)

        try:
            resp = await client.get(
                BraveSearchService.ENDPOINT, headers=headers, params=params
            )
            if resp.status_code != 200:
                # Surface Brave's error message when available for easier debugging.
                try:
                    body = resp.json()
                    msg = body.get("message") or body.get("error") or resp.text
                except Exception:
                    msg = resp.text
                raise RuntimeError(f"Brave Search HTTP {resp.status_code}: {msg}")

            data = resp.json()
            web_results = (data.get("web") or {}).get("results") or []

            normalized: List[Dict[str, Any]] = []
            for item in web_results:
                normalized.append(
                    {
                        "title": item.get("title") or item.get("url") or "Source",
                        "url": item.get("url", ""),
                        # Match Tavily's "content" field so downstream prompts don't change.
                        "content": item.get("description") or item.get("snippet") or "",
                    }
                )
            return normalized
        finally:
            if owns_client:
                await client.aclose()
