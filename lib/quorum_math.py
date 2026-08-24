"""
SourceQuorum settlement math — deterministic, consensus-free.

This module is the same algorithm the Intelligent Contract runs *after*
validators have already agreed on per-source extracts. Keeping it here lets
builders and reviewers unit-test the primitive without GenVM.

The LLM is used only to extract structured facts from each source.
Quorum, ties, coverage, and numeric bands are computed here.

NUMERIC payouts do not store a raw leader median. The settled number is
canonicalized to integer ticks (4 decimal places) and that tick is a
consensus decision field. Two validator-compatible extract sets that
would pay different QuorumBond payees cannot both be accepted.
"""

from __future__ import annotations

from typing import Any

UNRESOLVED = "UNRESOLVED"
SETTLED = "SETTLED"

BINARY_OUTCOMES = ("YES", "NO")
CLAIM_TYPES = ("BINARY", "ENUM", "NUMERIC")
# 4 decimal places. 100.00 and 100.01 are distinct payout buckets.
NUMERIC_SCALE = 10000


def normalize_outcome(raw: Any, claim_type: str, allowed: list[str]) -> str:
    if raw is None:
        return UNRESOLVED
    text = str(raw).strip().upper()
    aliases = {
        "TRUE": "YES",
        "Y": "YES",
        "SUPPORT": "YES",
        "SUPPORTED": "YES",
        "FALSE": "NO",
        "N": "NO",
        "REJECT": "NO",
        "REJECTED": "NO",
        "CONTESTED": "NO",
        "UNKNOWN": UNRESOLVED,
        "UNDETERMINED": UNRESOLVED,
        "INSUFFICIENT": UNRESOLVED,
        "INSUFFICIENT_EVIDENCE": UNRESOLVED,
        "NONE": UNRESOLVED,
        "": UNRESOLVED,
    }
    text = aliases.get(text, text)
    if claim_type == "BINARY":
        return text if text in BINARY_OUTCOMES else UNRESOLVED
    if claim_type == "ENUM":
        allowed_u = [a.strip().upper() for a in allowed]
        return text if text in allowed_u else UNRESOLVED
    if claim_type == "NUMERIC":
        return "VALUE" if text not in (UNRESOLVED, "") else UNRESOLVED
    return UNRESOLVED


def parse_number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median of empty list")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def within_tolerance(value: float, center: float, tolerance_bps: int) -> bool:
    if tolerance_bps < 0:
        return False
    if center == 0.0:
        return value == 0.0
    return abs(value - center) / abs(center) <= (tolerance_bps / 10000.0)


def canonicalize_numeric(value: Any) -> int | None:
    """Snap a float to integer ticks (4 d.p.). None stays None."""
    number = parse_number(value)
    if number is None:
        return None
    scaled = number * NUMERIC_SCALE
    if scaled >= 0:
        return int(scaled + 0.5)
    return int(scaled - 0.5)


def ticks_to_display(ticks: int | None) -> str | None:
    if ticks is None:
        return None
    ticks = int(ticks)
    sign = "-" if ticks < 0 else ""
    t = abs(ticks)
    whole = t // NUMERIC_SCALE
    frac = t % NUMERIC_SCALE
    return f"{sign}{whole}.{frac:04d}"


