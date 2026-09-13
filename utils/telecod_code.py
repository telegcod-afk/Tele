"""TeleCodRobot canonical file-code helpers.

Canonical format:
    telecod_<photo>p<video>v<document>d_<random9>

Example:
    telecod_2p10v0d_C62Xy9zxy
"""
from __future__ import annotations

import re
import secrets
import string

TELECOD_CODE_RE = re.compile(
    r"^telecod_(?P<photo>\d+)p(?P<video>\d+)v(?P<document>\d+)d_(?P<random>[A-Za-z0-9]{9})$",
    re.IGNORECASE,
)

TELECOD_CODE_SEARCH_RE = re.compile(
    r"(?<![A-Za-z0-9])telecod_\d+p\d+v\d+d_[A-Za-z0-9]{9}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def build_code(photo: int, video: int, document: int, random_part: str | None = None) -> str:
    photo = max(0, int(photo or 0))
    video = max(0, int(video or 0))
    document = max(0, int(document or 0))

    if random_part is None:
        alphabet = string.ascii_letters + string.digits
        random_part = "".join(secrets.choice(alphabet) for _ in range(9))

    if not re.fullmatch(r"[A-Za-z0-9]{9}", random_part):
        raise ValueError("random_part must contain exactly 9 alphanumeric characters")

    return f"telecod_{photo}p{video}v{document}d_{random_part}"


def normalize_code(value: str | None) -> str:
    if not value:
        return ""
    return str(value).strip().replace(" ", "").replace("\n", "").replace("\r", "")


def is_valid_code(value: str | None) -> bool:
    return bool(TELECOD_CODE_RE.fullmatch(normalize_code(value)))


def extract_code(value: str | None) -> str:
    if not value:
        return ""
    m = TELECOD_CODE_SEARCH_RE.search(str(value))
    return m.group(0) if m else ""
