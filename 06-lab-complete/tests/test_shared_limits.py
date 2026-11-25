"""Integration tests against an isolated Redis: races, reconciliation and UTC reset.

Run with TEST_REDIS_URL set. Tests only delete their own random namespace.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import uuid

if os.getenv("TEST_REDIS_URL"):
    os.environ["REDIS_URL"] = os.environ["TEST_REDIS_URL"]

from fastapi import HTTPException
from app.config import settings
from app import cost_guard, rate_limiter
from app.redis_client import r


@unittest.skipUnless(os.getenv("TEST_REDIS_URL"), "Set TEST_REDIS_URL to an isolated Redis")
class SharedLimitsTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(
            settings, environment="test", redis_namespace=f"limits-{uuid.uuid4().hex}",
            rate_limit_per_minute=5,
            daily_budget_usd=Decimal("0.00001"), monthly_budget_usd=Decimal("0.00001"),
        )
        for module in (cost_guard, rate_limiter):
            patcher = patch.object(module, "settings", self.config)
            patcher.start()
            self.addCleanup(patcher.stop)
        r.ping()
        self.addCleanup(self.clean_namespace)

    def clean_namespace(self):
        keys = list(r.scan_iter(f"{self.config.redis_prefix}:*"))
        if keys:
            r.delete(*keys)

    def test_parallel_rate_limit_accepts_exactly_five(self):
        def request(_):
            try:
                rate_limiter.check_rate_limit("parallel-test")
                return 200
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 429)
                self.assertGreaterEqual(int(exc.headers["Retry-After"]), 1)
                return exc.status_code
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(request, range(32)))
        self.assertEqual(results.count(200), 5)
        self.assertEqual(results.count(429), 27)

    def test_parallel_budget_cannot_reserve_more_than_available(self):
        # Each reservation costs 7,500 nanodollars; budget is 10,000.
        def request(_):
            try:
                return cost_guard.check_budget(10, 10)
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 402)
                return None
        with ThreadPoolExecutor(max_workers=16) as pool:
            reservations = list(pool.map(request, range(24)))
        accepted = [reservation for reservation in reservations if reservation]
        self.assertEqual(len(accepted), 1)
        cost_guard.release_reservation(accepted[0])

    def test_settlement_and_release_are_idempotent(self):
        reservation = cost_guard.check_budget(10, 10)
        self.assertEqual(cost_guard.record_cost(2, 2, reservation), 0.0000015)
        cost_guard.record_cost(2, 2, reservation)
        cost_guard.release_reservation(reservation)
        self.assertEqual(r.mget(reservation.keys[:2]), ["1500", "1500"])
        another = cost_guard.check_budget(10, 10)
        cost_guard.release_reservation(another)
        cost_guard.release_reservation(another)
        self.assertEqual(r.mget(reservation.keys[:2]), ["1500", "1500"])

    def test_daily_and_monthly_budgets_roll_over_in_utc(self):
        today = datetime.now(timezone.utc)
        tomorrow = today + timedelta(days=1)
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        cases = [
            (Decimal("0.00001"), Decimal("0.001"), tomorrow),
            (Decimal("0.001"), Decimal("0.00001"), next_month),
        ]
        for daily, monthly, next_period in cases:
            with self.subTest(daily=daily, monthly=monthly):
                config = replace(self.config, daily_budget_usd=daily, monthly_budget_usd=monthly)
                self.clean_namespace()
                with patch.object(cost_guard, "settings", config), patch.object(cost_guard, "datetime") as clock:
                    clock.now.return_value = today
                    first = cost_guard.check_budget(10, 10)
                    cost_guard.record_cost(10, 10, first)
                    with self.assertRaises(HTTPException) as rejected:
                        cost_guard.check_budget(10, 10)
                    self.assertEqual(rejected.exception.status_code, 402)
                    clock.now.return_value = next_period
                    second = cost_guard.check_budget(10, 10)
                    cost_guard.record_cost(10, 10, second)


if __name__ == "__main__":
    unittest.main()
