from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float

    def as_dict(self) -> dict[str, float]:
        return {"lat": self.lat, "lng": self.lng}


@dataclass(frozen=True)
class ResolvedPoint:
    label: str
    location: GeoPoint


@dataclass(frozen=True)
class RoutePath:
    distance_m: int
    duration_s: int
    coordinates: list[GeoPoint]


@dataclass(frozen=True)
class PoiCandidate:
    name: str
    category: str
    source: str
    location: GeoPoint
    distance_from_route_m: float
    progress_m: float
    priority: int
    osm_type: str | None = None
    osm_id: int | None = None
    wikidata_id: str | None = None
    wikipedia_title: str | None = None
    website: str | None = None
    opening_hours: str | None = None
    address: str | None = None
    raw_tags: dict[str, str] | None = None
    is_sponsored: bool = False
    event_start_at: str | None = None
    event_end_at: str | None = None


@dataclass(frozen=True)
class RoutePoi:
    stop_id: str
    name: str
    category: str
    source: str
    location: GeoPoint
    distance_from_route_m: float
    progress_m: float
    priority: int
    included_in_route: bool
    waypoint_order: int | None
    state: str = "active"
    osm_type: str | None = None
    osm_id: int | None = None
    wikidata_id: str | None = None
    wikipedia_title: str | None = None
    website: str | None = None
    opening_hours: str | None = None
    address: str | None = None
    raw_tags: dict[str, str] | None = None
    # Destaques vindos do banco: parceiro patrocinado e janela de evento (ISO 8601).
    is_sponsored: bool = False
    event_start_at: str | None = None
    event_end_at: str | None = None


@dataclass(frozen=True)
class TourRouteResult:
    origin: ResolvedPoint
    destination: ResolvedPoint
    route_path: RoutePath
    direct_route_path: RoutePath
    tour_route_path: RoutePath | None
    mode: str
    places_to_pass: list[RoutePoi]
