"""Offline lookup of US city coordinates.

Backed by data/us_places.csv, which is generated from the US Census Gazetteer
by scripts/build_places.py, and data/us_places_extra.csv for the few towns the
gazetteer lacks (scripts/geocode_missing_cities.py). Used both to place fuel stations on the map and to
geocode "City, ST" inputs without calling an external API.
"""
import csv
import re
from functools import lru_cache

from django.conf import settings

US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN',
    'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH',
    'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT',
    'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
}

_PREFIXES = [
    (re.compile(r'\b(st|ste|saint)\b\.?'), 'saint'),
    (re.compile(r'\b(ft|fort)\b\.?'), 'fort'),
    (re.compile(r'\b(mt|mount)\b\.?'), 'mount'),
]


def normalize_place_name(name):
    """Normalize a city name so "Mc Calla", "McCalla" and "E. St. Louis" style variants match."""
    name = name.lower().strip()
    for pattern, replacement in _PREFIXES:
        name = pattern.sub(replacement, name)
    return re.sub(r'[^a-z0-9]', '', name)


@lru_cache(maxsize=1)
def _places():
    places = {}
    for path in settings.FUEL_ROUTE['PLACES_CSVS']:
        with open(path, encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                places.setdefault((row['state'], row['name']), (float(row['lat']), float(row['lon'])))
    return places


def lookup_city(city, state):
    """Return (lat, lon) for a US city, or None if it isn't in the gazetteer."""
    return _places().get((state.strip().upper(), normalize_place_name(city)))
