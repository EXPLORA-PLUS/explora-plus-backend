from __future__ import annotations

from tour_routes.constants import (
    TOUR_ROUTE_MODE_DIRECT_FALLBACK,
    TOUR_ROUTE_MODE_TOUR,
)
from tour_routes.types import TourRouteResult


class GeoJsonMapBuilder:
    def build(self, result: TourRouteResult) -> dict:
        features = []

        if result.tour_route_path is not None:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [point.lng, point.lat]
                            for point in result.tour_route_path.coordinates
                        ],
                    },
                    "properties": {
                        "kind": "route_tour",
                        "distance_m": result.tour_route_path.distance_m,
                        "duration_s": result.tour_route_path.duration_s,
                        "active": result.mode == TOUR_ROUTE_MODE_TOUR,
                    },
                }
            )

        features.extend(
            [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [point.lng, point.lat]
                            for point in result.direct_route_path.coordinates
                        ],
                    },
                    "properties": {
                        "kind": "route_direct",
                        "distance_m": result.direct_route_path.distance_m,
                        "duration_s": result.direct_route_path.duration_s,
                        "active": result.mode == TOUR_ROUTE_MODE_DIRECT_FALLBACK,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            result.origin.location.lng,
                            result.origin.location.lat,
                        ],
                    },
                    "properties": {
                        "kind": "origin",
                        "label": result.origin.label,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            result.destination.location.lng,
                            result.destination.location.lat,
                        ],
                    },
                    "properties": {
                        "kind": "destination",
                        "label": result.destination.label,
                    },
                },
            ]
        )

        for index, poi in enumerate(result.places_to_pass, start=1):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [poi.location.lng, poi.location.lat],
                    },
                    "properties": {
                        "kind": "stop" if poi.included_in_route else "poi",
                        "stop_id": poi.stop_id,
                        "order": index,
                        "waypoint_order": poi.waypoint_order,
                        "name": poi.name,
                        "category": poi.category,
                        "source": poi.source,
                        "included_in_route": poi.included_in_route,
                        "distance_from_route_m": int(round(poi.distance_from_route_m)),
                        "state": poi.state,
                        "is_sponsored": poi.is_sponsored,
                        "is_event": poi.event_start_at is not None,
                        "event_start_at": poi.event_start_at,
                        "event_end_at": poi.event_end_at,
                    },
                }
            )

        return {
            "type": "FeatureCollection",
            "features": features,
        }
