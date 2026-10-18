"""Find the fuel stations that lie along a route.

All stations are loaded into numpy arrays once per process, so a request never
queries the database. The route is resampled to a point every mile, and each
station near the route's bounding box is matched to its closest route point,
which gives both its distance off the route and its mile marker.
"""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from routing.models import FuelStation

from .optimizer import Candidate

EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE_LAT = 69.0
SAMPLE_SPACING_MILES = 1.0
CHUNK_SIZE = 512


@dataclass(frozen=True)
class StationIndex:
    stations: list
    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray


@lru_cache(maxsize=1)
def get_station_index():
    stations = list(FuelStation.objects.all())
    return StationIndex(
        stations=stations,
        lat=np.array([s.latitude for s in stations], dtype=float),
        lon=np.array([s.longitude for s in stations], dtype=float),
        price=np.array([float(s.price) for s in stations], dtype=float),
    )


@dataclass
class RouteGeometry:
    """The route resampled to roughly one point per mile, with mile markers."""

    lat: np.ndarray
    lon: np.ndarray
    miles: np.ndarray

    def as_lonlat_list(self):
        return [[round(lon, 5), round(lat, 5)] for lat, lon in zip(self.lat.tolist(), self.lon.tolist())]


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def resample_route(coordinates, total_miles):
    """Keep about one point per mile and label each with its distance from the start."""
    points = np.asarray(coordinates, dtype=float)
    lat, lon = points[:, 0], points[:, 1]
    cumulative = np.concatenate([[0.0], np.cumsum(haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:]))])
    if cumulative[-1] > 0:
        # Scale to the routing API's distance so mile markers agree with it.
        cumulative *= total_miles / cumulative[-1]

    targets = np.arange(0.0, cumulative[-1], SAMPLE_SPACING_MILES)
    keep = np.unique(np.append(np.searchsorted(cumulative, targets), len(points) - 1))
    return RouteGeometry(lat=lat[keep], lon=lon[keep], miles=cumulative[keep])


def find_stations_along_route(route, max_detour_miles):
    """Return a Candidate for every station within `max_detour_miles` of the route."""
    index = get_station_index()
    if not index.stations:
        return []

    # Cheap bounding-box filter before measuring distances.
    pad_lat = max_detour_miles / MILES_PER_DEGREE_LAT
    pad_lon = pad_lat / max(np.cos(np.radians(np.abs(route.lat).max())), 0.1)
    in_box = np.flatnonzero(
        (index.lat >= route.lat.min() - pad_lat) & (index.lat <= route.lat.max() + pad_lat)
        & (index.lon >= route.lon.min() - pad_lon) & (index.lon <= route.lon.max() + pad_lon)
    )

    # Equirectangular distance is accurate to well under 1% over a few miles.
    route_x_scale = np.cos(np.radians(route.lat)) * MILES_PER_DEGREE_LAT
    candidates = []
    for start in range(0, len(in_box), CHUNK_SIZE):
        ids = in_box[start:start + CHUNK_SIZE]
        dx = (index.lon[ids, None] - route.lon[None, :]) * route_x_scale[None, :]
        dy = (index.lat[ids, None] - route.lat[None, :]) * MILES_PER_DEGREE_LAT
        dist = np.hypot(dx, dy)
        nearest = dist.argmin(axis=1)
        detour = dist[np.arange(len(ids)), nearest]
        for station_id, point, off_route in zip(ids, nearest, detour):
            if off_route <= max_detour_miles:
                candidates.append(StationOnRoute(
                    mile=float(route.miles[point]),
                    price=float(index.price[station_id]),
                    station=index.stations[station_id],
                    off_route_miles=float(off_route),
                ))
    return candidates


@dataclass(frozen=True)
class StationOnRoute(Candidate):
    off_route_miles: float = 0.0
