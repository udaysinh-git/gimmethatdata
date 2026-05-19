"""Instagram archiver: profile, posts, reels, highlights, comments.

Built on instaloader for session/GraphQL handling. Use at your own risk —
Instagram's ToS prohibits automated access without authorization; this code
exists to let you archive content you own or have explicit permission to
collect (e.g. your own account, accounts you administer, OSINT for journalism
or research).
"""

from gimmethatdata.instagram.client import IGLoginError, InstagramClient
from gimmethatdata.instagram.downloader import (
    DownloadOptions as IGDownloadOptions,
)
from gimmethatdata.instagram.downloader import (
    DownloadReport,
    download_profile,
)

__all__ = [
    "DownloadReport",
    "IGDownloadOptions",
    "IGLoginError",
    "InstagramClient",
    "download_profile",
]
