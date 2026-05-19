"""Auth helpers — basic/bearer/cookies/extra headers for fetchers."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path


@dataclass
class AuthConfig:
    """Auth knobs resolved from CLI flags / settings."""

    basic: tuple[str, str] | None = None  # (user, pass)
    bearer: str | None = None
    cookies: dict[str, str] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict)

    def header_overrides(self) -> dict[str, str]:
        out: dict[str, str] = dict(self.extra_headers)
        if self.basic is not None:
            user, password = self.basic
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            out["Authorization"] = f"Basic {token}"
        elif self.bearer:
            out["Authorization"] = f"Bearer {self.bearer}"
        if self.cookies:
            out["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return out

    @classmethod
    def from_cli(
        cls,
        *,
        auth: str | None,
        cookies_arg: list[str] | None,
        cookies_file: Path | None,
        headers_arg: list[str] | None,
    ) -> AuthConfig:
        basic: tuple[str, str] | None = None
        bearer: str | None = None
        if auth:
            scheme, _, rest = auth.partition(":")
            scheme = scheme.lower().strip()
            if scheme == "basic":
                user, _, password = rest.partition(":")
                basic = (user, password)
            elif scheme == "bearer":
                bearer = rest.strip()
            else:
                raise ValueError(f"--auth expects basic:user:pass or bearer:<token>, got: {auth!r}")

        cookies: dict[str, str] = {}
        for raw in cookies_arg or []:
            cookies.update(_parse_cookie_header(raw))
        if cookies_file is not None:
            cookies.update(parse_cookies_file(cookies_file))

        extras: dict[str, str] = {}
        for raw in headers_arg or []:
            name, sep, value = raw.partition(":")
            if not sep:
                raise ValueError(f"--header expects 'Name: Value', got: {raw!r}")
            extras[name.strip()] = value.strip()

        return cls(basic=basic, bearer=bearer, cookies=cookies, extra_headers=extras)


def _parse_cookie_header(raw: str) -> dict[str, str]:
    """Accept either 'k=v' or 'k=v; k2=v2'."""
    jar: SimpleCookie = SimpleCookie()
    jar.load(raw)
    return {k: morsel.value for k, morsel in jar.items()}


def parse_cookies_file(path: Path) -> dict[str, str]:
    """Parse a Netscape `cookies.txt` file."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name, value = parts[5], parts[6]
            if name:
                out[name] = value
    return out
