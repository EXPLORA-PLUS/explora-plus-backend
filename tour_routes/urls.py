from django.urls import path

from .views import (
    CurrentTourRouteView,
    SavedTourRouteFilterPreviewView,
    SavedTourRouteStopDeleteView,
    SavedTourRouteStopStateView,
    TourRoutePoiDetailView,
    TourRoutePreferencesView,
    TourRouteView,
    UserTourPlaceListView,
    UserTourPlaceVisitedView,
)

urlpatterns = [
    path("", TourRouteView.as_view(), name="tour-route"),
    path("current/", CurrentTourRouteView.as_view(), name="tour-route-current"),
    path("preferences/", TourRoutePreferencesView.as_view(), name="tour-route-preferences"),
    path("places/", UserTourPlaceListView.as_view(), name="tour-route-places"),
    path("pois/<str:stop_id>/", TourRoutePoiDetailView.as_view(), name="tour-route-poi-detail"),
    path(
        "places/<str:stop_id>/visited/",
        UserTourPlaceVisitedView.as_view(),
        name="tour-route-place-visited",
    ),
    path(
        "saved/<int:route_id>/stops/<str:stop_id>/",
        SavedTourRouteStopDeleteView.as_view(),
        name="saved-tour-route-stop-delete",
    ),
    path(
        "saved/<int:route_id>/filtered/",
        SavedTourRouteFilterPreviewView.as_view(),
        name="saved-tour-route-filter-preview",
    ),
    path(
        "saved/<int:route_id>/stops/<str:stop_id>/state/",
        SavedTourRouteStopStateView.as_view(),
        name="saved-tour-route-stop-state",
    ),
]
