from __future__ import annotations

from rest_framework import serializers

from places.models import Place

from .constants import TOUR_ROUTE_STOP_STATES
from .models import TourRoute
from .search_preferences import TourRouteSearchPreferences
from .services.map_builder import GeoJsonMapBuilder
from .types import GeoPoint, ResolvedPoint, RoutePath, RoutePoi, TourRouteResult


class CoordinateSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class RouteEndpointSerializer(serializers.Serializer):
    address = serializers.CharField(required=False, allow_blank=False)
    location = CoordinateSerializer(required=False)

    def validate(self, attrs):
        has_address = bool(attrs.get("address"))
        has_location = attrs.get("location") is not None

        if has_address == has_location:
            raise serializers.ValidationError(
                "Informe exatamente um entre 'address' e 'location'."
            )
        return attrs


class TourRouteRequestSerializer(serializers.Serializer):
    origin = RouteEndpointSerializer()
    destination = RouteEndpointSerializer()


class ResolvedPointSerializer(serializers.Serializer):
    label = serializers.CharField()
    location = CoordinateSerializer()


class PlaceToPassSerializer(serializers.Serializer):
    stop_id = serializers.CharField()
    order = serializers.IntegerField()
    name = serializers.CharField()
    category = serializers.CharField()
    location = CoordinateSerializer()
    distance_from_route_m = serializers.IntegerField()
    source = serializers.CharField()
    included_in_route = serializers.BooleanField()
    waypoint_order = serializers.IntegerField(allow_null=True)
    state = serializers.ChoiceField(choices=TOUR_ROUTE_STOP_STATES)


class RouteSummarySerializer(serializers.Serializer):
    distance_m = serializers.IntegerField()
    duration_s = serializers.IntegerField()
    polyline_points = CoordinateSerializer(many=True)


class RoutePayloadSerializer(serializers.Serializer):
    saved_route_id = serializers.IntegerField(allow_null=True, required=False)
    mode = serializers.CharField()
    origin = ResolvedPointSerializer()
    destination = ResolvedPointSerializer()
    distance_m = serializers.IntegerField()
    duration_s = serializers.IntegerField()
    polyline_points = CoordinateSerializer(many=True)
    direct_route = RouteSummarySerializer()
    places_to_pass = PlaceToPassSerializer(many=True)


class TourRouteResponseSerializer(serializers.Serializer):
    route = RoutePayloadSerializer()
    map = serializers.JSONField()


class SavedTourRouteStopStateSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=TOUR_ROUTE_STOP_STATES)


class TourRoutePoiDetailSerializer(serializers.Serializer):
    stop_id = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    summary = serializers.CharField(allow_blank=True)
    image_url = serializers.URLField(allow_null=True)
    source_url = serializers.URLField(allow_null=True)
    opening_hours = serializers.CharField(allow_null=True)
    website = serializers.URLField(allow_null=True)


class UserTourPlaceSerializer(serializers.Serializer):
    stop_id = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    image_url = serializers.URLField(allow_null=True)
    address = serializers.CharField(allow_blank=True)
    city = serializers.CharField(allow_blank=True)
    summary = serializers.CharField(allow_blank=True)
    is_visited = serializers.BooleanField()
    is_in_current_route = serializers.BooleanField()
    is_excluded_from_current_route = serializers.BooleanField()
    current_route_order = serializers.IntegerField(allow_null=True)
    last_seen_at = serializers.DateTimeField()


class UserTourPlaceVisitedSerializer(serializers.Serializer):
    visited = serializers.BooleanField()


class TourRoutePreferencesSerializer(serializers.Serializer):
    include_culture = serializers.BooleanField()
    include_park = serializers.BooleanField()
    include_food = serializers.BooleanField()
    poi_spacing_m = serializers.ChoiceField(choices=(75, 100, 150))
    max_search_radius_m = serializers.ChoiceField(choices=(150, 250, 400))

    def validate(self, attrs):
        if not any(
            [
                attrs.get("include_culture"),
                attrs.get("include_park"),
                attrs.get("include_food"),
            ]
        ):
            raise serializers.ValidationError(
                "Ative pelo menos uma categoria para a busca."
            )
        return attrs


