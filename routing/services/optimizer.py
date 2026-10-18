"""Choose where to buy fuel so a trip costs as little as possible.

Dynamic programming over the stations on the route. For each station and each
possible fuel level on arrival (in whole miles of range), it keeps the
cheapest way to get there. At a station the driver either drives past or stops
and buys any amount, and every stop adds a fixed `stop_penalty` in dollars.
The penalty stands for the driver's time: with it at 0 the plan is the
absolute cheapest, but may stop every few miles to save a cent per gallon.

Assumptions: the vehicle starts with just enough fuel to reach the first
station on the route, which is paid for there, and arrives at the destination
empty. So every mile of the trip is paid for at a station along the way.
"""
from dataclasses import dataclass, field

import numpy as np


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


def plan_fuel_stops(candidates, total_miles, range_miles, mpg, stop_penalty=0.0):
    """Return the cheapest FuelPlan for driving `total_miles` past `candidates`."""
    stations = sorted((c for c in candidates if 0 <= c.mile <= total_miles), key=lambda c: c.mile)
    if not stations:
        raise NoFeasiblePlan('No fuel stations were found along this route.')

    tank = int(range_miles)
    positions = [round(s.mile) for s in stations] + [round(total_miles)]
    _check_gaps(positions, tank)

    levels = np.arange(tank + 1)
    # arrival[i][f]: cheapest cost to reach station i with f miles of fuel left.
    arrival = np.full(tank + 1, np.inf)
    arrival[0] = 0.0  # reach the first station empty; that leg is billed there below
    arrivals = []
    for i, station in enumerate(stations):
        arrivals.append(arrival)
        after = _after_buying(arrival, station.price / mpg, stop_penalty)
        hop = positions[i + 1] - positions[i]
        arrival = np.full(tank + 1, np.inf)
        arrival[:tank + 1 - hop] = after[hop:]
    if not np.isfinite(arrival).any():
        raise NoFeasiblePlan('Could not find a way to reach the destination with these stations.')

    # Walk back from the destination to recover how much was bought where.
    bought = [0] * len(stations)
    fuel = int(np.argmin(arrival))
    for i in range(len(stations) - 1, -1, -1):
        fuel += positions[i + 1] - positions[i]  # fuel in the tank when leaving station i
        cost_per_mile = stations[i].price / mpg
        before = arrivals[i]
        options = before[:fuel + 1] - levels[:fuel + 1] * cost_per_mile
        start = int(np.argmin(options))
        if before[fuel] > options[start] + fuel * cost_per_mile + stop_penalty + 1e-9:
            bought[i] = fuel - start
            fuel = start
    bought[0] += positions[0]  # the drive to the first station

    purchases = [Purchase(s, miles / mpg) for s, miles in zip(stations, bought) if miles > 0]
    return FuelPlan(
        purchases=purchases,
        total_gallons=sum(p.gallons for p in purchases),
        total_cost=sum(p.cost for p in purchases),
    )


def _after_buying(arrival, cost_per_mile, stop_penalty):
    """Cheapest cost to leave a station with each fuel level, buying optionally."""
    levels = np.arange(len(arrival))
    # Buying up to level g from level f costs (g - f) * price, so track the
    # running minimum of arrival[f] - f * price.
    best_start = np.minimum.accumulate(arrival - levels * cost_per_mile)
    return np.minimum(arrival, best_start + levels * cost_per_mile + stop_penalty)


def _check_gaps(positions, tank):
    for here, there in zip(positions, positions[1:]):
        if there - here > tank:
            raise NoFeasiblePlan(
                f'No fuel station within {tank} miles after mile {here} of the route.'
            )
