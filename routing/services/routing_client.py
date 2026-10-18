"""Fetch a driving route with a single call to a free routing API.

OpenRouteService is used when ORS_API_KEY is set; otherwise the public OSRM
server, which needs no key. Both return the full route geometry and distance
in one response. If OpenRouteService is down, the request falls back to OSRM.
"""
import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    pass


@dataclass
class Route:
    distance_miles: float
    duration_seconds: float
    coordinates: list  # [(lat, lon), ...] from start to finish
    provider: str
    api_calls: int = 1


def get_route(start, finish):
    """Return the driving Route between two Locations."""
    conf = settings.FUEL_ROUTE
    failed_calls = 0
    if conf['ORS_API_KEY']:
        try:
            return _ors_route(start, finish, conf)
        except requests.RequestException as exc:
            logger.warning('OpenRouteService failed, falling back to OSRM: %s', exc)
            failed_calls = 1
    try:
        route = _osrm_route(start, finish, conf)
    except requests.RequestException as exc:
        raise RoutingError(f'Routing service failed: {exc}') from exc
    route.api_calls += failed_calls
    return route


def _ors_route(start, finish, conf):
    response = requests.post(
        'https://api.openrouteservice.org/v2/directions/driving-hgv/geojson',
        json={'coordinates': [[start.lon, start.lat], [finish.lon, finish.lat]]},
        headers={'Authorization': conf['ORS_API_KEY']},
        timeout=conf['ORS_TIMEOUT_SECONDS'],
    )
    if response.status_code in (400, 404):
        raise RoutingError(_ors_error_message(response))
    response.raise_for_status()
    feature = response.json()['features'][0]
    summary = feature['properties']['summary']
    return Route(
        distance_miles=summary['distance'] / METERS_PER_MILE,
        duration_seconds=summary['duration'],
        coordinates=[(lat, lon) for lon, lat in feature['geometry']['coordinates']],
        provider='openrouteservice',
    )


def _ors_error_message(response):
    try:
        return response.json()['error']['message']
    except (ValueError, KeyError, TypeError):
        return 'No route found between these locations.'


def _osrm_route(start, finish, conf):
    url = f"{conf['OSRM_BASE_URL']}/route/v1/driving/{start.lon},{start.lat};{finish.lon},{finish.lat}"
    response = requests.get(
        url,
        params={'overview': 'full', 'geometries': 'geojson'},
        headers={'User-Agent': conf['USER_AGENT']},
        timeout=conf['HTTP_TIMEOUT_SECONDS'],
    )
    data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
    if data.get('code') != 'Ok':
        if response.status_code >= 500:
            response.raise_for_status()
        raise RoutingError(data.get('message') or 'No route found between these locations.')
    route = data['routes'][0]
    return Route(
        distance_miles=route['distance'] / METERS_PER_MILE,
        duration_seconds=route['duration'],
        coordinates=[(lat, lon) for lon, lat in route['geometry']['coordinates']],
        provider='osrm',
    )