def serialize_result(
    result: TourRouteResult,
    map_payload: dict,
    *,
    saved_route_id: int | None = None,
) -> dict:
    payload = {
        "route": {
            "saved_route_id": saved_route_id,
            "origin": {
                "label": result.origin.label,
                "location": result.origin.location.as_dict(),
            },
            "mode": result.mode,
            "destination": {
                "label": result.destination.label,
                "location": result.destination.location.as_dict(),
            },
            "distance_m": result.route_path.distance_m,
            "duration_s": result.route_path.duration_s,
            "polyline_points": [
                point.as_dict() for point in result.route_path.coordinates
            ],
            "direct_route": {
                "distance_m": result.direct_route_path.distance_m,
                "duration_s": result.direct_route_path.duration_s,
                "polyline_points": [
                    point.as_dict() for point in result.direct_route_path.coordinates
                ],
            },
            "places_to_pass": [
                {
                    "stop_id": poi.stop_id,
                    "order": index,
                    "name": poi.name,
                    "category": poi.category,
                    "location": poi.location.as_dict(),
                    "distance_from_route_m": int(round(poi.distance_from_route_m)),
                    "source": poi.source,
                    "included_in_route": poi.included_in_route,
                    "waypoint_order": poi.waypoint_order,
                    "state": poi.state,
                }
                for index, poi in enumerate(result.places_to_pass, start=1)
            ],
        },
        "map": map_payload,
    }
    return TourRouteResponseSerializer(instance=payload).data


def serialize_route_model(route: TourRoute) -> dict:
    result = _result_from_route(route)
    return serialize_result(
        result,
        GeoJsonMapBuilder().build(result),
        saved_route_id=route.id,
    )


def serialize_poi_detail(place: Place) -> dict:
    payload = {
        "stop_id": place.source_ref or place.slug,
        "name": place.name,
        "category": place.category.slug,
        "address": place.address,
        "summary": place.summary or place.description,
        "image_url": place.primary_image_url,
        "source_url": place.source_url or None,
        "opening_hours": place.opening_hours or None,
        "website": place.website or None,
    }
    return TourRoutePoiDetailSerializer(instance=payload).data


def serialize_user_places(items: list[dict]) -> list[dict]:
    return UserTourPlaceSerializer(instance=items, many=True).data


def serialize_search_preferences(preferences: TourRouteSearchPreferences) -> dict:
    return TourRoutePreferencesSerializer(instance=preferences.as_dict()).data


def _result_from_route(route: TourRoute) -> TourRouteResult:
    stops = list(
        route.stops.select_related("place", "place__category")
        .exclude(state="excluded")
        .order_by("display_order", "id")
    )
    direct_route_path = _route_path_from_geometry(
        route.direct_route_geometry,
        distance_m=route.direct_distance_m,
        duration_s=route.direct_duration_s,
    )
    active_route_path = _route_path_from_geometry(
        route.route_geometry or route.direct_route_geometry,
        distance_m=route.distance_m,
        duration_s=route.duration_s,
    )
    tour_route_path = active_route_path if route.mode == "tour" else None
    return TourRouteResult(
        origin=ResolvedPoint(
            label=route.origin_label,
            location=_geo_point_from_geometry(route.origin_location),
        ),
        destination=ResolvedPoint(
            label=route.destination_label,
            location=_geo_point_from_geometry(route.destination_location),
        ),
        route_path=active_route_path,
        direct_route_path=direct_route_path,
        tour_route_path=tour_route_path,
        mode=route.mode,
        places_to_pass=[_poi_from_stop(stop) for stop in stops],
    )


def _route_path_from_geometry(geometry, *, distance_m: int, duration_s: int) -> RoutePath:
    coordinates = []
    if geometry is not None:
        for lng, lat in geometry.coords:
            coordinates.append(GeoPoint(lat=float(lat), lng=float(lng)))
    return RoutePath(
        distance_m=int(distance_m),
        duration_s=int(duration_s),
        coordinates=coordinates,
    )


def _geo_point_from_geometry(point_geometry) -> GeoPoint:
    return GeoPoint(lat=float(point_geometry.y), lng=float(point_geometry.x))


def _poi_from_stop(stop) -> RoutePoi:
    place = stop.place
    return RoutePoi(
        stop_id=place.source_ref or place.slug,
        name=place.name,
        category=place.category.slug,
        source=stop.source or place.source,
        location=_geo_point_from_geometry(place.location),
        distance_from_route_m=float(stop.distance_from_route_m),
        progress_m=0.0,
        priority=0,
        included_in_route=stop.state == "active",
        waypoint_order=stop.waypoint_order if stop.state == "active" else None,
        state=stop.state,
        osm_type=place.osm_type or None,
        osm_id=place.osm_id,
        wikidata_id=place.wikidata_id or None,
        wikipedia_title=place.wikipedia_title or None,
        website=place.website or None,
        opening_hours=place.opening_hours or None,
        address=place.address or None,
        raw_tags=((place.raw_payload or {}).get("tags") or None),
    )
