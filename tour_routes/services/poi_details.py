from __future__ import annotations

import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from django.utils import timezone

from core.domain import DETAIL_STATUS_COMPLETE, DETAIL_STATUS_ERROR, DETAIL_STATUS_UNAVAILABLE
from places.catalog import ensure_place_primary_image
from places.models import Place

from tour_routes.types import GeoPoint

from .geometry import haversine_distance_m
from .http import JsonHttpClient

NAME_SEARCH_MAX_DISTANCE_M = 3000


class TourRoutePoiDetailFetcher:
    nominatim_lookup_url = "https://nominatim.openstreetmap.org/lookup"
    wikidata_entities_url = "https://www.wikidata.org/w/api.php"
    wikipedia_summary_url = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"

    def __init__(self, client: JsonHttpClient | None = None):
        self.client = client or JsonHttpClient()

    def hydrate(self, place: Place) -> Place:
        raw_payload = dict(place.raw_payload or {})
        address = place.address
        summary = place.summary
        image_url = place.primary_image_url
        source_url = place.source_url or place.website
        website = place.website
        opening_hours = place.opening_hours
        wikipedia_title = place.wikipedia_title
        wikidata_id = place.wikidata_id

        try:
            lookup_payload = self._fetch_lookup_payload(place)
            if lookup_payload:
                raw_payload["nominatim"] = lookup_payload
                address = address or lookup_payload.get("display_name") or ""
                source_url = source_url or self._build_osm_url(place.osm_type, place.osm_id)
                extratags = lookup_payload.get("extratags") or {}
                website = website or extratags.get("website") or extratags.get("contact:website")
                opening_hours = opening_hours or extratags.get("opening_hours")
                wikipedia_title = wikipedia_title or self._normalize_wikipedia_title(
                    extratags.get("wikipedia")
                )
                wikidata_id = wikidata_id or extratags.get("wikidata")

            wikidata_payload = self._fetch_wikidata_payload(wikidata_id)
            if wikidata_payload:
                raw_payload["wikidata"] = wikidata_payload
                wikipedia_title = wikipedia_title or self._pick_wikipedia_title(
                    wikidata_payload
                )
                image_url = image_url or self._build_wikidata_image_url(wikidata_payload)

            # Busca por nome so para pontos culturais/parques: restaurantes e cafes
            # quase nunca tem artigo proprio e o primeiro resultado vira lixo.
            found_by_name = False
            if not wikipedia_title and place.category.slug != "food":
                wikipedia_title = self._search_wikipedia_by_name(place.name)
                found_by_name = wikipedia_title is not None

            summary_payload = self._fetch_wikipedia_summary(wikipedia_title)
            if found_by_name and not _summary_is_near_place(summary_payload, place):
                summary_payload = None
                wikipedia_title = None
            if summary_payload:
                raw_payload["wikipedia_summary"] = summary_payload
                summary = summary or summary_payload.get("extract") or ""
                image_url = image_url or self._extract_summary_image(summary_payload)
                source_url = source_url or self._extract_summary_source_url(summary_payload)

            place.address = address or ""
            place.summary = summary or ""
            place.source_url = source_url or ""
            place.website = website or ""
            place.opening_hours = opening_hours or ""
            place.wikipedia_title = wikipedia_title or ""
            place.wikidata_id = wikidata_id or ""
            place.raw_payload = raw_payload
            place.detail_status = (
                DETAIL_STATUS_COMPLETE
                if any(
                    [
                        place.address,
                        place.summary,
                        image_url,
                        place.source_url,
                        place.website,
                        place.opening_hours,
                    ]
                )
                else DETAIL_STATUS_UNAVAILABLE
            )
            ensure_place_primary_image(place, image_url)
        except (HTTPError, URLError, TimeoutError, ValueError):
            place.detail_status = DETAIL_STATUS_ERROR
        finally:
            place.details_fetched_at = timezone.now()
            place.save(
                update_fields=[
                    "address",
                    "summary",
                    "source_url",
                    "website",
                    "opening_hours",
                    "wikipedia_title",
                    "wikidata_id",
                    "detail_status",
                    "raw_payload",
                    "details_fetched_at",
                    "updated_at",
                ]
            )

        return place

    def _fetch_lookup_payload(self, place: Place) -> dict | None:
        if not place.osm_type or place.osm_id is None:
            return None

        osm_prefix = self._osm_lookup_prefix(place.osm_type)
        if osm_prefix is None:
            return None

        payload = self.client.get_json(
            self.nominatim_lookup_url,
            params={
                "format": "jsonv2",
                "addressdetails": "1",
                "extratags": "1",
                "namedetails": "1",
                "osm_ids": f"{osm_prefix}{place.osm_id}",
            },
            timeout=12.0,
        )
        if isinstance(payload, list) and payload:
            return payload[0]
        return None

    def _fetch_wikidata_payload(self, wikidata_id: str | None) -> dict | None:
        if not wikidata_id:
            return None

        payload = self.client.get_json(
            self.wikidata_entities_url,
            params={
                "action": "wbgetentities",
                "ids": wikidata_id,
                "format": "json",
                "props": "sitelinks|claims",
                "origin": "*",
            },
            timeout=12.0,
        )
        entity = (payload.get("entities") or {}).get(wikidata_id)
        if isinstance(entity, dict):
            return entity
        return None

    def _fetch_wikipedia_summary(self, wikipedia_title: str | None) -> dict | None:
        if not wikipedia_title:
            return None
        lang, title = self._split_wikipedia_title(wikipedia_title)
        if not title:
            return None
        return self.client.get_json(
            self.wikipedia_summary_url.format(lang=lang, title=quote(title)),
            timeout=12.0,
        )

    def _search_wikipedia_by_name(self, name: str) -> str | None:
        for lang in ("pt", "en"):
            try:
                payload = self.client.get_json(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": name,
                        "format": "json",
                        "srlimit": "1",
                    },
                    timeout=8.0,
                )
                results = (payload.get("query") or {}).get("search") or []
                if results:
                    title = results[0].get("title")
                    if title and _titles_match(name, title):
                        return f"{lang}:{title}"
            except (HTTPError, URLError, TimeoutError, ValueError):
                continue
        return None

    def _pick_wikipedia_title(self, wikidata_payload: dict) -> str | None:
        sitelinks = wikidata_payload.get("sitelinks") or {}
        for key in ("ptwiki", "enwiki"):
            entry = sitelinks.get(key)
            if entry and entry.get("title"):
                lang = key.removesuffix("wiki")
                return f"{lang}:{entry['title']}"
        return None

    def _build_wikidata_image_url(self, wikidata_payload: dict) -> str | None:
        claims = wikidata_payload.get("claims") or {}
        image_claims = claims.get("P18") or []
        if not image_claims:
            return None
        filename = image_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
        if not filename:
            return None
        return (
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            f"{quote(str(filename))}?width=1200"
        )

    def _extract_summary_image(self, summary_payload: dict) -> str | None:
        thumbnail = summary_payload.get("thumbnail") or {}
        original = summary_payload.get("originalimage") or {}
        return original.get("source") or thumbnail.get("source")

    def _extract_summary_source_url(self, summary_payload: dict) -> str | None:
        content_urls = summary_payload.get("content_urls") or {}
        desktop = content_urls.get("desktop") or {}
        mobile = content_urls.get("mobile") or {}
        return desktop.get("page") or mobile.get("page")

    def _build_osm_url(self, osm_type: str | None, osm_id: int | None) -> str | None:
        if not osm_type or osm_id is None:
            return None
        return f"https://www.openstreetmap.org/{osm_type}/{osm_id}"

    def _normalize_wikipedia_title(self, wikipedia_title: str | None) -> str | None:
        if not wikipedia_title:
            return None
        normalized = wikipedia_title.strip()
        return normalized or None

    def _split_wikipedia_title(self, wikipedia_title: str) -> tuple[str, str]:
        if ":" not in wikipedia_title:
            return "pt", wikipedia_title.strip().replace(" ", "_")
        lang, title = wikipedia_title.split(":", 1)
        return lang.strip() or "pt", title.strip().replace(" ", "_")

    def _osm_lookup_prefix(self, osm_type: str) -> str | None:
        normalized = osm_type.casefold()
        if normalized == "node":
            return "N"
        if normalized == "way":
            return "W"
        if normalized == "relation":
            return "R"
        return None


