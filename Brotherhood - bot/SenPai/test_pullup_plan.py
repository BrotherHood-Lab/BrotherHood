import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import unittest

from bot import PULLUP_PLAN, find_starting_week, plan_for_week


class PullupPlanTests(unittest.TestCase):
    def test_plan_has_30_weeks_of_5_sets(self):
        self.assertEqual(len(PULLUP_PLAN), 30)
        for week_targets in PULLUP_PLAN:
            self.assertEqual(len(week_targets), 5)

    def test_week_1_targets(self):
        self.assertEqual(PULLUP_PLAN[0], (6, 5, 5, 4, 3))

    def test_week_30_targets(self):
        self.assertEqual(PULLUP_PLAN[29], (26, 15, 14, 14, 13))

    def test_weekly_totals_match_source_table(self):
        totals = [sum(week) for week in PULLUP_PLAN]
        self.assertEqual(totals, [
            23, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52,
            54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 74, 76, 78, 80, 82,
        ])

    def test_plan_for_week_clamps_below_1(self):
        self.assertEqual(plan_for_week(0), PULLUP_PLAN[0])

    def test_plan_for_week_clamps_above_30(self):
        self.assertEqual(plan_for_week(99), PULLUP_PLAN[29])

    def test_find_starting_week_exact_run_of_matches(self):
        # неделя 6 и 7 обе имеют Подход1=10, неделя 8 уже требует 11 —
        # должна выбираться более поздняя из подходящих (7)
        self.assertEqual(find_starting_week(10), 7)

    def test_find_starting_week_below_minimum(self):
        self.assertEqual(find_starting_week(3), 1)

    def test_find_starting_week_above_maximum(self):
        self.assertEqual(find_starting_week(50), 30)


if __name__ == "__main__":
    unittest.main()
