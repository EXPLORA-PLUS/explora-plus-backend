from __future__ import annotations

import hashlib
import unicodedata
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core.domain import PLACE_SOURCE_CURATED
from places.models import Place
from tour_routes.types import GeoPoint, PoiCandidate, RoutePath

from .geometry import haversine_distance_m, project_point_onto_route

# Lugares do banco vencem o Overpass na escolha por trecho (menor = melhor):
# patrocinados e eventos acima dos curados (os mesmos do Explora+ Passaporte).
SPONSORED_PRIORITY = -2
EVENT_PRIORITY = -2
CURATED_PRIORITY = -1
# Evento entra na rota se esta acontecendo ou comeca dentro desta janela.
EVENT_LOOKAHEAD = timedelta(hours=3)
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
        now = timezone.now()
        places = (
            Place.objects.select_related("category")
            .filter(
                Q(source=PLACE_SOURCE_CURATED) | Q(is_sponsored=True),
                is_active=True,
                category__slug__in=enabled_categories,
            )
            .filter(
                Q(event_start_at__isnull=True)
                | Q(event_start_at__lte=now + EVENT_LOOKAHEAD, event_end_at__gte=now)
            )
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
                    priority=_priority_for(place),
                    opening_hours=place.opening_hours or None,
                    address=place.address or None,
                    is_sponsored=place.is_sponsored,
                    event_start_at=isoformat_local(place.event_start_at),
                    event_end_at=isoformat_local(place.event_end_at),
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


def latest_highlight_change():
    """Ultimo instante (ate agora) em que os destaques mudaram: um evento entrou
    na janela, terminou ou foi editado, ou um patrocinado foi cadastrado/editado.
    Rotas em cache mais antigas que isso precisam ser recalculadas."""
    now = timezone.now()
    moments = []
    highlights = Place.objects.filter(
        Q(event_start_at__isnull=False) | Q(is_sponsored=True)
    ).values_list("event_start_at", "event_end_at", "updated_at")
    for start_at, end_at, updated_at in highlights:
        moments.append(updated_at)
        if start_at:
            moments.append(start_at - EVENT_LOOKAHEAD)
        if end_at:
            moments.append(end_at)
    past = [moment for moment in moments if moment and moment <= now]
    return max(past) if past else None


def _priority_for(place: Place) -> int:
    if place.is_sponsored:
        return SPONSORED_PRIORITY
    if place.event_start_at is not None:
        return EVENT_PRIORITY
    return CURATED_PRIORITY


def isoformat_local(value) -> str | None:
    # No fuso do projeto (America/Sao_Paulo): "termina 15/12 23:59", nao 16/12 em UTC.
    return timezone.localtime(value).isoformat() if value else None


def build_stop_id(*, name: str, category: str, location: GeoPoint) -> str:
    raw = f"{name.casefold()}|{category}|{location.lat:.6f}|{location.lng:.6f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if char.isalnum())
