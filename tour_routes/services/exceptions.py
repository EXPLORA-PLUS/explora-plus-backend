class TourRouteError(Exception):
    status_code = 500


class AddressResolutionError(TourRouteError):
    status_code = 400


class RouteProviderError(TourRouteError):
    status_code = 502


class PoiSearchError(TourRouteError):
    status_code = 502


class RouteTooLongError(TourRouteError):
    status_code = 400