def build_poi_detail_fetcher() -> TourRoutePoiDetailFetcher:
    return TourRoutePoiDetailFetcher()


def _normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join("".join(c if c.isalnum() else " " for c in without_accents).split())


def _titles_match(name: str, title: str) -> bool:
    # Aceita o artigo so quando o titulo e o proprio nome do lugar (com ou sem
    # complemento, ex.: "Japan House" -> "Japan House Sao Paulo").
    normalized_name = _normalize_name(name)
    normalized_title = _normalize_name(title.split(" (")[0])
    if not normalized_name or not normalized_title:
        return False
    if normalized_title.startswith(normalized_name):
        return True
    return normalized_name.startswith(normalized_title) and (
        len(normalized_title) >= 0.8 * len(normalized_name)
    )


def _summary_is_near_place(summary_payload: dict | None, place: Place) -> bool:
    # Artigo achado so pelo nome precisa ser deste lugar: sem coordenadas
    # (pessoa, conceito) ou longe demais (homonimo em outra cidade) e descartado.
    if not summary_payload or summary_payload.get("type") == "disambiguation":
        return False
    coordinates = summary_payload.get("coordinates") or {}
    if "lat" not in coordinates or "lon" not in coordinates or place.location is None:
        return False
    distance_m = haversine_distance_m(
        GeoPoint(lat=float(coordinates["lat"]), lng=float(coordinates["lon"])),
        GeoPoint(lat=place.location.y, lng=place.location.x),
    )
    return distance_m <= NAME_SEARCH_MAX_DISTANCE_M
