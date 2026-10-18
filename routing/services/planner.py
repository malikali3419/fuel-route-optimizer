"""Plan a trip: geocode, route, find stations, choose fuel stops.

The geocoded endpoints and the route are cached per (start, finish), so asking
for the same trip again makes no external API calls at all. Station matching
and optimization are re-run each time; together they take a few milliseconds.
"""
import hashlib
import time

import numpy as np
from django.conf import settings
from django.core.cache import cache

from .geocoding import geocode
from .optimizer import plan_fuel_stops
from .routing_client import get_route
from .station_finder import RouteGeometry, find_stations_along_route, resample_route


def plan_trip(start_query, finish_query, stop_cost=None):
    started = time.perf_counter()
    conf = settings.FUEL_ROUTE
    stop_cost = conf['DEFAULT_STOP_COST'] if stop_cost is None else stop_cost

    trip, api_calls, cached = _get_trip(start_query, finish_query)
    geometry = RouteGeometry(lat=np.array(trip['lat']), lon=np.array(trip['lon']), miles=np.array(trip['miles']))
    candidates = find_stations_along_route(geometry, conf['MAX_DETOUR_MILES'])
    plan = plan_fuel_stops(
        candidates,
        total_miles=trip['distance_miles'],
        range_miles=conf['VEHICLE_RANGE_MILES'],
        mpg=conf['MILES_PER_GALLON'],
        stop_penalty=stop_cost,
    )

    return {
        'start': trip['start'],
        'finish': trip['finish'],
        'route': {
            'distance_miles': round(trip['distance_miles'], 1),
            'duration_hours': round(trip['duration_seconds'] / 3600, 1),
            'provider': trip['provider'],
            'geometry': {'type': 'LineString', 'coordinates': geometry.as_lonlat_list()},
        },
        'fuel_summary': {
            'total_cost_usd': round(plan.total_cost, 2),
            'total_gallons': round(plan.total_gallons, 1),
            'number_of_stops': len(plan.purchases),
            'average_price_per_gallon': round(plan.total_cost / plan.total_gallons, 3),
            'miles_per_gallon': conf['MILES_PER_GALLON'],
            'vehicle_range_miles': conf['VEHICLE_RANGE_MILES'],
            'stop_cost_usd': stop_cost,
        },
        'fuel_stops': [_stop_payload(number, purchase) for number, purchase in enumerate(plan.purchases, 1)],
        'meta': {
            'external_api_calls': api_calls,
            'route_from_cache': cached,
            'stations_near_route': len(candidates),
            'elapsed_ms': round((time.perf_counter() - started) * 1000),
        },
    }


def _get_trip(start_query, finish_query):
    """Return (trip data, number of external API calls made, whether it was cached)."""
    key = 'trip:' + hashlib.sha256(
        f'{start_query.strip().lower()}|{finish_query.strip().lower()}'.encode()
    ).hexdigest()
    trip = cache.get(key)
    if trip is not None:
        return trip, 0, True

    start, finish = geocode(start_query), geocode(finish_query)
    route = get_route(start, finish)
    geometry = resample_route(route.coordinates, route.distance_miles)
    trip = {
        'start': _location_payload(start),
        'finish': _location_payload(finish),
        'distance_miles': route.distance_miles,
        'duration_seconds': route.duration_seconds,
        'provider': route.provider,
        'lat': geometry.lat.tolist(),
        'lon': geometry.lon.tolist(),
        'miles': geometry.miles.tolist(),
    }
    cache.set(key, trip)
    return trip, route.api_calls + start.used_api + finish.used_api, False


def _location_payload(location):
    return {'query': location.query, 'label': location.label, 'lat': location.lat, 'lon': location.lon}


def _stop_payload(number, purchase):
    station = purchase.candidate.station
    return {
        'stop': number,
        'mile': round(purchase.candidate.mile, 1),
        'name': station.name,
        'address': station.address,
        'city': station.city,
        'state': station.state,
        'lat': station.latitude,
        'lon': station.longitude,
        'off_route_miles': round(purchase.candidate.off_route_miles, 1),
        'price_per_gallon': round(purchase.candidate.price, 3),
        'gallons': round(purchase.gallons, 1),
        'cost_usd': round(purchase.cost, 2),
    }
