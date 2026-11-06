from __future__ import annotations

import hashlib
import unicodedata

from core.domain import PLACE_SOURCE_CURATED
from places.models import Place
from tour_routes.types import GeoPoint, PoiCandidate, RoutePath

from .geometry import haversine_distance_m, project_point_onto_route

# Curados (os mesmos lugares do Explora+ Passaporte) vencem qualquer categoria
# do Overpass na escolha por trecho.
CURATED_PRIORITY = -1
# Pontos do Overpass tao perto de um curado sao o mesmo lugar (ex.: "Bolsa do
# Cafe" x "Museu do Cafe") e saem da lista.
OVERLAP_DISTANCE_M = 60.0


class CuratedPoiSource:
    def search(
        self,
        route_path: RoutePath,
        *,
        enabled_categories: tuple[str, ...],
        max_distance_from_route_m: int,
    ) -> list[PoiCandidate]:
        if not route_path.coordinates or not enabled_categories:
            return []

        candidates: list[PoiCandidate] = []
        places = Place.objects.select_related("category").filter(
            source=PLACE_SOURCE_CURATED,
            is_active=True,
            category__slug__in=enabled_categories,
            event_start_at__isnull=True,
        )
        for place in places:
            point = GeoPoint(lat=place.location.y, lng=place.location.x)
            distance_m, progress_m = project_point_onto_route(point, route_path.coordinates)
            if distance_m > float(max_distance_from_route_m):
                continue
            self._link_stop_id(place, point)
            candidates.append(
                PoiCandidate(
                    name=place.name,
                    category=place.category.slug,
                    source=PLACE_SOURCE_CURATED,
                    location=point,
                    distance_from_route_m=distance_m,
                    progress_m=progress_m,
                    priority=CURATED_PRIORITY,
                    opening_hours=place.opening_hours or None,
                    address=place.address or None,
                )
            )
        return candidates

    def _link_stop_id(self, place: Place, point: GeoPoint) -> None:
        # O planner identifica paradas por um hash de nome/categoria/posicao e
        # faz upsert de Place por source_ref; amarrar o curado a esse hash faz a
        # rota reaproveitar o registro do seed em vez de criar um duplicado.
        stop_id = build_stop_id(name=place.name, category=place.category.slug, location=point)
        if place.source_ref != stop_id:
            Place.objects.filter(pk=place.pk).update(source_ref=stop_id)


def merge_with_curated(
    curated: list[PoiCandidate],
    candidates: list[PoiCandidate],
) -> list[PoiCandidate]:
    if not curated:
        return candidates
    curated_names = {_normalize_name(candidate.name) for candidate in curated}
    kept = [
        candidate
        for candidate in candidates
        if _normalize_name(candidate.name) not in curated_names
        and all(
            haversine_distance_m(candidate.location, item.location) > OVERLAP_DISTANCE_M
            for item in curated
        )
    ]
    return [*curated, *kept]


def build_stop_id(*, name: str, category: str, location: GeoPoint) -> str:
    raw = f"{name.casefold()}|{category}|{location.lat:.6f}|{location.lng:.6f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if char.isalnum())
