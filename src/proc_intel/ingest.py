"""Small pure helpers for paging the World Bank APIs and naming raw snapshot files."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date, datetime

WB_DATE_FORMAT = "%d-%b-%Y"  # both APIs write dates as 19-Oct-2026


def parse_wb_date(value: str | None) -> date | None:
    """Parse a '19-Oct-2026' style date; None for empty or malformed input."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), WB_DATE_FORMAT).date()
    except ValueError:
        return None


def page_offsets(total: int, page_size: int) -> list[int]:
    """Offsets 0, page_size, 2*page_size, ... that cover `total` rows."""
    if total < 0 or page_size <= 0:
        raise ValueError("total must be >= 0 and page_size > 0")
    return list(range(0, total, page_size))


def page_is_older_than(notices: Iterable[Mapping], cutoff: date) -> bool:
    """True when every notice on the page with a readable `noticedate` is before `cutoff`.

    Used to stop paging a country (sorted by id, newest first) once a whole page predates
    the cutoff. A page with no readable dates counts as old, so paging always terminates.
    """
    dates = [d for d in (parse_wb_date(n.get("noticedate")) for n in notices) if d is not None]
    return all(d < cutoff for d in dates)


def slugify(text: str) -> str:
    """File-system-safe ASCII name, e.g. "Cote d'Ivoire" -> 'cote_d_ivoire'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or "unknown"


def partition_folder(name: str) -> str:
    """Readable and collision-free folder name: slug plus a short hash of the exact name.

    Two partition names can share a slug ('Turkiye' / 'Türkiye'), so the slug alone is not a key.
    """
    return f"{slugify(name)}_{hashlib.sha1(name.encode('utf-8')).hexdigest()[:6]}"


def page_file_name(offset: int) -> str:
    """Zero-padded so a directory listing sorts in paging order."""
    return f"page_{offset:07d}.json"
