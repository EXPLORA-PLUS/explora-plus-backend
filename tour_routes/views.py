from __future__ import annotations

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.domain import DETAIL_STATUS_PENDING, ROUTE_STOP_STATE_EXCLUDED, ROUTE_STOP_STATE_VISITED
from places.catalog import upsert_places_from_route_payload, upsert_places_from_route_pois
from places.cities import ensure_cities_in_background
from places.models import Place
from .authentication import OptionalJWTAuthentication
from .models import RouteSearchCache, TourRoute
from .persistence import (
    build_search_cache_key,
    bump_cache_hit,
    clone_response_payload,
    create_or_update_cache,
    create_tour_route,
    update_tour_route_snapshot,
)
from .serializers import (
    SavedTourRouteStopStateSerializer,
    TourRouteRequestSerializer,
    TourRoutePreferencesSerializer,
    UserTourPlaceSerializer,
    UserTourPlaceVisitedSerializer,
    serialize_poi_detail,
    serialize_search_preferences,
    serialize_result,
    serialize_route_model,
    serialize_user_places,
)
from .search_preferences import (
    get_search_preferences_for_user,
    save_search_preferences_for_user,
)
from .services.exceptions import TourRouteError
from .services.poi_details import build_poi_detail_fetcher
from .services.planner import build_default_planner
from .user_places import (
    build_user_place_library,
    ensure_user_place_states_from_route_payload,
    get_latest_tour_route,
    get_visited_stop_ids_for_route_payload,
    set_user_place_visited,
    sync_tour_route_with_user_places,
)


class TourRouteView(APIView):
    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TourRouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        origin_input = serializer.validated_data["origin"]
        destination_input = serializer.validated_data["destination"]
        search_preferences = get_search_preferences_for_user(request.user)
        cache_key, canonical_payload = build_search_cache_key(
            origin_input=origin_input,
            destination_input=destination_input,
            search_preferences=search_preferences.as_dict(),
        )
        cache = RouteSearchCache.objects.filter(cache_key=cache_key).first()

        if cache is None or _should_refresh_cache(cache):
            planner = build_default_planner()
            try:
                result, map_payload = planner.plan(
                    origin_input=origin_input,
                    destination_input=destination_input,
                    search_preferences=search_preferences,
                )
            except TourRouteError as exc:
                return Response({"detail": str(exc)}, status=exc.status_code)

            base_response_payload = serialize_result(result, map_payload, saved_route_id=None)
            places_by_stop_id = upsert_places_from_route_pois(result.places_to_pass)
            ensure_cities_in_background(
                [place.pk for place in places_by_stop_id.values() if not place.city]
            )
            cache = create_or_update_cache(
                cache_key=cache_key,
                canonical_payload=canonical_payload,
                origin_query=_endpoint_query(origin_input),
                destination_query=_endpoint_query(destination_input),
                route_payload=base_response_payload["route"],
                map_payload=base_response_payload["map"],
            )
        else:
            bump_cache_hit(cache)
            base_response_payload = clone_response_payload(cache.route_payload, cache.map_payload)
            upsert_places_from_route_payload(base_response_payload["route"])

        if request.user.is_authenticated:
            visited_stop_ids = get_visited_stop_ids_for_route_payload(
                user=request.user,
                route_payload=base_response_payload["route"],
            )
            current_response_payload = base_response_payload
            if visited_stop_ids:
                planner = build_default_planner()
                try:
                    result, map_payload = planner.rebuild_from_payload(
                        route_payload=base_response_payload["route"],
                        visited_stop_ids=visited_stop_ids,
                    )
                except TourRouteError as exc:
                    return Response({"detail": str(exc)}, status=exc.status_code)
                current_response_payload = serialize_result(
                    result,
                    map_payload,
                    saved_route_id=None,
                )

            route = create_tour_route(
                user=request.user,
                search_cache=cache,
                origin_query=_endpoint_query(origin_input),
                destination_query=_endpoint_query(destination_input),
                base_route_payload=base_response_payload["route"],
                current_route_payload=current_response_payload["route"],
                visited_stop_ids=visited_stop_ids,
            )
            ensure_user_place_states_from_route_payload(
                user=request.user,
                route_payload=base_response_payload["route"],
                route=route,
            )
            return Response(serialize_route_model(route))

        return Response(base_response_payload)


class SavedTourRouteStopDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, route_id: int, stop_id: str):
        route = get_object_or_404(
            TourRoute.objects.select_related("search_cache"),
            id=route_id,
            user=request.user,
        )

        base_route_payload = route.search_cache.route_payload
        all_stop_ids = {
            place.get("stop_id")
            for place in base_route_payload.get("places_to_pass", [])
        }
        if stop_id not in all_stop_ids:
            return Response({"detail": "Parada nao encontrada nesta rota."}, status=404)

        excluded_stop_ids = list(
            route.stops.filter(state=ROUTE_STOP_STATE_EXCLUDED)
            .values_list("place__source_ref", flat=True)
        )
        if stop_id in excluded_stop_ids:
            return Response(serialize_route_model(route))

        excluded_stop_ids.append(stop_id)
        visited_stop_ids = get_visited_stop_ids_for_route_payload(
            user=request.user,
            route_payload=base_route_payload,
        )

        planner = build_default_planner()
        try:
            result, map_payload = planner.rebuild_from_payload(
                route_payload=base_route_payload,
                excluded_stop_ids=excluded_stop_ids,
                visited_stop_ids=visited_stop_ids,
            )
        except TourRouteError as exc:
            return Response({"detail": str(exc)}, status=exc.status_code)

        current_route_payload = serialize_result(
            result,
            map_payload,
            saved_route_id=route.id,
        )["route"]
        update_tour_route_snapshot(
            route=route,
            base_route_payload=base_route_payload,
            current_route_payload=current_route_payload,
            excluded_stop_ids=excluded_stop_ids,
            visited_stop_ids=visited_stop_ids,
        )
        ensure_user_place_states_from_route_payload(
            user=request.user,
            route_payload=base_route_payload,
            route=route,
            touch_existing=False,
        )
        return Response(serialize_route_model(route))


class SavedTourRouteStopStateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, route_id: int, stop_id: str):
        serializer = SavedTourRouteStopStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        route = get_object_or_404(
            TourRoute.objects.select_related("search_cache"),
            id=route_id,
            user=request.user,
        )
        base_route_payload = route.search_cache.route_payload
        all_stop_ids = {
            place.get("stop_id")
            for place in base_route_payload.get("places_to_pass", [])
        }
        if stop_id not in all_stop_ids:
            return Response({"detail": "Parada nao encontrada nesta rota."}, status=404)

        excluded_stop_ids = list(
            route.stops.filter(state=ROUTE_STOP_STATE_EXCLUDED)
            .values_list("place__source_ref", flat=True)
        )
        if stop_id in excluded_stop_ids:
            return Response({"detail": "Parada removida da rota."}, status=404)

        wants_visited = serializer.validated_data["state"] == ROUTE_STOP_STATE_VISITED
        state = set_user_place_visited(
            user=request.user,
            stop_id=stop_id,
            visited=wants_visited,
            route_payload=base_route_payload,
            route=route,
        )
        if state is None:
            return Response({"detail": "Lugar nao encontrado na biblioteca."}, status=404)

        planner = build_default_planner()
        try:
            sync_payload = sync_tour_route_with_user_places(
                route=route,
                planner=planner,
                serialize_result=serialize_result,
            )
        except TourRouteError as exc:
            return Response({"detail": str(exc)}, status=exc.status_code)

        update_tour_route_snapshot(
            route=route,
            base_route_payload=base_route_payload,
            current_route_payload=sync_payload["route_payload"],
            excluded_stop_ids=sync_payload["excluded_stop_ids"],
            visited_stop_ids=sync_payload["visited_stop_ids"],
        )
        return Response(serialize_route_model(route))


