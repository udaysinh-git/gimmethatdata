"""robots.txt fetcher with per-domain caching."""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


class RobotsCache:
    """Async robots.txt cache. Defaults to allow-all on fetch failure."""

    def __init__(self, *, user_agent: str, timeout_seconds: float = 10.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._cache: dict[str, RobotFileParser | None] = {}

    async def _load(self, scheme: str, host: str) -> RobotFileParser | None:
        url = f"{scheme}://{host}/robots.txt"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            _log.debug("robots_fetch_failed", host=host, error=str(exc))
            return None
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    async def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.netloc:
            return True
        host_key = f"{parsed.scheme}://{parsed.netloc}".lower()
        if host_key not in self._cache:
            self._cache[host_key] = await self._load(parsed.scheme, parsed.netloc)
        parser = self._cache[host_key]
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)
