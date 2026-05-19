"""Discover subdomains of a base domain via the Certificate Transparency log.

Uses crt.sh, which exposes a JSON API listing every TLS certificate issued for
a domain — most subdomains worth caring about show up there.
"""

from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import quote

import httpx

from gimmethatdata.core.url_utils import domain_of
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)

_CRT_SH_URL = "https://crt.sh/?q=%25.{domain}&output=json"
_WILDCARD_RE = re.compile(r"^\*\.")


async def discover_subdomains(
    seed_url: str,
    *,
    user_agent: str,
    timeout: float = 15.0,  # noqa: ASYNC109 — HTTP timeout, not a cancel deadline
    max_subdomains: int = 200,
) -> list[str]:
    """Return distinct subdomain hosts (without scheme) for the seed's eTLD+1."""
    base = domain_of(seed_url)
    if not base:
        return []
    # Strip "www." prefix so we query the eTLD+1.
    if base.startswith("www."):
        base = base[4:]
    url = _CRT_SH_URL.format(domain=quote(base))

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.text
    except httpx.HTTPError as exc:
        _log.warning("subdomain_lookup_failed", domain=base, error=str(exc))
        return []

    try:
        rows = json.loads(payload)
    except json.JSONDecodeError:
        return []

    discovered: set[str] = set()
    for row in rows:
        name = row.get("name_value") or ""
        for raw in name.splitlines():
            host = _WILDCARD_RE.sub("", raw).strip().lower()
            if not host:
                continue
            # Only keep hosts within the base domain.
            if host == base or host.endswith("." + base):
                discovered.add(host)
            if len(discovered) >= max_subdomains:
                break
        if len(discovered) >= max_subdomains:
            break

    # Order: alphabetical, but keep the base domain first if present.
    out = sorted(discovered)
    if base in out:
        out.remove(base)
        out.insert(0, base)
    return out


async def discover_subdomain_seeds(
    seed_url: str,
    *,
    user_agent: str,
    scheme: str = "https",
    timeout: float = 15.0,  # noqa: ASYNC109 — HTTP timeout, not a cancel deadline
    max_subdomains: int = 200,
) -> list[str]:
    """Subdomains formatted as seed URLs (scheme://host/) ready for the frontier."""
    hosts = await discover_subdomains(
        seed_url,
        user_agent=user_agent,
        timeout=timeout,
        max_subdomains=max_subdomains,
    )
    return [f"{scheme}://{host}/" for host in hosts]


def _sync_discover(seed_url: str, *, user_agent: str) -> list[str]:
    """Sync wrapper used by the CLI command (`gimmethatdata subdomains`)."""
    return asyncio.run(discover_subdomains(seed_url, user_agent=user_agent))
