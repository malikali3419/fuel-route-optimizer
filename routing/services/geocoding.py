"""Turn a user-supplied location into coordinates.

Most inputs are resolved offline, so they cost no API calls:

* "lat,lon" pairs, e.g. "32.7767,-96.7970"
* "City, ST" names, e.g. "Dallas, TX", via the Census gazetteer

Anything else (a street address, a landmark) falls back to one geocoding call:
OpenRouteService when an API key is configured, otherwise Nominatim.
"""
import re
from dataclasses import dataclass

import requests
from django.conf import settings

from .places import lookup_city

# Generous box around the contiguous US, Alaska and Hawaii.
US_BOUNDS = {'min_lat': 18.0, 'max_lat': 72.0, 'min_lon': -180.0, 'max_lon': -65.0}

COORDS_RE = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$')
CITY_STATE_RE = re.compile(r'^\s*(.+?)\s*,\s*([A-Za-z]{2})(?:\s*,\s*(?:USA?|United States))?\s*$', re.IGNORECASE)


class GeocodingError(Exception):
    pass


@dataclass(frozen=True)
class Location:
    query: str
    label: str
    lat: float
    lon: float
    source: str  # "coordinates", "gazetteer" or the geocoding API used

    @property
    def used_api(self):
        return self.source not in ('coordinates', 'gazetteer')


def in_usa(lat, lon):
    return (US_BOUNDS['min_lat'] <= lat <= US_BOUNDS['max_lat']
            and US_BOUNDS['min_lon'] <= lon <= US_BOUNDS['max_lon'])


def geocode(query):
    query = query.strip()
    location = _from_coordinates(query) or _from_gazetteer(query) or _from_api(query)
    if not in_usa(location.lat, location.lon):
        raise GeocodingError(f'"{query}" is not in the USA.')
    return location


def _from_coordinates(query):
    match = COORDS_RE.match(query)
    if match:
        lat, lon = float(match.group(1)), float(match.group(2))
        return Location(query, f'{lat:.5f}, {lon:.5f}', lat, lon, 'coordinates')
    return None


def _from_gazetteer(query):
    match = CITY_STATE_RE.match(query)
    if match:
        city, state = match.group(1), match.group(2).upper()
        coords = lookup_city(city, state)
        if coords:
            return Location(query, f'{city.title()}, {state}', coords[0], coords[1], 'gazetteer')
    return None


def _from_api(query):
    conf = settings.FUEL_ROUTE
    try:
        if conf['ORS_API_KEY']:
            return _ors_geocode(query, conf)
        return _nominatim_geocode(query, conf)
    except requests.RequestException as exc:
        raise GeocodingError(f'Geocoding service failed for "{query}": {exc}') from exc


def _ors_geocode(query, conf):
    response = requests.get(
        'https://api.openrouteservice.org/geocode/search',
        params={'api_key': conf['ORS_API_KEY'], 'text': query, 'boundary.country': 'US', 'size': 1},
        timeout=conf['HTTP_TIMEOUT_SECONDS'],
    )
    response.raise_for_status()
    features = response.json().get('features')
    if not features:
        raise GeocodingError(f'Could not find "{query}" in the USA.')
    lon, lat = features[0]['geometry']['coordinates']
    return Location(query, features[0]['properties'].get('label', query), lat, lon, 'openrouteservice')


def _nominatim_geocode(query, conf):
    response = requests.get(
        conf['NOMINATIM_URL'],
        params={'q': query, 'countrycodes': 'us', 'format': 'json', 'limit': 1},
        headers={'User-Agent': conf['USER_AGENT']},
        timeout=conf['HTTP_TIMEOUT_SECONDS'],
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise GeocodingError(f'Could not find "{query}" in the USA.')
    return Location(query, results[0]['display_name'], float(results[0]['lat']), float(results[0]['lon']), 'nominatim')
