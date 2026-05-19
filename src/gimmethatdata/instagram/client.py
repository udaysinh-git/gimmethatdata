"""Thin wrapper around `instaloader.Instaloader` for session lifecycle.

Login flow:
  1. If `session_file` is given and exists, load it.
  2. Otherwise log in with `username` + `password` (prompts for `password`
     if not provided). Saves the session to `session_file` so the next run
     skips login entirely.

We do not handle 2FA prompts here — instaloader's CLI does that interactively
and would conflict with our Typer command. Users with 2FA should run
`instaloader --login=<user>` once to mint a session file, then pass that path
via `--session-file`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import instaloader

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


class IGLoginError(Exception):
    """Raised when login or session loading fails."""


@dataclass
class InstagramClient:
    """Holds an authenticated `instaloader.Instaloader`."""

    loader: instaloader.Instaloader
    logged_in_as: str | None

    @classmethod
    def anonymous(cls, *, user_agent: str | None = None) -> InstagramClient:
        """Anonymous client — public profiles + public posts only."""
        loader = _make_loader(user_agent=user_agent)
        return cls(loader=loader, logged_in_as=None)

    @classmethod
    def from_session_file(
        cls,
        *,
        username: str,
        session_file: Path,
        user_agent: str | None = None,
    ) -> InstagramClient:
        """Resume a session previously minted via instaloader CLI."""
        loader = _make_loader(user_agent=user_agent)
        try:
            loader.load_session_from_file(username, str(session_file))
        except FileNotFoundError as exc:
            raise IGLoginError(f"session file not found: {session_file}") from exc
        except Exception as exc:
            raise IGLoginError(f"failed to load session: {exc}") from exc
        _log.info("ig_session_loaded", user=username, path=str(session_file))
        return cls(loader=loader, logged_in_as=username)

    @classmethod
    def login(
        cls,
        *,
        username: str,
        password: str,
        session_file: Path | None = None,
        user_agent: str | None = None,
    ) -> InstagramClient:
        """Username/password login. Saves the session to `session_file` if given."""
        loader = _make_loader(user_agent=user_agent)
        try:
            loader.login(username, password)
        except instaloader.exceptions.TwoFactorAuthRequiredException as exc:
            raise IGLoginError(
                "this account has 2FA enabled. Mint a session externally with "
                "`instaloader --login=<user>` and pass --session-file instead."
            ) from exc
        except instaloader.exceptions.BadCredentialsException as exc:
            raise IGLoginError("bad credentials") from exc
        except instaloader.exceptions.ConnectionException as exc:
            raise IGLoginError(f"connection / checkpoint error: {exc}") from exc
        except Exception as exc:
            raise IGLoginError(f"login failed: {exc}") from exc
        if session_file is not None:
            session_file.parent.mkdir(parents=True, exist_ok=True)
            loader.save_session_to_file(str(session_file))
            _log.info("ig_session_saved", path=str(session_file))
        return cls(loader=loader, logged_in_as=username)


def _make_loader(*, user_agent: str | None) -> instaloader.Instaloader:
    """Construct an Instaloader instance with conservative defaults."""
    return instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        storyitem_metadata_txt_pattern="",
        quiet=True,
        user_agent=user_agent,
    )
