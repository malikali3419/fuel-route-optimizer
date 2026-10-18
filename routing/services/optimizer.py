"""Choose where to buy fuel so a trip costs as little as possible.

This is the classic "gas station problem", solved greedily:

* At a station, look ahead one full tank. If there is a cheaper station in
  range (or the destination), buy only enough fuel to reach it.
* Otherwise fill the tank here, since nothing ahead is cheaper, and drive to
  the cheapest station in range.

Assumptions: the vehicle starts with just enough fuel to reach the first
station on the route and arrives at the destination empty, so every mile of
the trip is paid for at a station along the way.
"""
from dataclasses import dataclass, field


class NoFeasiblePlan(Exception):
    """Raised when a stretch of the route has no station within the vehicle's range."""


@dataclass(frozen=True)
class Candidate:
    """A station on the route, at `mile` miles from the start."""

    mile: float
    price: float
    station: object = field(default=None, compare=False)


@dataclass
class Purchase:
    candidate: Candidate
    gallons: float

    @property
    def cost(self):
        return self.gallons * self.candidate.price


@dataclass
class FuelPlan:
    purchases: list
    total_gallons: float
    total_cost: float


def plan_fuel_stops(candidates, total_miles, range_miles, mpg):
    """Return the cheapest FuelPlan for driving `total_miles` past `candidates`."""
    stations = sorted((c for c in candidates if 0 <= c.mile <= total_miles), key=lambda c: c.mile)
    if not stations:
        raise NoFeasiblePlan('No fuel stations were found along this route.')

    purchases = {}  # station index -> miles of fuel bought there

    def buy(index, miles):
        if miles > 1e-9:
            purchases[index] = purchases.get(index, 0.0) + miles

    # The drive to the first station is paid for there, as if the tank was topped up.
    buy(0, stations[0].mile)
    i, fuel = 0, 0.0  # fuel is measured in miles of driving left in the tank
    while True:
        here = stations[i]
        reach = here.mile + range_miles

        cheaper = next(
            (j for j in range(i + 1, len(stations))
             if stations[j].mile <= reach and stations[j].price < here.price),
            None,
        )
        if cheaper is None and total_miles <= reach:
            # Nothing cheaper before the destination: buy exactly what is left.
            buy(i, total_miles - here.mile - fuel)
            break
        if cheaper is not None:
            needed = stations[cheaper].mile - here.mile
            buy(i, max(0.0, needed - fuel))
            fuel = max(fuel, needed) - needed
            i = cheaper
            continue

        in_range = [j for j in range(i + 1, len(stations)) if stations[j].mile <= reach]
        if not in_range:
            raise NoFeasiblePlan(
                f'No fuel station within {range_miles:g} miles after mile {here.mile:.0f} of the route.'
            )
        buy(i, range_miles - fuel)
        nxt = min(in_range, key=lambda j: (stations[j].price, stations[j].mile))
        fuel = range_miles - (stations[nxt].mile - here.mile)
        i = nxt

    result = [Purchase(stations[idx], miles / mpg) for idx, miles in sorted(purchases.items())]
    return FuelPlan(
        purchases=result,
        total_gallons=sum(p.gallons for p in result),
        total_cost=sum(p.cost for p in result),
    )