def compute_quorum(
    claim_type: str,
    allowed_outcomes: list[str],
    min_quorum: int,
    min_coverage: int,
    tolerance_bps: int,
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Derive a settlement from independently extracted source reports.

    reports: [{url, fetch_ok, outcome, numeric_value, ...}, ...]
    """
    claim_type = (claim_type or "").strip().upper()
    allowed = [a.strip().upper() for a in allowed_outcomes if str(a).strip()]
    min_quorum = int(min_quorum)
    min_coverage = int(min_coverage)
    tolerance_bps = int(tolerance_bps)

    if claim_type not in CLAIM_TYPES:
        return _fail("invalid_claim_type", reports, {})
    if min_quorum < 2:
        return _fail("min_quorum_below_2", reports, {})
    if min_coverage < min_quorum:
        return _fail("min_coverage_below_quorum", reports, {})

    fetched = [r for r in reports if bool(r.get("fetch_ok"))]
    coverage = len(fetched)
    if coverage < min_coverage:
        return _fail("insufficient_coverage", reports, {}, coverage=coverage)

    if claim_type == "NUMERIC":
        return _numeric_quorum(fetched, reports, min_quorum, tolerance_bps, coverage)
    return _categorical_quorum(claim_type, allowed, fetched, reports, min_quorum, coverage)


def _categorical_quorum(
    claim_type: str,
    allowed: list[str],
    fetched: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    min_quorum: int,
    coverage: int,
) -> dict[str, Any]:
    tally: dict[str, int] = {}
    usable = 0
    for report in fetched:
        outcome = normalize_outcome(report.get("outcome"), claim_type, allowed)
        if outcome == UNRESOLVED:
            continue
        tally[outcome] = tally.get(outcome, 0) + 1
        usable += 1

    if usable < min_quorum or not tally:
        return _fail("no_quorum", reports, tally, coverage=coverage)

    ranked = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
    winner, win_count = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if win_count < min_quorum:
        return _fail("no_quorum", reports, tally, coverage=coverage)
    if win_count == second:
        return _fail("tie", reports, tally, coverage=coverage)

    return {
        "status": SETTLED,
        "outcome": winner,
        "numeric_value": None,
        "numeric_ticks": None,
        "reason": "quorum",
        "coverage": coverage,
        "usable": usable,
        "tally": tally,
        "quorum_met": True,
    }


def _numeric_quorum(
    fetched: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    min_quorum: int,
    tolerance_bps: int,
    coverage: int,
) -> dict[str, Any]:
    values: list[float] = []
    for report in fetched:
        if normalize_outcome(report.get("outcome"), "NUMERIC", []) == UNRESOLVED:
            continue
        number = parse_number(report.get("numeric_value"))
        if number is None:
            continue
        values.append(number)

    tally = {"VALUE": len(values), UNRESOLVED: coverage - len(values)}
    if len(values) < min_quorum:
        return _fail("no_quorum", reports, tally, coverage=coverage)

    center = median(values)
    band = [v for v in values if within_tolerance(v, center, tolerance_bps)]
    if len(band) < min_quorum:
        return _fail("numeric_dispersion", reports, tally, coverage=coverage)

    settled_value = median(band)
    ticks = canonicalize_numeric(settled_value)
    return {
        "status": SETTLED,
        "outcome": "VALUE",
        "numeric_value": ticks_to_display(ticks),
        "numeric_ticks": ticks,
        "reason": "numeric_band",
        "coverage": coverage,
        "usable": len(band),
        "tally": {"in_band": len(band), "extracted": len(values)},
        "quorum_met": True,
    }


def _fail(
    reason: str,
    reports: list[dict[str, Any]],
    tally: dict[str, Any],
    coverage: int | None = None,
) -> dict[str, Any]:
    if coverage is None:
        coverage = len([r for r in reports if bool(r.get("fetch_ok"))])
    return {
        "status": UNRESOLVED,
        "outcome": UNRESOLVED,
        "numeric_value": None,
        "numeric_ticks": None,
        "reason": reason,
        "coverage": coverage,
        "usable": 0,
        "tally": tally,
        "quorum_met": False,
    }


def reports_equivalent(
    leader_reports: list[dict[str, Any]],
    validator_reports: list[dict[str, Any]],
    claim_type: str,
    tolerance_bps: int,
) -> bool:
    """
    Validator comparison used conceptually by the contract.

    Decision fields must match. Excerpts and confidence are not compared.
    A gate applies: UNRESOLVED vs a concrete outcome is never equivalent.
    """
    if not isinstance(leader_reports, list) or not isinstance(validator_reports, list):
        return False
    if len(leader_reports) != len(validator_reports):
        return False

    def by_url(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        mapped = {}
        for row in rows:
            url = str(row.get("url", "")).strip()
            if not url or url in mapped:
                return {}
            mapped[url] = row
        return mapped

    left = by_url(leader_reports)
    right = by_url(validator_reports)
    if not left or set(left) != set(right):
        return False

    for url, leader in left.items():
        validator = right[url]
        l_ok = bool(leader.get("fetch_ok"))
        v_ok = bool(validator.get("fetch_ok"))
        if l_ok != v_ok:
            return False
        if not l_ok:
            continue

        l_out = normalize_outcome(leader.get("outcome"), claim_type, [])
        v_out = normalize_outcome(validator.get("outcome"), claim_type, [])
        if l_out == UNRESOLVED or v_out == UNRESOLVED:
            if l_out != v_out:
                return False
            continue
        if l_out != v_out:
            return False

        if claim_type == "NUMERIC":
            l_num = parse_number(leader.get("numeric_value"))
            v_num = parse_number(validator.get("numeric_value"))
            if l_num is None or v_num is None:
                return False
            if not within_tolerance(l_num, v_num, tolerance_bps) and not within_tolerance(
                v_num, l_num, tolerance_bps
            ):
                return False
    return True


def settlements_equivalent(leader: dict[str, Any], validator: dict[str, Any]) -> bool:
    """Payout-relevant fields must match exactly. No leftover leader median."""
    if not isinstance(leader, dict) or not isinstance(validator, dict):
        return False
    if leader.get("status") != validator.get("status"):
        return False
    if leader.get("outcome") != validator.get("outcome"):
        return False
    if bool(leader.get("quorum_met")) != bool(validator.get("quorum_met")):
        return False
    return leader.get("numeric_ticks") == validator.get("numeric_ticks")


def payloads_equivalent(
    leader_payload: dict[str, Any],
    validator_payload: dict[str, Any],
    claim_type: str,
    tolerance_bps: int,
) -> bool:
    if not isinstance(leader_payload, dict) or not isinstance(validator_payload, dict):
        return False
    if not reports_equivalent(
        leader_payload.get("reports") or [],
        validator_payload.get("reports") or [],
        claim_type,
        tolerance_bps,
    ):
        return False
    return settlements_equivalent(
        leader_payload.get("settlement") or {},
        validator_payload.get("settlement") or {},
    )


def bond_matches_range(
    numeric_ticks: int | None,
    expected_min: Any,
    expected_max: Any,
) -> bool:
    """Integer-tick range used by QuorumBond. Same ticks ⇒ same payee."""
    if numeric_ticks is None:
        return False
    ticks = int(numeric_ticks)
    nmin = canonicalize_numeric(expected_min)
    nmax = canonicalize_numeric(expected_max)
    if nmin is not None and ticks < nmin:
        return False
    if nmax is not None and ticks > nmax:
        return False
    return True
