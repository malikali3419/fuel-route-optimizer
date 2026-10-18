from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services.geocoding import GeocodingError
from .services.optimizer import NoFeasiblePlan
from .services.planner import plan_trip
from .services.routing_client import RoutingError


def _plan(data):
    """Validate input and plan the trip. Returns (payload, HTTP status)."""
    serializer = RouteRequestSerializer(data=data)
    if not serializer.is_valid():
        return {'errors': serializer.errors}, status.HTTP_400_BAD_REQUEST
    params = serializer.validated_data
    try:
        result = plan_trip(params['start'], params['finish'], params.get('stop_cost'))
    except GeocodingError as exc:
        return {'error': str(exc)}, status.HTTP_400_BAD_REQUEST
    except NoFeasiblePlan as exc:
        return {'error': str(exc)}, status.HTTP_422_UNPROCESSABLE_ENTITY
    except RoutingError as exc:
        return {'error': str(exc)}, status.HTTP_502_BAD_GATEWAY
    result['map_url'] = '{}?{}'.format(
        reverse('route-map'),
        urlencode({key: value for key, value in params.items()}),
    )
    return result, status.HTTP_200_OK


class RoutePlanView(APIView):
    """Plan fuel stops for a trip between two US locations.

    GET  /api/route/?start=Dallas, TX&finish=Chicago, IL
    POST /api/route/  {"start": "Dallas, TX", "finish": "Chicago, IL"}
    """

    def get(self, request):
        return self._respond(request, request.query_params)

    def post(self, request):
        return self._respond(request, request.data)

    def _respond(self, request, data):
        payload, status_code = _plan(data)
        if 'map_url' in payload:
            payload['map_url'] = request.build_absolute_uri(payload['map_url'])
        return Response(payload, status=status_code)


def route_map(request):
    """Leaflet map of the route and fuel stops; shows a search form when no trip is given."""
    context = {'start': request.GET.get('start', ''), 'finish': request.GET.get('finish', '')}
    if context['start'] and context['finish']:
        payload, status_code = _plan(request.GET)
        if status_code == status.HTTP_200_OK:
            context['plan'] = payload
        else:
            context['error'] = payload.get('error') or payload['errors']
    return render(request, 'routing/map.html', context)
