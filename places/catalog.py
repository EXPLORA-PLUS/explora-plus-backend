from __future__ import annotations

from collections.abc import Iterable

from django.contrib.gis.geos import Point
from django.utils.text import slugify

from core.domain import DETAIL_STATUS_PENDING, PLACE_CATEGORY_DEFAULTS, PLACE_SOURCE_OVERPASS

from .models import Place, PlaceCategory, PlaceImage


def get_or_create_place_category(slug: str) -> PlaceCategory:
    defaults = PLACE_CATEGORY_DEFAULTS.get(
        slug,
        {"name": slug.replace("_", " ").title(), "icon_name": "location"},
    )
    category, _ = PlaceCategory.objects.get_or_create(slug=slug, defaults=defaults)
    return category


def upsert_places_from_route_pois(route_pois: Iterable) -> dict[str, Place]:
    places_by_stop_id: dict[str, Place] = {}
    for poi in route_pois:
        place = upsert_place_from_route_poi(poi)
        places_by_stop_id[poi.stop_id] = place
    return places_by_stop_id


def upsert_places_from_route_payload(route_payload: dict) -> dict[str, Place]:
    places_by_stop_id: dict[str, Place] = {}
    for place_payload in route_payload.get("places_to_pass", []):
        stop_id = place_payload.get("stop_id")
        if not stop_id:
            continue
        places_by_stop_id[stop_id] = upsert_place_from_route_payload_entry(place_payload)
    return places_by_stop_id


def upsert_place_from_route_poi(poi) -> Place:
    return _upsert_place(
        source_ref=poi.stop_id,
        name=poi.name,
        category_slug=poi.category,
        lat=poi.location.lat,
        lng=poi.location.lng,
        source=poi.source or PLACE_SOURCE_OVERPASS,
        address=poi.address or "",
        osm_type=poi.osm_type or "",
        osm_id=poi.osm_id,
        wikidata_id=poi.wikidata_id or "",
        wikipedia_title=poi.wikipedia_title or "",
        website=poi.website or "",
        opening_hours=poi.opening_hours or "",
        raw_payload={"tags": poi.raw_tags or {}},
    )


def upsert_place_from_route_payload_entry(place_payload: dict) -> Place:
    location = place_payload.get("location") or {}
    return _upsert_place(
        source_ref=place_payload["stop_id"],
        name=place_payload.get("name", ""),
        category_slug=place_payload.get("category", ""),
        lat=float(location.get("lat", 0.0)),
        lng=float(location.get("lng", 0.0)),
        source=place_payload.get("source", PLACE_SOURCE_OVERPASS),
    )


def get_place_by_stop_id(stop_id: str) -> Place | None:
    return (
        Place.objects.select_related("category")
        .prefetch_related("images")
        .filter(source_ref=stop_id)
        .first()
    )


def ensure_place_primary_image(place: Place, image_url: str | None) -> None:
    normalized = (image_url or "").strip()
    if not normalized:
        return
    if place.images.filter(url=normalized).exists():
        return
    max_order = place.images.order_by("-order").values_list("order", flat=True).first()
    PlaceImage.objects.create(
        place=place,
        url=normalized,
        order=0 if max_order is None else max_order + 1,
    )


def _upsert_place(
    *,
    source_ref: str,
    name: str,
    category_slug: str,
    lat: float,
    lng: float,
    source: str,
    address: str = "",
    osm_type: str = "",
    osm_id: int | None = None,
    wikidata_id: str = "",
    wikipedia_title: str = "",
    website: str = "",
    opening_hours: str = "",
    raw_payload: dict | None = None,
) -> Place:
    category = get_or_create_place_category(category_slug)
    defaults = {
        "slug": _build_external_place_slug(name=name, source_ref=source_ref),
        "category": category,
        "name": name,
        "summary": "",
        "description": "",
        "source": source,
        "location": Point(lng, lat, srid=4326),
        "address": address,
        "opening_hours": opening_hours,
        "osm_type": osm_type,
        "osm_id": osm_id,
        "wikidata_id": wikidata_id,
        "wikipedia_title": wikipedia_title,
        "website": website,
        "detail_status": DETAIL_STATUS_PENDING,
        "raw_payload": raw_payload or {},
        "is_curated": False,
        "is_active": True,
    }
    place, created = Place.objects.get_or_create(source_ref=source_ref, defaults=defaults)
    if created:
        return place

    update_fields: list[str] = []
    for field_name, value in (
        ("category", category),
        ("name", name),
        ("source", source),
        ("location", Point(lng, lat, srid=4326)),
    ):
        if getattr(place, field_name) != value:
            setattr(place, field_name, value)
            update_fields.append(field_name)

    # Identificadores externos so sao sobrescritos quando vierem preenchidos:
    # o upsert a partir do payload salvo nao os carrega e os apagaria.
    for field_name, value in (
        ("osm_type", osm_type),
        ("osm_id", osm_id),
        ("wikidata_id", wikidata_id),
        ("wikipedia_title", wikipedia_title),
        ("address", address),
        ("opening_hours", opening_hours),
        ("website", website),
    ):
        if value and getattr(place, field_name) != value:
            setattr(place, field_name, value)
            update_fields.append(field_name)

    if raw_payload and place.raw_payload != raw_payload:
        place.raw_payload = raw_payload
        update_fields.append("raw_payload")

    if update_fields:
        place.save(update_fields=[*update_fields, "updated_at"])
    return place


def _build_external_place_slug(*, name: str, source_ref: str) -> str:
    base_slug = slugify(name)[:120] or "place"
    suffix = source_ref[-8:]
    return f"{base_slug}-{suffix}"
