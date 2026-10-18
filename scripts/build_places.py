"""Build data/us_places.csv from the US Census Gazetteer files.

One-off helper: the output file is committed, so this only needs to run again
if the gazetteer is refreshed. Download the 2024 "places" and "county
subdivisions" national files from
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html

    python scripts/build_places.py 2024_Gaz_place_national.txt 2024_Gaz_cousubs_national.txt
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from routing.services.places import normalize_place_name  # noqa: E402

# Legal/statistical descriptors the Census appends to place names.
GOVERNMENT_RE = re.compile(
    r"\s+(\(balance\)|consolidated government|metropolitan government|unified government|"
    r"metro government|urban county)$",
    re.IGNORECASE,
)
PLACE_TYPE_RE = re.compile(
    r"\s+(city and borough|municipality|borough|city|town|township|village|plantation|"
    r"CDP|CCD|comunidad|zona urbana|gore|grant|location|purchase)$",
    re.IGNORECASE,
)


def aliases(raw_name):
    """Yield the lookup names a gazetteer entry should be reachable under."""
    name = re.sub(r"^(town|city|village) of ", "", raw_name.strip(), flags=re.IGNORECASE)
    while GOVERNMENT_RE.search(name):  # "Augusta-Richmond County consolidated government (balance)"
        name = GOVERNMENT_RE.sub("", name)
    name = PLACE_TYPE_RE.sub("", name)  # only once: "Oklahoma City city" -> "Oklahoma City"
    yield name
    if "-" in name:  # "Nashville-Davidson" -> "Nashville"
        yield name.split("-")[0]
    if name.lower().endswith(" city"):  # "Boise City" -> "Boise"
        yield name[:-5]


def main(*gazetteer_files):
    places = {}
    # Earlier files win, so pass the "places" file before "county subdivisions".
    for path in gazetteer_files:
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                row = {k.strip(): v.strip() for k, v in row.items()}
                for alias in aliases(row["NAME"]):
                    key = (row["USPS"], normalize_place_name(alias))
                    places.setdefault(key, (row["INTPTLAT"], row["INTPTLONG"]))

    out = ROOT / "data" / "us_places.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["state", "name", "lat", "lon"])
        for (state, name), (lat, lon) in sorted(places.items()):
            writer.writerow([state, name, lat, lon])
    print(f"Wrote {len(places)} places to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
