"""Unit tests for deterministic SourceQuorum settlement math.

Run:
    python tests/test_quorum_math.py
    pytest tests/test_quorum_math.py -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib.quorum_math import (  # noqa: E402
    compute_quorum,
    reports_equivalent,
    within_tolerance,
    median,
)


def report(url: str, ok: bool, outcome: str, number=None) -> dict:
    return {
        "url": url,
        "fetch_ok": ok,
        "outcome": outcome,
        "numeric_value": number,
        "excerpt": "ignored",
        "confidence": 80,
    }


class TestBinaryQuorum(unittest.TestCase):
    def test_three_yes_settles(self):
        reports = [
            report("https://a.example/1", True, "YES"),
            report("https://b.example/1", True, "YES"),
            report("https://c.example/1", True, "YES"),
        ]
        result = compute_quorum("BINARY", ["YES", "NO"], 2, 2, 0, reports)
        self.assertEqual(result["status"], "SETTLED")
        self.assertEqual(result["outcome"], "YES")
        self.assertTrue(result["quorum_met"])

    def test_tie_is_unresolved(self):
        reports = [
            report("https://a.example/1", True, "YES"),
            report("https://b.example/1", True, "YES"),
            report("https://c.example/1", True, "NO"),
            report("https://d.example/1", True, "NO"),
        ]
        result = compute_quorum("BINARY", ["YES", "NO"], 2, 2, 0, reports)
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertEqual(result["reason"], "tie")

    def test_coverage_gate(self):
        reports = [
            report("https://a.example/1", True, "YES"),
            report("https://b.example/1", False, "UNRESOLVED"),
            report("https://c.example/1", False, "UNRESOLVED"),
        ]
        result = compute_quorum("BINARY", ["YES", "NO"], 2, 2, 0, reports)
        self.assertEqual(result["reason"], "insufficient_coverage")

    def test_unresolved_extracts_do_not_count(self):
        reports = [
            report("https://a.example/1", True, "UNRESOLVED"),
            report("https://b.example/1", True, "YES"),
            report("https://c.example/1", True, "UNRESOLVED"),
        ]
        result = compute_quorum("BINARY", ["YES", "NO"], 2, 2, 0, reports)
        self.assertEqual(result["reason"], "no_quorum")


class TestEnumQuorum(unittest.TestCase):
    def test_majority_no_tie(self):
        reports = [
            report("https://a.example/1", True, "HOME"),
            report("https://b.example/1", True, "HOME"),
            report("https://c.example/1", True, "AWAY"),
        ]
        result = compute_quorum("ENUM", ["HOME", "AWAY", "DRAW"], 2, 2, 0, reports)
        self.assertEqual(result["outcome"], "HOME")
        self.assertEqual(result["tally"]["HOME"], 2)

    def test_disallowed_outcome_ignored(self):
        reports = [
            report("https://a.example/1", True, "POSTPONED"),
            report("https://b.example/1", True, "POSTPONED"),
            report("https://c.example/1", True, "HOME"),
        ]
        result = compute_quorum("ENUM", ["HOME", "AWAY", "DRAW"], 2, 2, 0, reports)
        self.assertEqual(result["status"], "UNRESOLVED")


class TestNumericQuorum(unittest.TestCase):
    def test_median_band(self):
        reports = [
            report("https://a.example/1", True, "VALUE", 100.0),
            report("https://b.example/1", True, "VALUE", 101.0),
            report("https://c.example/1", True, "VALUE", 99.5),
        ]
        result = compute_quorum("NUMERIC", [], 2, 2, 200, reports)
        self.assertEqual(result["status"], "SETTLED")
        self.assertAlmostEqual(result["numeric_value"], 100.0, places=6)

    def test_outlier_breaks_band(self):
        reports = [
            report("https://a.example/1", True, "VALUE", 10.0),
            report("https://b.example/1", True, "VALUE", 50.0),
            report("https://c.example/1", True, "VALUE", 90.0),
        ]
        result = compute_quorum("NUMERIC", [], 2, 2, 100, reports)
        self.assertEqual(result["reason"], "numeric_dispersion")

    def test_zero_center(self):
        self.assertTrue(within_tolerance(0.0, 0.0, 200))
        self.assertFalse(within_tolerance(1.0, 0.0, 200))

    def test_even_median(self):
        self.assertEqual(median([1.0, 3.0]), 2.0)


class TestEquivalence(unittest.TestCase):
    def test_decision_fields_match_despite_wording(self):
        leader = [
            report("https://a.example/1", True, "YES"),
            report("https://b.example/1", True, "YES"),
        ]
        validator = [
            {
                "url": "https://a.example/1",
                "fetch_ok": True,
                "outcome": "YES",
                "numeric_value": None,
                "excerpt": "different wording",
                "confidence": 40,
            },
            {
                "url": "https://b.example/1",
                "fetch_ok": True,
                "outcome": "true",
                "numeric_value": None,
                "excerpt": "also different",
                "confidence": 99,
            },
        ]
        self.assertTrue(reports_equivalent(leader, validator, "BINARY", 0))

    def test_unresolved_gate(self):
        leader = [report("https://a.example/1", True, "YES")]
        validator = [report("https://a.example/1", True, "UNRESOLVED")]
        self.assertFalse(reports_equivalent(leader, validator, "BINARY", 0))

    def test_url_set_must_match(self):
        leader = [report("https://a.example/1", True, "YES")]
        validator = [report("https://evil.example/1", True, "YES")]
        self.assertFalse(reports_equivalent(leader, validator, "BINARY", 0))

    def test_numeric_tolerance(self):
        leader = [report("https://a.example/1", True, "VALUE", 100.0)]
        validator = [report("https://a.example/1", True, "VALUE", 101.5)]
        self.assertTrue(reports_equivalent(leader, validator, "NUMERIC", 200))
        self.assertFalse(reports_equivalent(leader, validator, "NUMERIC", 50))

    def test_fetch_mismatch_rejects(self):
        leader = [report("https://a.example/1", True, "YES")]
        validator = [report("https://a.example/1", False, "UNRESOLVED")]
        self.assertFalse(reports_equivalent(leader, validator, "BINARY", 0))


if __name__ == "__main__":
    unittest.main()
