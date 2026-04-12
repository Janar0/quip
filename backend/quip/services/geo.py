"""Coarse IP-based geolocation for runtime context injection.

Loads GeoLite2-City.mmdb once at import time. If the file is missing (dev
environment, fresh checkout, stripped Docker image), every lookup returns
``None`` and the base prompt simply omits the location line — the server
still starts and serves requests normally.
"""
import ipaddress
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import Request

logger = logging.getLogger(__name__)

_reader = None
try:
    import geoip2.database  # type: ignore
    _DB_PATH = Path(__file__).resolve().parent.parent / "data" / "GeoLite2-City.mmdb"
    if _DB_PATH.exists():
        _reader = geoip2.database.Reader(str(_DB_PATH))
        logger.info("geoip2 loaded: %s", _DB_PATH.name)
    else:
        logger.warning("GeoLite2-City.mmdb missing at %s — geo context disabled", _DB_PATH)
except ImportError:
    logger.warning("geoip2 package not installed — geo context disabled")
except Exception as e:  # noqa: BLE001
    logger.warning("geoip2 init failed: %s", e)


@dataclass(frozen=True)
class GeoInfo:
    country: str
    city: Optional[str]


def client_ip(request: Request) -> Optional[str]:
    """Extract the best-effort client IP from a FastAPI request.

    Honors ``X-Forwarded-For`` (first hop) then ``X-Real-IP`` then the
    socket peer. Returns ``None`` for private / loopback / reserved ranges
    so dev setups don't waste a lookup.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client else None
        )
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
        return None
    return ip


@lru_cache(maxsize=4096)
def resolve(ip: Optional[str]) -> Optional[GeoInfo]:
    """Resolve an IP to coarse location (city + country). Best-effort."""
    if not ip or _reader is None:
        return None
    try:
        r = _reader.city(ip)
    except Exception:  # noqa: BLE001
        return None
    country = r.country.name or ""
    if not country:
        return None
    return GeoInfo(country=country, city=r.city.name or None)


def format_location(geo: Optional[GeoInfo]) -> Optional[str]:
    """Render a one-line location hint for the system prompt, or None."""
    if not geo:
        return None
    if geo.city:
        return f"{geo.city}, {geo.country}"
    return geo.country
