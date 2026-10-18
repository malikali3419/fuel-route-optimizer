import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import FuelStation
from routing.services.places import US_STATES, lookup_city


class Command(BaseCommand):
    help = 'Load fuel stations from the price CSV, placing each one at its city coordinates.'

    def add_arguments(self, parser):
        parser.add_argument('--csv', type=Path, default=settings.FUEL_ROUTE['STATIONS_CSV'])

    def handle(self, *args, **options):
        # The dataset lists some stations several times (different names or
        # prices), so group rows by station ID first.
        rows_by_id = defaultdict(list)
        with open(options['csv'], encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                row = {key: value.strip() for key, value in row.items()}
                if row['State'] in US_STATES:  # drop Canadian provinces
                    rows_by_id[int(row['OPIS Truckstop ID'])].append(row)

        stations, unplaced = [], set()
        for opis_id, rows in rows_by_id.items():
            first = rows[0]
            coords = lookup_city(first['City'], first['State'])
            if coords is None:
                unplaced.add(f"{first['City']}, {first['State']}")
                continue
            prices = [Decimal(row['Retail Price']) for row in rows]
            stations.append(FuelStation(
                opis_id=opis_id,
                name=first['Truckstop Name'],
                address=first['Address'],
                city=first['City'],
                state=first['State'],
                rack_id=int(first['Rack ID']) if first['Rack ID'] else None,
                price=(sum(prices) / len(prices)).quantize(Decimal('0.001')),
                latitude=coords[0],
                longitude=coords[1],
            ))

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f'Loaded {len(stations)} US fuel stations.'))
        if unplaced:
            self.stdout.write(self.style.WARNING(
                f"Skipped stations in {len(unplaced)} cities with unknown coordinates: "
                f"{'; '.join(sorted(unplaced))}"
            ))
