"""Shared platform URL patterns for all discovery adapters."""
from __future__ import annotations
import re

PLATFORM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("youtube",  re.compile(r"(?:www\.)?youtube\.com/(?:@|c/|user/)?([A-Za-z0-9_.\-]{2,})(?=[/?#\s]|$)", re.I)),
    ("github",   re.compile(r"(?:www\.)?github\.com/([A-Za-z0-9_.\-]{1,39})(?=[/?#\s]|$)", re.I)),
    ("tiktok",   re.compile(r"(?:www\.)?tiktok\.com/@?([A-Za-z0-9_.\-]{2,})(?=[/?#\s]|$)", re.I)),
    ("twitter",  re.compile(r"(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})(?=[/?#\s]|$)", re.I)),
    ("twitch",   re.compile(r"(?:www\.)?twitch\.tv/([A-Za-z0-9_]{4,25})(?=[/?#\s]|$)", re.I)),
    ("reddit",   re.compile(r"(?:www\.)?reddit\.com/u(?:ser)?/([A-Za-z0-9_\-]{3,20})(?=[/?#\s]|$)", re.I)),
    ("substack", re.compile(r"([A-Za-z0-9_\-]{2,})\.substack\.com(?:[/?#]|$)", re.I)),
    ("spotify",  re.compile(r"open\.spotify\.com/(?:user|artist)/([A-Za-z0-9_\-]{2,})", re.I)),
]
