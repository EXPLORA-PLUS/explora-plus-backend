from __future__ import annotations

import os
from urllib.error import HTTPError, URLError

from tour_routes.types import GeoPoint, ResolvedPoint, RoutePath

from .exceptions import RouteProviderError
from .http import JsonHttpClient


class OsrmWalkingRouter:
    # O demo publico do OSRM (router.project-osrm.org) so tem perfil de carro e
    # ignora o "foot" da URL; o servidor da FOSSGIS roteia a pe de verdade.
    endpoint = "https://routing.openstreetmap.de/routed-foot"

    def __init__(self, client: JsonHttpClient | None = None):
        self.client = client or JsonHttpClient()
        self.endpoint = os.environ.get("OSRM_ENDPOINT", self.endpoint)

    def route(
        self,
        origin: ResolvedPoint,
        destination: ResolvedPoint,
        *,
        waypoints: list[ResolvedPoint] | None = None,
        error_message: str = "Nao foi possivel calcular a rota principal.",
    ) -> RoutePath:
        route_points = [origin, *(waypoints or []), destination]
        payload = self._fetch_payload(
            service="route",
            route_points=route_points,
            params={
                "overview": "full",
                "geometries": "geojson",
            },
            error_message=error_message,
        )
        routes = payload.get("routes") or []
        if not routes:
            raise RouteProviderError(error_message)

        return self._build_route_path(routes[0])

    def _fetch_payload(
        self,
        *,
        service: str,
        route_points: list[ResolvedPoint],
        params: dict[str, str],
        error_message: str,
    ) -> dict:
        coordinates = ";".join(
            f"{point.location.lng},{point.location.lat}" for point in route_points
        )
        url = f"{self.endpoint}/{service}/v1/foot/{coordinates}"

        try:
            payload = self.client.get_json(url, params=params)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise RouteProviderError(error_message) from exc

        if payload.get("code") != "Ok":
            raise RouteProviderError(error_message)
        return payload

    def _build_route_path(self, route: dict) -> RoutePath:
        geometry = route.get("geometry", {})
        raw_coordinates = geometry.get("coordinates") or []
        if not raw_coordinates:
            raise RouteProviderError("O provedor nao retornou geometria de rota.")

        return RoutePath(
            distance_m=int(round(route.get("distance", 0))),
            duration_s=int(round(route.get("duration", 0))),
            coordinates=[
                GeoPoint(lat=float(lat), lng=float(lng))
                for lng, lat in raw_coordinates
            ],
        )
