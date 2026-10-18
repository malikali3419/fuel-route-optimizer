"""Geocode the few station cities missing from the Census gazetteer.

One-off helper: unincorporated postal towns (e.g. "Breezewood, PA") are not in
the gazetteer, so they are looked up once via Nominatim and saved to
data/us_places_extra.csv, which is committed. Respects Nominatim's limit of
one request per second.

    python scripts/geocode_missing_cities.py
"""
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

import requests  # noqa: E402
from django.conf import settings  # noqa: E402

from routing.services.places import US_STATES, lookup_city, normalize_place_name  # noqa: E402


def main():
    conf = settings.FUEL_ROUTE
    with open(conf["STATIONS_CSV"], encoding="utf-8") as fh:
        missing = sorted({
            (row["City"].strip(), row["State"].strip())
            for row in csv.DictReader(fh)
            if row["State"].strip() in US_STATES and not lookup_city(row["City"], row["State"])
        })
    print(f"{len(missing)} cities to geocode")

    found = []
    for city, state in missing:
        response = requests.get(
            conf["NOMINATIM_URL"],
            params={"city": city, "state": state, "country": "USA", "format": "json", "limit": 1},
            headers={"User-Agent": conf["USER_AGENT"]},
            timeout=conf["HTTP_TIMEOUT_SECONDS"],
        )
        response.raise_for_status()
        results = response.json()
        if results:
            found.append([state, normalize_place_name(city), results[0]["lat"], results[0]["lon"]])
        else:
            print(f"  not found: {city}, {state}")
        time.sleep(1.1)

    out = ROOT / "data" / "us_places_extra.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["state", "name", "lat", "lon"])
        writer.writerows(found)
    print(f"Wrote {len(found)} places to {out}")


if __name__ == "__main__":
    main()
