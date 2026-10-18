from unittest import mock

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from routing.models import FuelStation
from routing.services import routing_client
from routing.services.geocoding import Location
from routing.services.routing_client import Route
from routing.services.station_finder import get_station_index, haversine_miles

START, FINISH = (35.0, -100.0), (35.0, -88.0)


def straight_route(*args):
    lons = np.linspace(START[1], FINISH[1], 500)
    coordinates = [(START[0], lon) for lon in lons]
    distance = float(haversine_miles(START[0], START[1], FINISH[0], FINISH[1]))
    return Route(distance_miles=distance, duration_seconds=distance * 60, coordinates=coordinates, provider='test')


class RoutePlanApiTests(TestCase):
    def setUp(self):
        cache.clear()
        get_station_index.cache_clear()
        self.addCleanup(get_station_index.cache_clear)
        # Stations every ~1.5 degrees of longitude along the route, plus one far away.
        prices = [3.50, 3.20, 3.90, 2.90, 3.60, 3.10, 3.80, 3.30, 3.40]
        for i, price in enumerate(prices):
            FuelStation.objects.create(
                opis_id=i + 1, name=f'Station {i + 1}', address=f'Exit {i}', city='Town', state='OK',
                price=price, latitude=35.0, longitude=-100.0 + i * 1.5,
            )
        FuelStation.objects.create(
            opis_id=99, name='Far away', address='-', city='Elsewhere', state='KS',
            price=1.00, latitude=38.0, longitude=-95.0,
        )
        self.client = APIClient()
        patcher = mock.patch('routing.services.planner.get_route', side_effect=straight_route)
        self.get_route = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **extra):
        body = {'start': '35.0,-100.0', 'finish': '35.0,-88.0', **extra}
        return self.client.post('/api/route/', body, format='json')

    def test_returns_route_stops_and_total_cost(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['route']['geometry']['type'], 'LineString')
        summary = data['fuel_summary']
        self.assertAlmostEqual(summary['total_gallons'], data['route']['distance_miles'] / 10, delta=0.2)
        self.assertAlmostEqual(summary['total_cost_usd'], sum(s['cost_usd'] for s in data['fuel_stops']), delta=0.05)
        self.assertNotIn('Far away', [s['name'] for s in data['fuel_stops']])
        self.assertTrue(data['map_url'].startswith('http://testserver/api/route/map/?'))

    def test_route_is_fetched_once_then_cached(self):
        first = self.post().json()
        second = self.post().json()
        self.assertEqual(self.get_route.call_count, 1)
        self.assertEqual(first['meta']['external_api_calls'], 1)
        self.assertEqual(second['meta']['external_api_calls'], 0)
        self.assertTrue(second['meta']['route_from_cache'])
        self.assertEqual(first['fuel_stops'], second['fuel_stops'])

    def test_zero_stop_cost_is_never_more_expensive(self):
        cheapest = self.post(stop_cost=0).json()['fuel_summary']
        default = self.post().json()['fuel_summary']
        self.assertLessEqual(cheapest['total_cost_usd'], default['total_cost_usd'])
        self.assertGreaterEqual(cheapest['number_of_stops'], default['number_of_stops'])

    def test_get_works_like_post(self):
        response = self.client.get('/api/route/', {'start': '35.0,-100.0', 'finish': '35.0,-88.0'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fuel_summary'], self.post().json()['fuel_summary'])

    def test_missing_field_is_rejected(self):
        response = self.client.post('/api/route/', {'start': 'Dallas, TX'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('finish', response.json()['errors'])

    def test_location_outside_usa_is_rejected(self):
        response = self.post(start='51.5,-0.12')
        self.assertEqual(response.status_code, 400)
        self.get_route.assert_not_called()

    def test_non_us_state_code_is_rejected_without_api_calls(self):
        with mock.patch('routing.services.geocoding.requests.get') as http_get:
            response = self.post(start='Toronto, ON')
        self.assertEqual(response.status_code, 400)
        http_get.assert_not_called()

    def test_gap_longer_than_range_is_unprocessable(self):
        FuelStation.objects.filter(longitude__gt=-97, longitude__lt=-89).delete()
        get_station_index.cache_clear()
        response = self.post()
        self.assertEqual(response.status_code, 422)

    def test_map_page_renders_plan(self):
        response = self.client.get('/api/route/map/', {'start': '35.0,-100.0', 'finish': '35.0,-88.0'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total fuel cost')
        self.assertContains(response, 'plan-data')


class RoutingFallbackTests(TestCase):
    def test_falls_back_to_osrm_when_openrouteservice_fails(self):
        start = Location('a', 'a', 35.0, -100.0, 'coordinates')
        finish = Location('b', 'b', 35.0, -88.0, 'coordinates')
        osrm_route = Route(distance_miles=600, duration_seconds=1, coordinates=[(35, -100), (35, -88)], provider='osrm')
        conf = {**settings.FUEL_ROUTE, 'ORS_API_KEY': 'test-key'}
        with override_settings(FUEL_ROUTE=conf), \
                mock.patch.object(routing_client, '_ors_route', side_effect=requests.Timeout('timed out')), \
                mock.patch.object(routing_client, '_osrm_route', return_value=osrm_route), \
                self.assertLogs('routing', level='WARNING'):
            route = routing_client.get_route(start, finish)
        self.assertEqual(route.provider, 'osrm')
        self.assertEqual(route.api_calls, 2)
