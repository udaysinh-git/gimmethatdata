"""Thin wrapper around `instagrapi.Client` for session lifecycle.

instagrapi talks to Instagram's mobile private API (the one their app uses),
which is dramatically more reliable than the public web/GraphQL surface that
instaloader scrapes — IG hardened the web path against automation in 2024.

Three login paths:

  1. `from_session_file()`        — reuse instagrapi's `settings.json`.
  2. `login()`                    — username + password (with optional 2FA code).
  3. `import_session_from_cookie()` — paste `sessionid` from a browser, which is
                                       the most reliable fallback when password
                                       login hits a challenge.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


class IGLoginError(Exception):
    """Raised when login or session loading fails."""


@dataclass
class InstagramClient:
    """Holds an authenticated `instagrapi.Client`."""

    client: Any  # instagrapi.Client — typed Any so this module imports without the extra
    logged_in_as: str | None

    @classmethod
    def anonymous(cls) -> InstagramClient:
        """No login — mostly fails on Instagram's current API. Kept for symmetry."""
        from instagrapi import Client

        client = _quiet_client(Client())
        return cls(client=client, logged_in_as=None)

    @classmethod
    def from_session_file(
        cls,
        *,
        username: str,
        session_file: Path,
    ) -> InstagramClient:
        from instagrapi import Client
        from instagrapi.exceptions import ClientError

        client = _quiet_client(Client())
        try:
            client.load_settings(session_file)
        except FileNotFoundError as exc:
            raise IGLoginError(f"session file not found: {session_file}") from exc
        except Exception as exc:
            raise IGLoginError(f"failed to load session: {exc}") from exc
        try:
            client.get_timeline_feed()  # cheap auth check
        except ClientError as exc:
            raise IGLoginError(f"session is invalid or expired: {exc}") from exc
        _log.info("ig_session_loaded", user=username, path=str(session_file))
        return cls(client=client, logged_in_as=username)

    @classmethod
    def login(
        cls,
        *,
        username: str,
        password: str,
        session_file: Path | None = None,
        verification_code: str | None = None,
    ) -> InstagramClient:
        from instagrapi import Client
        from instagrapi.exceptions import (
            BadPassword,
            ChallengeRequired,
            ClientError,
            PleaseWaitFewMinutes,
            TwoFactorRequired,
        )

        client = _quiet_client(Client())
        if session_file is not None and session_file.exists():
            try:
                client.load_settings(session_file)
            except Exception as exc:
                _log.debug("ig_settings_load_skipped", error=str(exc))
        try:
            client.login(
                username,
                password,
                verification_code=verification_code or "",
            )
        except BadPassword as exc:
            raise IGLoginError("bad password") from exc
        except TwoFactorRequired as exc:
            raise IGLoginError(
                "this account requires a 2FA code. Re-run with --verification-code <6-digit>."
            ) from exc
        except ChallengeRequired as exc:
            raise IGLoginError(_challenge_help(exc)) from exc
        except PleaseWaitFewMinutes as exc:
            raise IGLoginError(
                f"Instagram is rate-limiting this account: {exc}. "
                "Wait 5-10 minutes and retry."
            ) from exc
        except ClientError as exc:
            raise IGLoginError(f"login failed: {exc}") from exc
        if session_file is not None:
            session_file.parent.mkdir(parents=True, exist_ok=True)
            client.dump_settings(session_file)
            _log.info("ig_session_saved", path=str(session_file))
        return cls(client=client, logged_in_as=username)


def import_session_from_cookie(
    *,
    username: str,
    sessionid: str,
    session_file: Path,
) -> Path:
    """Mint an instagrapi settings file from a browser-minted `sessionid` cookie.

    Use when `login()` keeps tripping a challenge:

      1. Open https://www.instagram.com/ in your browser, log in normally.
      2. DevTools -> Application -> Cookies -> instagram.com.
      3. Copy the value of `sessionid` (the long URL-encoded string).
      4. Pass it via `--sessionid`.
    """
    from instagrapi import Client
    from instagrapi.exceptions import ClientError

    client = _quiet_client(Client())
    try:
        client.login_by_sessionid(sessionid)
    except ClientError as exc:
        raise IGLoginError(
            "Instagram rejected the cookie. Re-copy `sessionid` from your "
            f"browser (must currently be logged in). Underlying error: {exc}"
        ) from exc
    session_file.parent.mkdir(parents=True, exist_ok=True)
    client.dump_settings(session_file)
    _log.info("ig_session_imported_from_cookie", user=username, path=str(session_file))
    return session_file


def _quiet_client(client: Any) -> Any:
    """Lower instagrapi's chatty loggers — we surface our own progress."""
    logging.getLogger("public_request").setLevel(logging.WARNING)
    logging.getLogger("private_request").setLevel(logging.WARNING)
    with contextlib.suppress(AttributeError):
        client.request_logger.setLevel(logging.WARNING)
    return client


def _challenge_help(exc: Any) -> str:
    return (
        "Instagram threw a challenge (checkpoint / unfamiliar device). Either:\n"
        "  1. Open the Instagram app on a known device, accept any pending "
        "'was this you?' prompts, then retry.\n"
        "  2. Use `gimmethatdata ig-import-cookie <user> --sessionid <value>` "
        "after logging in via your browser — it sidesteps the challenge entirely.\n"
        f"Raw: {exc}"
    )
