from __future__ import annotations

from dataclasses import replace

from tour_routes.constants import (
    TOUR_ROUTE_MODE_DIRECT_FALLBACK,
    TOUR_ROUTE_MODE_TOUR,
    TOUR_ROUTE_STOP_STATE_ACTIVE,
    TOUR_ROUTE_STOP_STATE_VISITED,
)
from tour_routes.search_preferences import TourRouteSearchPreferences
from tour_routes.types import GeoPoint, ResolvedPoint, RoutePath, RoutePoi, TourRouteResult

from .curated_pois import CuratedPoiSource, build_stop_id, merge_with_curated
from .exceptions import PoiSearchError, RouteProviderError, RouteTooLongError
from .geocoding import NominatimGeocoder
from .geometry import haversine_distance_m, polyline_distance_m
from .map_builder import GeoJsonMapBuilder
from .poi_search import OverpassPoiSearcher
from .poi_selector import PoiSelector
from .routing import OsrmWalkingRouter

FREE_WALKING_SPEED_MPS = 1.35
# Distancia em linha reta acima da qual nao faz sentido uma rota a pe; evita
# ficar minutos esperando roteamento/POIs de um destino geocodificado longe.
MAX_WALKING_DISTANCE_M = 25_000


class TourRoutePlanner:
    def __init__(
        self,
        *,
        geocoder: NominatimGeocoder | None = None,
        router: OsrmWalkingRouter | None = None,
        poi_searcher: OverpassPoiSearcher | None = None,
        poi_selector: PoiSelector | None = None,
        map_builder: GeoJsonMapBuilder | None = None,
        curated_source: CuratedPoiSource | None = None,
    ):
        self.geocoder = geocoder or NominatimGeocoder()
        self.router = router or OsrmWalkingRouter()
        self.poi_searcher = poi_searcher or OverpassPoiSearcher()
        self.poi_selector = poi_selector or PoiSelector()
        self.map_builder = map_builder or GeoJsonMapBuilder()
        self.curated_source = curated_source or CuratedPoiSource()

    def plan(
        self,
        *,
        origin_input: dict,
        destination_input: dict,
        search_preferences: TourRouteSearchPreferences,
    ):
        origin = self._resolve_endpoint(origin_input)
        destination = self._resolve_endpoint(destination_input)
        straight_distance_m = haversine_distance_m(origin.location, destination.location)
        if straight_distance_m > MAX_WALKING_DISTANCE_M:
            raise RouteTooLongError(
                "Origem e destino estao muito longe para uma rota a pe "
                f"({straight_distance_m / 1000:.0f} km). Confira o destino: "
                f"{destination.label}"
            )
        direct_route_path = self.router.route(origin, destination)

        try:
            poi_candidates = self.poi_searcher.search(
                direct_route_path,
                enabled_categories=search_preferences.enabled_categories,
                max_distance_from_route_m=search_preferences.max_search_radius_m,
            )
        except PoiSearchError:
            poi_candidates = []

        curated_candidates = self.curated_source.search(
            direct_route_path,
            enabled_categories=search_preferences.enabled_categories,
            max_distance_from_route_m=search_preferences.max_search_radius_m,
        )
        poi_candidates = merge_with_curated(curated_candidates, poi_candidates)

        selected_candidates = self.poi_selector.select(
            poi_candidates,
            route_distance_m=direct_route_path.distance_m,
            poi_spacing_m=search_preferences.poi_spacing_m,
        )
        selected_places = [
            self._route_poi_from_candidate(candidate) for candidate in selected_candidates
        ]
        return self._build_result(
            origin=origin,
            destination=destination,
            direct_route_path=direct_route_path,
            places_to_pass=selected_places,
        )

    def rebuild_from_payload(
        self,
        *,
        route_payload: dict,
        excluded_stop_ids: list[str] | None = None,
        visited_stop_ids: list[str] | None = None,
    ):
        excluded_ids = set(excluded_stop_ids or [])
        visited_ids = set(visited_stop_ids or [])
        origin = self._resolved_point_from_payload(route_payload["origin"])
        destination = self._resolved_point_from_payload(route_payload["destination"])
        direct_route_path = self._route_path_from_summary(route_payload["direct_route"])
        places_to_pass = []
        for place_payload in route_payload.get("places_to_pass", []):
            stop_id = place_payload.get("stop_id")
            if stop_id in excluded_ids:
                continue
            place = self._route_poi_from_payload(place_payload)
            if stop_id in visited_ids:
                place = replace(
                    place,
                    state=TOUR_ROUTE_STOP_STATE_VISITED,
                    included_in_route=False,
                    waypoint_order=None,
                )
            places_to_pass.append(place)
        return self._build_result(
            origin=origin,
            destination=destination,
            direct_route_path=direct_route_path,
            places_to_pass=places_to_pass,
        )

    def _build_result(
        self,
        *,
        origin: ResolvedPoint,
        destination: ResolvedPoint,
        direct_route_path: RoutePath,
        places_to_pass: list[RoutePoi],
    ):
        active_places = [
            poi for poi in places_to_pass if poi.state != TOUR_ROUTE_STOP_STATE_VISITED
        ]
        tour_route_path = (
            self._build_free_walk_route(
                origin=origin,
                destination=destination,
                places_to_pass=active_places,
            )
            if active_places
            else None
        )

        route_path = tour_route_path or direct_route_path
        mode = (
            TOUR_ROUTE_MODE_TOUR
            if tour_route_path is not None
            else TOUR_ROUTE_MODE_DIRECT_FALLBACK
        )
        result = TourRouteResult(
            origin=origin,
            destination=destination,
            route_path=route_path,
            direct_route_path=direct_route_path,
            tour_route_path=tour_route_path,
            mode=mode,
            places_to_pass=self._decorate_places_for_response(
                places_to_pass,
                included_in_route=tour_route_path is not None,
            ),
        )
        map_payload = self.map_builder.build(result)
        return result, map_payload

    def _resolve_endpoint(self, endpoint_input: dict) -> ResolvedPoint:
        address = endpoint_input.get("address")
        if address:
            return self.geocoder.resolve(address)

        location = endpoint_input["location"]
        point = GeoPoint(
            lat=float(location["lat"]),
            lng=float(location["lng"]),
        )
        return ResolvedPoint(
            label=f"{point.lat:.6f}, {point.lng:.6f}",
            location=point,
        )

    def _build_free_walk_route(
        self,
        *,
        origin: ResolvedPoint,
        destination: ResolvedPoint,
        places_to_pass: list[RoutePoi],
    ) -> RoutePath:
        # Segue as ruas passando pelas paradas; se o roteador falhar, cai para
        # linhas retas entre os pontos para a rota nao quebrar.
        try:
            return self.router.route(
                origin,
                destination,
                waypoints=[
                    ResolvedPoint(label=place.name, location=place.location)
                    for place in places_to_pass
                ],
                error_message="Nao foi possivel calcular a rota turistica.",
            )
        except RouteProviderError:
            pass

        coordinates = [
            origin.location,
            *(place.location for place in places_to_pass),
            destination.location,
        ]
        distance_m = int(round(polyline_distance_m(coordinates)))
        duration_s = int(round(distance_m / FREE_WALKING_SPEED_MPS)) if distance_m else 0
        return RoutePath(
            distance_m=distance_m,
            duration_s=duration_s,
            coordinates=coordinates,
        )

    def _decorate_places_for_response(
        self,
        places_to_pass: list[RoutePoi],
        *,
        included_in_route: bool,
    ) -> list[RoutePoi]:
        active_places = [
            poi for poi in places_to_pass if poi.state != TOUR_ROUTE_STOP_STATE_VISITED
        ]
        active_lookup = {
            poi.stop_id: poi
            for poi in self._resequence_places(
                active_places,
                included_in_route=included_in_route,
            )
        }
        resequenced: list[RoutePoi] = []
        for poi in places_to_pass:
            if poi.state == TOUR_ROUTE_STOP_STATE_VISITED:
                resequenced.append(
                    replace(
                        poi,
                        included_in_route=False,
                        waypoint_order=None,
                        state=TOUR_ROUTE_STOP_STATE_VISITED,
                    )
                )
                continue
            resequenced.append(active_lookup[poi.stop_id])
        return resequenced

    def _resequence_places(
        self,
        places_to_pass: list[RoutePoi],
        *,
        included_in_route: bool,
    ) -> list[RoutePoi]:
        resequenced: list[RoutePoi] = []
        for index, poi in enumerate(places_to_pass, start=1):
            resequenced.append(
                replace(
                    poi,
                    included_in_route=included_in_route,
                    waypoint_order=index if included_in_route else None,
                    state=TOUR_ROUTE_STOP_STATE_ACTIVE,
                )
            )
        return resequenced

    def _route_poi_from_candidate(self, candidate) -> RoutePoi:
        return RoutePoi(
            stop_id=self._build_stop_id(
                name=candidate.name,
                category=candidate.category,
                location=candidate.location,
            ),
            name=candidate.name,
            category=candidate.category,
            source=candidate.source,
            location=candidate.location,
            distance_from_route_m=candidate.distance_from_route_m,
            progress_m=candidate.progress_m,
            priority=candidate.priority,
            included_in_route=False,
            waypoint_order=None,
            state=TOUR_ROUTE_STOP_STATE_ACTIVE,
            osm_type=candidate.osm_type,
            osm_id=candidate.osm_id,
            wikidata_id=candidate.wikidata_id,
            wikipedia_title=candidate.wikipedia_title,
            website=candidate.website,
            opening_hours=candidate.opening_hours,
            address=candidate.address,
            raw_tags=candidate.raw_tags,
        )

    def _route_poi_from_payload(self, place_payload: dict) -> RoutePoi:
        location = GeoPoint(
            lat=float(place_payload["location"]["lat"]),
            lng=float(place_payload["location"]["lng"]),
        )
        stop_id = place_payload.get("stop_id") or self._build_stop_id(
            name=place_payload["name"],
            category=place_payload["category"],
            location=location,
        )
        return RoutePoi(
            stop_id=stop_id,
            name=place_payload["name"],
            category=place_payload["category"],
            source=place_payload.get("source", "cache"),
            location=location,
            distance_from_route_m=float(place_payload.get("distance_from_route_m", 0)),
            progress_m=float(place_payload.get("progress_m", 0)),
            priority=0,
            included_in_route=bool(place_payload.get("included_in_route")),
            waypoint_order=place_payload.get("waypoint_order"),
            state=place_payload.get("state", TOUR_ROUTE_STOP_STATE_ACTIVE),
        )

    def _resolved_point_from_payload(self, payload: dict) -> ResolvedPoint:
        return ResolvedPoint(
            label=payload["label"],
            location=GeoPoint(
                lat=float(payload["location"]["lat"]),
                lng=float(payload["location"]["lng"]),
            ),
        )

    def _route_path_from_summary(self, summary: dict) -> RoutePath:
        return RoutePath(
            distance_m=int(summary["distance_m"]),
            duration_s=int(summary["duration_s"]),
            coordinates=[
                GeoPoint(lat=float(point["lat"]), lng=float(point["lng"]))
                for point in summary.get("polyline_points", [])
            ],
        )

    def _build_stop_id(
        self,
        *,
        name: str,
        category: str,
        location: GeoPoint,
    ) -> str:
        return build_stop_id(name=name, category=category, location=location)


def build_default_planner() -> TourRoutePlanner:
    return TourRoutePlanner()
