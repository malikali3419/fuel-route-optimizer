from django.db import models


class FuelStation(models.Model):
    """A truck stop from the fuel price dataset, placed on the map by its city."""

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    # Average of the dataset's prices for this station, in USD per gallon.
    price = models.DecimalField(max_digits=6, decimal_places=3)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ['opis_id']

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state}) ${self.price}'
