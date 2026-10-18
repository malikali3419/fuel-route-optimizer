import itertools

from django.test import SimpleTestCase

from routing.services.optimizer import Candidate, NoFeasiblePlan, plan_fuel_stops


def brute_force_cost(stations, total_miles, range_miles, mpg, step=50):
    """Cheapest cost by trying every purchase amount (in `step`-mile units) at every station."""
    best = None
    choices = range(0, range_miles + step, step)
    for amounts in itertools.product(choices, repeat=len(stations)):
        # The leg before the first station is paid for at that station.
        fuel, pos, ok = 0, stations[0].mile, True
        cost = stations[0].mile / mpg * stations[0].price
        for station, amount in zip(stations, amounts):
            fuel -= station.mile - pos
            if fuel < 0:
                ok = False
                break
            if fuel + amount > range_miles:
                ok = False
                break
            fuel += amount
            cost += amount / mpg * station.price
            pos = station.mile
        if ok and fuel >= total_miles - pos and (best is None or cost < best):
            best = cost
    return best


class PlanFuelStopsTests(SimpleTestCase):
    def test_short_trip_buys_only_what_is_needed(self):
        plan = plan_fuel_stops([Candidate(0, 3.0)], total_miles=300, range_miles=500, mpg=10)
        self.assertEqual(len(plan.purchases), 1)
        self.assertAlmostEqual(plan.total_gallons, 30)
        self.assertAlmostEqual(plan.total_cost, 90)

    def test_buys_little_before_a_cheaper_station(self):
        stations = [Candidate(0, 4.0), Candidate(100, 3.0)]
        plan = plan_fuel_stops(stations, total_miles=400, range_miles=500, mpg=10)
        gallons = [round(p.gallons, 6) for p in plan.purchases]
        self.assertEqual(gallons, [10, 30])
        self.assertAlmostEqual(plan.total_cost, 10 * 4 + 30 * 3)

    def test_fills_up_when_current_station_is_cheapest(self):
        stations = [Candidate(0, 3.0), Candidate(450, 4.0), Candidate(600, 5.0)]
        plan = plan_fuel_stops(stations, total_miles=900, range_miles=500, mpg=10)
        # Fill 50 gal at $3, then at mile 450 buy just enough to finish (450 mi left, 50 in tank).
        self.assertAlmostEqual(plan.purchases[0].gallons, 50)
        self.assertAlmostEqual(plan.purchases[1].gallons, 40)
        self.assertAlmostEqual(plan.total_gallons, 90)

    def test_total_gallons_always_cover_the_trip(self):
        stations = [Candidate(m, p) for m, p in [(5, 3.5), (200, 3.1), (480, 3.9), (700, 2.9), (950, 3.3)]]
        plan = plan_fuel_stops(stations, total_miles=1200, range_miles=500, mpg=10)
        self.assertAlmostEqual(plan.total_gallons, 120)

    def test_matches_brute_force(self):
        cases = [
            ([(0, 3.0), (150, 2.5), (300, 3.5), (450, 2.0)], 700),
            ([(50, 4.0), (250, 3.0), (500, 3.8), (600, 3.2)], 900),
            ([(0, 3.0), (100, 3.6), (350, 3.4), (550, 3.9), (750, 2.8)], 1100),
            ([(0, 2.0), (200, 5.0), (400, 4.0)], 800),
        ]
        for points, total in cases:
            with self.subTest(points=points):
                stations = [Candidate(m, p) for m, p in points]
                plan = plan_fuel_stops(stations, total_miles=total, range_miles=500, mpg=10)
                expected = brute_force_cost(stations, total, 500, 10)
                self.assertAlmostEqual(plan.total_cost, expected, places=6)

    def test_gap_longer_than_range_is_infeasible(self):
        stations = [Candidate(0, 3.0), Candidate(600, 3.0)]
        with self.assertRaises(NoFeasiblePlan):
            plan_fuel_stops(stations, total_miles=800, range_miles=500, mpg=10)

    def test_no_stations_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan):
            plan_fuel_stops([], total_miles=100, range_miles=500, mpg=10)