class SavedTourRouteFilterPreviewView(APIView):
    """Recalcula a rota salva passando so pelas paradas das categorias pedidas.

    Nao persiste nada: e o que o mapa mostra quando o usuario filtra. Sem
    nenhuma parada na categoria, devolve o caminho direto ate o destino.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, route_id: int):
        route = get_object_or_404(
            TourRoute.objects.select_related("search_cache"),
            id=route_id,
            user=request.user,
        )
        categories = sorted(
            {value for value in request.query_params.get("categories", "").split(",") if value}
        )
        cache_key = f"tour-route-filter:{route.id}:{route.updated_at.timestamp()}:{','.join(categories)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        current_route_payload = serialize_route_model(route)["route"]
        excluded_stop_ids = [
            place["stop_id"]
            for place in current_route_payload.get("places_to_pass", [])
            if place.get("category") not in categories
        ]
        planner = build_default_planner()
        try:
            result, map_payload = planner.rebuild_from_payload(
                route_payload=current_route_payload,
                excluded_stop_ids=excluded_stop_ids,
            )
        except TourRouteError as exc:
            return Response({"detail": str(exc)}, status=exc.status_code)

        payload = serialize_result(result, map_payload, saved_route_id=route.id)
        cache.set(cache_key, payload, timeout=60 * 60)
        return Response(payload)


class TourRoutePoiDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, stop_id: str):
        place = get_object_or_404(
            Place.objects.select_related("category").prefetch_related("images"),
            source_ref=stop_id,
        )
        if _should_fetch_poi_detail(place):
            place = build_poi_detail_fetcher().hydrate(place)
        return Response(serialize_poi_detail(place))


class CurrentTourRouteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        route = get_latest_tour_route(request.user)
        if route is None:
            return Response({"detail": "Nenhuma rota atual salva."}, status=404)
        return Response(serialize_route_model(route))


class UserTourPlaceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = build_user_place_library(user=request.user)
        return Response(serialize_user_places(payload))


class UserTourPlaceVisitedView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, stop_id: str):
        serializer = UserTourPlaceVisitedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        route = get_latest_tour_route(request.user)
        route_payload = route.search_cache.route_payload if route is not None else None
        state = set_user_place_visited(
            user=request.user,
            stop_id=stop_id,
            visited=serializer.validated_data["visited"],
            route_payload=route_payload,
            route=route,
        )
        if state is None:
            return Response({"detail": "Lugar nao encontrado na biblioteca."}, status=404)

        if route is not None:
            all_stop_ids = {
                place.get("stop_id")
                for place in route.search_cache.route_payload.get("places_to_pass", [])
            }
            if stop_id in all_stop_ids:
                planner = build_default_planner()
                try:
                    sync_payload = sync_tour_route_with_user_places(
                        route=route,
                        planner=planner,
                        serialize_result=serialize_result,
                    )
                except TourRouteError as exc:
                    return Response({"detail": str(exc)}, status=exc.status_code)
                update_tour_route_snapshot(
                    route=route,
                    base_route_payload=route.search_cache.route_payload,
                    current_route_payload=sync_payload["route_payload"],
                    excluded_stop_ids=sync_payload["excluded_stop_ids"],
                    visited_stop_ids=sync_payload["visited_stop_ids"],
                )

        payload = build_user_place_library(user=request.user)
        item = next((entry for entry in payload if entry["stop_id"] == stop_id), None)
        if item is None:
            return Response({"detail": "Lugar nao encontrado na biblioteca."}, status=404)
        return Response(UserTourPlaceSerializer(instance=item).data)


class TourRoutePreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        preferences = get_search_preferences_for_user(request.user)
        return Response(serialize_search_preferences(preferences))

    def patch(self, request):
        serializer = TourRoutePreferencesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        preferences = save_search_preferences_for_user(
            request.user,
            include_culture=serializer.validated_data["include_culture"],
            include_park=serializer.validated_data["include_park"],
            include_food=serializer.validated_data["include_food"],
            poi_spacing_m=int(serializer.validated_data["poi_spacing_m"]),
            max_search_radius_m=int(serializer.validated_data["max_search_radius_m"]),
        )
        return Response(serialize_search_preferences(preferences))


def _endpoint_query(endpoint_input: dict) -> str:
    address = endpoint_input.get("address")
    if address:
        return str(address).strip()

    location = endpoint_input["location"]
    return f'{float(location["lat"]):.6f},{float(location["lng"]):.6f}'


def _should_refresh_cache(cache: RouteSearchCache) -> bool:
    route_payload = cache.route_payload or {}
    places = route_payload.get("places_to_pass") or []
    mode = route_payload.get("mode")
    return mode == "direct_fallback" or len(places) == 0


def _should_fetch_poi_detail(place) -> bool:
    if place.is_curated:
        # Conteudo curado (Passaporte) ja vem completo do seed.
        return False
    if place.details_fetched_at is None:
        return True
    if place.detail_status == DETAIL_STATUS_PENDING:
        return True
    return not any(
        [
            place.address,
            place.summary,
            place.primary_image_url,
            place.source_url,
            place.website,
            place.opening_hours,
        ]
    )
