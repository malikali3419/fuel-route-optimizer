from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text='"City, ST", an address, or "lat,lon".')
    finish = serializers.CharField(max_length=200, help_text='"City, ST", an address, or "lat,lon".')
    stop_cost = serializers.FloatField(
        required=False, min_value=0, max_value=1000,
        help_text='Dollar cost charged per fuel stop when planning. 0 gives the absolute cheapest plan.',
    )
