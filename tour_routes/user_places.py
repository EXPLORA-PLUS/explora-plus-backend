from __future__ import annotations

from django.utils import timezone

from core.domain import ROUTE_STOP_STATE_ACTIVE, ROUTE_STOP_STATE_EXCLUDED
from places.catalog import get_place_by_stop_id, upsert_places_from_route_payload
from places.cities import ensure_cities
from places.models import UserPlaceState

from .models import TourRoute


def get_latest_tour_route(user) -> TourRoute | None:
    return (
        TourRoute.objects.select_related("search_cache")
        .filter(user=user)
        .order_by("-created_at", "-id")
        .first()
    )


def ensure_user_place_states_from_route_payload(
    *,
    user,
    route_payload: dict,
    route: TourRoute | None = None,
    touch_existing: bool = True,
) -> list[UserPlaceState]:
    upsert_places_from_route_payload(route_payload)
    states: list[UserPlaceState] = []
    for place_payload in route_payload.get("places_to_pass", []):
        stop_id = place_payload.get("stop_id")
        if not stop_id:
            continue

        place = get_place_by_stop_id(stop_id)
        if place is None:
            continue

        state, created = UserPlaceState.objects.get_or_create(
            user=user,
            place=place,
            defaults={
                "is_visited": bool(place_payload.get("state") == "visited"),
                "visited_at": timezone.now()
                if place_payload.get("state") == "visited"
                else None,
                "seen_count": 1,
                "last_seen_route": route,
            },
        )
        if created:
            states.append(state)
            continue

        if touch_existing:
            state.seen_count += 1
            state.last_seen_route = route
            state.save(update_fields=["seen_count", "last_seen_route", "last_seen_at"])
        states.append(state)
    return states


def get_visited_stop_ids_for_route_payload(*, user, route_payload: dict) -> list[str]:
    stop_ids = [
        place.get("stop_id")
        for place in route_payload.get("places_to_pass", [])
        if place.get("stop_id")
    ]
    if not stop_ids:
        return []
    return list(
        UserPlaceState.objects.filter(
            user=user,
            place__source_ref__in=stop_ids,
            is_visited=True,
        ).values_list("place__source_ref", flat=True)
    )


def set_user_place_visited(
    *,
    user,
    stop_id: str,
    visited: bool,
    route_payload: dict | None = None,
    route: TourRoute | None = None,
) -> UserPlaceState | None:
    if route_payload is not None:
        ensure_user_place_states_from_route_payload(
            user=user,
            route_payload=route_payload,
            route=route,
            touch_existing=False,
        )

    state = (
        UserPlaceState.objects.select_related("place", "place__category")
        .filter(user=user, place__source_ref=stop_id)
        .first()
    )
    if state is None:
        return None

    state.is_visited = visited
    state.visited_at = timezone.now() if visited else None
    if route is not None:
        state.last_seen_route = route
    state.save(update_fields=["is_visited", "visited_at", "last_seen_route", "last_seen_at"])
    return state


def build_user_place_library(*, user) -> list[dict]:
    current_route = get_latest_tour_route(user)
    active_lookup: dict[str, int] = {}
    excluded_ids: set[str] = set()

    if current_route is not None:
        ensure_user_place_states_from_route_payload(
            user=user,
            route_payload=current_route.search_cache.route_payload,
            route=current_route,
            touch_existing=False,
        )
        for stop in current_route.stops.select_related("place").order_by("display_order", "id"):
            stop_id = stop.place.source_ref or stop.place.slug
            if stop.state == ROUTE_STOP_STATE_ACTIVE:
                active_lookup[stop_id] = stop.waypoint_order or stop.display_order
            elif stop.state == ROUTE_STOP_STATE_EXCLUDED:
                excluded_ids.add(stop_id)

    payloads = []
    queryset = (
        UserPlaceState.objects.select_related("place", "place__category")
        .filter(user=user)
        .order_by("-last_seen_at", "-id")
    )
    states = list(queryset)
    # Garante a cidade de todo lugar listado (normalmente ja veio do
    # preenchimento em segundo plano feito ao gerar a rota).
    ensure_cities(state.place for state in states if not state.place.city)
    for state in states:
        stop_id = state.place.source_ref or state.place.slug
        payloads.append(
            {
                "stop_id": stop_id,
                "name": state.place.name,
                "category": state.place.category.slug,
                "image_url": state.place.primary_image_url,
                "address": state.place.address,
                "city": state.place.city,
                "summary": state.place.summary or state.place.description,
                "is_sponsored": state.place.is_sponsored,
                "event_start_at": state.place.event_start_at,
                "event_end_at": state.place.event_end_at,
                "is_visited": state.is_visited,
                "is_in_current_route": stop_id in active_lookup,
                "is_excluded_from_current_route": stop_id in excluded_ids,
                "current_route_order": active_lookup.get(stop_id),
                "last_seen_at": state.last_seen_at,
            }
        )
    return sorted(payloads, key=_library_sort_key)


def sync_tour_route_with_user_places(
    *,
    route: TourRoute,
    planner,
    serialize_result,
) -> dict:
    base_route_payload = route.search_cache.route_payload
    excluded_stop_ids = list(
        route.stops.filter(state=ROUTE_STOP_STATE_EXCLUDED)
        .select_related("place")
        .values_list("place__source_ref", flat=True)
    )
    visited_stop_ids = get_visited_stop_ids_for_route_payload(
        user=route.user,
        route_payload=base_route_payload,
    )
    result, map_payload = planner.rebuild_from_payload(
        route_payload=base_route_payload,
        excluded_stop_ids=excluded_stop_ids,
        visited_stop_ids=visited_stop_ids,
    )
    current_route_payload = serialize_result(
        result,
        map_payload,
        saved_route_id=route.id,
    )["route"]
    return {
        "excluded_stop_ids": excluded_stop_ids,
        "visited_stop_ids": visited_stop_ids,
        "route_payload": current_route_payload,
        "map_payload": map_payload,
    }


def _library_sort_key(item: dict) -> tuple[int, int, float]:
    if item["is_in_current_route"]:
        return (0, int(item["current_route_order"] or 0), 0.0)
    if item["is_excluded_from_current_route"]:
        return (2, 0, -item["last_seen_at"].timestamp())
    return (1, 0, -item["last_seen_at"].timestamp())
