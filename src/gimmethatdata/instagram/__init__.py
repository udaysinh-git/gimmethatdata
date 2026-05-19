"""Instagram archiver: profile, posts, reels, highlights, comments, analytics.

Built on instagrapi. Use at your own risk — Instagram's ToS prohibits automated
access without authorization; this code exists to let you archive content you
own or have explicit permission to collect.
"""

from gimmethatdata.instagram.analytics import (
    EngagementReport,
)
from gimmethatdata.instagram.analytics import (
    analyze as analyze_engagement,
)
from gimmethatdata.instagram.analytics import (
    render_markdown as render_engagement_md,
)
from gimmethatdata.instagram.analytics import (
    write_report as write_engagement_report,
)
from gimmethatdata.instagram.client import IGLoginError, InstagramClient
from gimmethatdata.instagram.compare import CompareReport
from gimmethatdata.instagram.compare import compare as compare_profiles
from gimmethatdata.instagram.compare import write_report as write_compare_report
from gimmethatdata.instagram.contact_sheet import write_contact_sheet
from gimmethatdata.instagram.downloader import (
    DownloadOptions as IGDownloadOptions,
)
from gimmethatdata.instagram.downloader import (
    DownloadReport,
    download_profile,
)

__all__ = [
    "CompareReport",
    "DownloadReport",
    "EngagementReport",
    "IGDownloadOptions",
    "IGLoginError",
    "InstagramClient",
    "analyze_engagement",
    "compare_profiles",
    "download_profile",
    "render_engagement_md",
    "write_compare_report",
    "write_contact_sheet",
    "write_engagement_report",
]
