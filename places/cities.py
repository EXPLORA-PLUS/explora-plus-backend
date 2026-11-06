from __future__ import annotations

import logging
import threading
import time
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.contrib.gis.measure import D
from django.db import close_old_connections

from places.models import Place
from tour_routes.services.http import JsonHttpClient

logger = logging.getLogger(__name__)

REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
# Um vizinho ja resolvido tao perto quase sempre esta no mesmo municipio; evita
# uma chamada ao Nominatim por POI (uma rota tem dezenas, quase todos colados).
NEIGHBOR_RADIUS_M = 300
# Politica de uso do Nominatim: no maximo 1 requisicao por segundo.
_REVERSE_INTERVAL_S = 1.1
_reverse_lock = threading.Lock()
_last_reverse_at = 0.0

_CITY_KEYS = ("city", "town", "municipality", "village", "county")


def resolve_city(place: Place, *, client: JsonHttpClient | None = None) -> str:
    """Descobre o municipio do lugar: dados ja salvos, vizinho proximo e, por fim,
    geocodificacao reversa da coordenada."""
    raw_payload = place.raw_payload or {}
    tags = raw_payload.get("tags") or {}
    if tags.get("addr:city"):
        return str(tags["addr:city"]).strip()

    nominatim_address = (raw_payload.get("nominatim") or {}).get("address") or {}
    city = _city_from_address(nominatim_address)
    if city:
        return city

    neighbor = (
        Place.objects.exclude(pk=place.pk)
        .exclude(city="")
        .filter(location__distance_lte=(place.location, D(m=NEIGHBOR_RADIUS_M)))
        .values_list("city", flat=True)
        .first()
    )
    if neighbor:
        return neighbor

    return _reverse_geocode_city(place, client=client or JsonHttpClient())


def lookup_enabled() -> bool:
    return getattr(settings, "PLACE_CITY_LOOKUP_ENABLED", True)


def ensure_place_city(place: Place, *, client: JsonHttpClient | None = None) -> str:
    if place.city or not lookup_enabled():
        return place.city
    try:
        city = resolve_city(place, client=client)
    except (HTTPError, URLError, TimeoutError, ValueError):
        logger.warning("Nao foi possivel resolver a cidade de %s", place.pk, exc_info=True)
        return ""
    if city:
        Place.objects.filter(pk=place.pk).update(city=city)
        place.city = city
    return city


def ensure_cities(places, *, client: JsonHttpClient | None = None) -> None:
    client = client or JsonHttpClient()
    for place in places:
        ensure_place_city(place, client=client)


def ensure_cities_in_background(place_ids: list[int]) -> None:
    """Preenche a cidade dos lugares recem-criados sem atrasar a resposta da rota."""
    if not place_ids or not lookup_enabled():
        return

    def run():
        close_old_connections()
        try:
            ensure_cities(Place.objects.filter(pk__in=place_ids, city=""))
        finally:
            close_old_connections()

    threading.Thread(target=run, name="place-city-backfill", daemon=True).start()


def _reverse_geocode_city(place: Place, *, client: JsonHttpClient) -> str:
    global _last_reverse_at
    with _reverse_lock:
        wait_s = _REVERSE_INTERVAL_S - (time.monotonic() - _last_reverse_at)
        if wait_s > 0:
            time.sleep(wait_s)
        try:
            payload = client.get_json(
                REVERSE_URL,
                params={
                    "lat": f"{place.location.y:.6f}",
                    "lon": f"{place.location.x:.6f}",
                    "format": "jsonv2",
                    "zoom": "10",
                    "addressdetails": "1",
                },
                timeout=8.0,
            )
        finally:
            _last_reverse_at = time.monotonic()
    return _city_from_address((payload or {}).get("address") or {})


def _city_from_address(address: dict) -> str:
    for key in _CITY_KEYS:
        value = address.get(key)
        if value:
            return str(value).strip()
    return ""
