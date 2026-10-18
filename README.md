# Fuel route optimizer

A Django API that takes a start and finish location in the USA and returns:

- the driving route, as GeoJSON and on an interactive map
- where to buy fuel along the way so the trip costs as little as possible
- the total amount spent on fuel

The vehicle has a 500-mile range and gets 10 miles per gallon. Fuel prices come from the provided `fuel-prices-for-be-assessment.csv`.

## Quick start

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add an OpenRouteService key
python manage.py migrate
python manage.py load_stations
python manage.py runserver
```

Then open http://127.0.0.1:8000/ for the map, or call the API:

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Dallas, TX", "finish": "Chicago, IL"}'
```

Run the tests with `python manage.py test`.

## API

### `POST /api/route/` (or `GET` with query parameters)

| Field | Required | Description |
|---|---|---|
| `start` | yes | `"City, ST"`, an address, or `"lat,lon"` |
| `finish` | yes | Same formats as `start` |
| `stop_cost` | no | Dollar cost charged per fuel stop when planning (default `10`). `0` gives the absolute cheapest plan. See [Choosing fuel stops](#choosing-fuel-stops). |

Response (route geometry shortened):

```json
{
  "start":  {"query": "Dallas, TX", "label": "Dallas, TX", "lat": 32.793333, "lon": -96.766513},
  "finish": {"query": "Chicago, IL", "label": "Chicago, IL", "lat": 41.837045, "lon": -87.684939},
  "route": {
    "distance_miles": 961.0,
    "duration_hours": 17.0,
    "provider": "osrm",
    "geometry": {"type": "LineString", "coordinates": [[-96.76651, 32.79333], "..."]}
  },
  "fuel_summary": {
    "total_cost_usd": 281.45,
    "total_gallons": 96.1,
    "number_of_stops": 2,
    "average_price_per_gallon": 2.929,
    "miles_per_gallon": 10,
    "vehicle_range_miles": 500,
    "stop_cost_usd": 10.0
  },
  "fuel_stops": [
    {"stop": 1, "mile": 0.0, "name": "RaceTrac #2626", "address": "I-20 Exit 472", "city": "Dallas", "state": "TX",
     "lat": 32.793333, "lon": -96.766513, "off_route_miles": 0.0,
     "price_per_gallon": 2.864, "gallons": 50.0, "cost_usd": 143.2},
    {"stop": 2, "mile": 483.4, "name": "SHELL", "address": "I-55, EXIT 48", "city": "Osceola", "state": "AR",
     "lat": 35.690217, "lon": -89.988295, "off_route_miles": 3.3,
     "price_per_gallon": 2.999, "gallons": 46.1, "cost_usd": 138.25}
  ],
  "meta": {"external_api_calls": 1, "route_from_cache": false, "stations_near_route": 163, "elapsed_ms": 2009},
  "map_url": "http://127.0.0.1:8000/api/route/map/?start=Dallas%2C+TX&finish=Chicago%2C+IL"
}
```

Errors: `400` for invalid input or a location outside the USA, `422` when part of the route has no station within 500 miles, `502` when the routing service fails.

### `GET /api/route/map/?start=...&finish=...`

An HTML page that draws the route and the numbered fuel stops on an OpenStreetMap map (Leaflet), with the cost breakdown alongside. `map_url` in the API response links here.

## How it works

```
request ──► geocode start/finish ──► 1 routing API call ──► stations near route ──► optimizer ──► response
            (offline for "City, ST"     (cached per trip)     (in-memory numpy)      (dynamic
             and "lat,lon")                                                          programming)
```

### External API calls: one per new trip, zero when repeated

- **Routing:** [OSRM](https://project-osrm.org/) public server by default (no key needed), or [OpenRouteService](https://openrouteservice.org/) truck routing when `ORS_API_KEY` is set. Either returns the whole route geometry and distance in one call. If OpenRouteService fails or times out (8 s), the request falls back to OSRM automatically.
- **Geocoding:** `"City, ST"` and `"lat,lon"` inputs are resolved offline from the US Census Gazetteer, so they cost no API calls. Only other inputs, such as street addresses, use a geocoding call (OpenRouteService or Nominatim). That's three calls at most.
- **Caching:** the geocoded endpoints and the route are cached per trip in a file cache (`.cache/`, kept for 7 days and across restarts), so asking for the same trip again makes no external calls. `meta.external_api_calls` reports the count for each request.
- **Compact geometry:** routes are downloaded as encoded polylines instead of GeoJSON, about a fifth of the size, which saves up to a second on long trips.

### Placing stations on the map

The CSV has addresses like `I-44, EXIT 283 & US-69` but no coordinates. Geocoding about 6,600 highway-exit addresses through a free API would be slow and unreliable, so each station is placed at its **city's coordinates** from the US Census Gazetteer (places and county subdivisions). Truck stops sit on the highways through or next to their town, so this is accurate to within a few miles. The 133 small towns missing from the gazetteer were geocoded once with Nominatim and saved to `data/us_places_extra.csv`.

`load_stations` also:
- drops Canadian stations (USA only)
- merges the ~680 station IDs that appear more than once, using the average of their listed prices
- skips stations in 4 towns that couldn't be located (8 rows)

### Finding stations along the route

All stations are loaded once into numpy arrays, so requests never query the database. The route is resampled to one point per mile. Stations inside the route's bounding box are matched to their nearest route point, giving each one a **mile marker** and a **distance off the route**. Stations more than 5 miles from the route are ignored. This step takes a few milliseconds even coast to coast.

### Choosing fuel stops

`routing/services/optimizer.py` uses dynamic programming. For every station and every possible fuel level on arrival, in whole miles of range, it keeps the cheapest way to get there. At each station the driver either drives past or stops and buys any amount. This is computed with vectorized numpy and takes about 5 ms.

**Why `stop_cost`?** The plan with the lowest fuel cost alone is impractical. Coast to coast it makes 19 stops, some buying under a gallon to save a cent per gallon at the next station. Each stop therefore adds a fixed cost to the plan (default $10, roughly 15 minutes of a driver's time), so the optimizer only stops when the savings are worth it. That cost affects which stops are chosen but is **not** included in `total_cost_usd`. New York to Los Angeles:

| `stop_cost` | Stops | Fuel cost |
|---|---|---|
| 0 | 19 | $861.32 |
| 10 (default) | 8 | $876.10 |

With `stop_cost=0` the result is the exact cheapest plan. The tests check this against a brute-force search.

### Assumptions

- The vehicle starts with just enough fuel to reach the first station on the route, and that fuel is paid for there. It arrives at the destination empty. So `total_gallons` is the trip distance ÷ 10 mpg, and `total_cost_usd` covers fuel for the whole trip.
- A station's price is the average of its prices in the CSV.
- Detours to stations off the route aren't added to the distance; they're at most 5 miles and reported as `off_route_miles`.

## Project layout

```
config/                      Django settings and URLs
routing/
  models.py                  FuelStation
  views.py, serializers.py   API and map views
  services/
    places.py                offline city → coordinates lookup
    geocoding.py             start/finish → coordinates
    routing_client.py        the single routing API call
    station_finder.py        stations along the route (numpy)
    optimizer.py             fuel stop optimizer (dynamic programming)
    planner.py               ties it together, caches routes
  management/commands/load_stations.py
  templates/routing/map.html Leaflet map
  tests/
data/                        fuel prices CSV and city coordinates
scripts/                     one-off scripts that built the city coordinate files
postman_collection.json      example requests
```

## Configuration

Set these in `.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ORS_API_KEY` | empty | Use OpenRouteService for routing and geocoding instead of OSRM and Nominatim |
| `DJANGO_SECRET_KEY` | dev key | Django secret key |
| `DJANGO_DEBUG` | `True` | Debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Allowed hosts |

Vehicle range, mpg, the 5-mile detour limit and the default stop cost are in `FUEL_ROUTE` in `config/settings.py`.
