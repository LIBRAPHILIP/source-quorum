# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
SourceQuorum — reusable multi-source fact settlement primitive.

Other builders compose this contract as an oracle. The LLM never decides the
settlement. It only extracts a structured fact from each locked source.
Validators independently re-fetch every source and re-extract those facts.
After consensus on the extracts, settlement is computed by deterministic
quorum math (coverage, majority-with-no-tie, numeric median band).

This is not a thin LLM wrapper and not a single-URL "AI decides X" demo.
"""

from genlayer import *

import json
import typing


VERSION = "1.0.0-source-quorum"
MAX_SOURCES = 8
MIN_SOURCES = 2
MIN_QUORUM = 2
MAX_QUESTION = 2000
MIN_QUESTION = 16
MAX_CHALLENGE_BUDGET = 3
BODY_LIMIT = 12000

CLAIM_TYPES = ("BINARY", "ENUM", "NUMERIC")
STATUSES = ("DRAFT", "LOCKED", "SETTLED", "UNRESOLVED", "CHALLENGED", "FINAL")
UNRESOLVED = "UNRESOLVED"
SETTLED = "SETTLED"
BINARY_OUTCOMES = ("YES", "NO")


class SourceQuorum(gl.Contract):
    """Typed multi-source claim registry with independent validator re-execution."""

    claim_count: u256
    claims: TreeMap[str, str]
    version: str
    title: str

    def __init__(self):
        self.claim_count = u256(0)
        self.version = VERSION
        self.title = "SourceQuorum"

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    @gl.public.view
    def get_meta(self) -> dict[str, str]:
        return {
            "title": self.title,
            "version": self.version,
            "claim_count": str(self.claim_count),
            "primitive": "multi-source-quorum-oracle",
            "consensus": "run_nondet_unsafe independent re-fetch + field compare",
            "settlement": "deterministic quorum after agreed extracts",
            "claim_types": ",".join(CLAIM_TYPES),
            "statuses": ",".join(STATUSES),
        }

    @gl.public.view
    def get_claim_count(self) -> u256:
        return self.claim_count

    @gl.public.view
    def get_claim(self, claim_id: str) -> str:
        claim_id = str(claim_id).strip()
        if claim_id not in self.claims:
            return json.dumps({"error": "claim_not_found", "claim_id": claim_id})
        return self.claims[claim_id]

    @gl.public.view
    def get_settlement(self, claim_id: str) -> str:
        """
        Stable consumer API for composing contracts (see QuorumBond).

        Returns status, outcome, numeric_value, finalized, tally, reason.
        """
        rec = self._read(claim_id)
        if rec is None:
            return json.dumps({"error": "claim_not_found", "claim_id": claim_id})
        return json.dumps(
            {
                "claim_id": rec["claim_id"],
                "claim_type": rec["claim_type"],
                "status": rec["status"],
                "outcome": rec.get("outcome", UNRESOLVED),
                "numeric_value": rec.get("numeric_value"),
                "finalized": rec["status"] == "FINAL",
                "settled": rec["status"] in ("SETTLED", "FINAL"),
                "tally": rec.get("tally", {}),
                "coverage": rec.get("coverage", 0),
                "usable": rec.get("usable", 0),
                "reason": rec.get("reason", ""),
                "quorum_met": bool(rec.get("quorum_met", False)),
                "question": rec.get("question", ""),
            },
            sort_keys=True,
        )

    @gl.public.view
    def list_claims(self, offset: u256, limit: u256) -> typing.Any:
        off = max(0, int(offset))
        lim = int(limit)
        if lim <= 0:
            lim = 10
        if lim > 50:
            lim = 50
        total = int(self.claim_count)
        out: list[str] = []
        idx = total - 1 - off
        while idx >= 0 and len(out) < lim:
            key = str(idx)
            if key in self.claims:
                out.append(self.claims[key])
            idx -= 1
        return out

    @gl.public.view
    def describe_primitive(self) -> dict[str, str]:
        return {
            "name": "SourceQuorum",
            "purpose": "Settle typed real-world claims from a locked set of independent web sources.",
            "leader": "Fetch every locked source, LLM-extract one structured fact per source.",
            "validator": "Re-fetch the same sources, re-extract, compare decision fields only.",
            "not_compared": "excerpt, rationale, confidence, raw HTML",
            "compared": "url set, fetch_ok, outcome, numeric_value within tolerance_bps",
            "gate": "UNRESOLVED vs a concrete outcome is never equivalent — forces retry.",
            "settlement": "Deterministic quorum math after extracts are accepted.",
            "compose": "Call get_settlement(claim_id) from another Intelligent Contract.",
        }

    # ------------------------------------------------------------------
    # Writes — claim lifecycle
    # ------------------------------------------------------------------

    @gl.public.write
    def create_claim(
        self,
        question: str,
        claim_type: str,
        allowed_outcomes: str,
        min_quorum: str,
        min_coverage: str,
        tolerance_bps: str,
        challenge_budget: str,
        initial_sources: str,
    ) -> str:
        question = (question or "").strip()
        claim_type = (claim_type or "").strip().upper()
        if len(question) < MIN_QUESTION:
            raise Exception("question_too_short")
        if len(question) > MAX_QUESTION:
            raise Exception("question_too_long")
        if claim_type not in CLAIM_TYPES:
            raise Exception("invalid_claim_type")

        allowed = _parse_outcomes(allowed_outcomes)
        if claim_type == "BINARY":
            allowed = list(BINARY_OUTCOMES)
        elif claim_type == "ENUM":
            if len(allowed) < 2:
                raise Exception("enum_needs_two_outcomes")
            if UNRESOLVED in allowed:
                raise Exception("unresolved_not_allowed_as_outcome")
        elif claim_type == "NUMERIC":
            allowed = []

        quorum = _parse_u(min_quorum, MIN_QUORUM)
        coverage = _parse_u(min_coverage, quorum)
        if quorum < MIN_QUORUM:
            raise Exception("min_quorum_below_2")
        if coverage < quorum:
            raise Exception("min_coverage_below_quorum")
        if coverage > MAX_SOURCES:
            raise Exception("min_coverage_too_high")

        tol = _parse_u(tolerance_bps, 200)
        if claim_type != "NUMERIC":
            tol = 0
        if tol > 5000:
            raise Exception("tolerance_too_wide")

        budget = _parse_u(challenge_budget, 1)
        if budget > MAX_CHALLENGE_BUDGET:
            raise Exception("challenge_budget_too_high")

        sources = _parse_sources(initial_sources)
        if len(sources) > MAX_SOURCES:
            raise Exception("too_many_sources")

        claim_id = str(int(self.claim_count))
        self.claim_count = self.claim_count + u256(1)
        rec = {
            "claim_id": claim_id,
            "creator": gl.message.sender_address.as_hex,
            "question": question,
            "claim_type": claim_type,
            "allowed_outcomes": allowed,
            "min_quorum": quorum,
            "min_coverage": coverage,
            "tolerance_bps": tol,
            "challenge_budget": budget,
            "challenges_used": 0,
            "status": "DRAFT",
            "sources": sources,
            "reports": [],
            "outcome": UNRESOLVED,
            "numeric_value": None,
            "tally": {},
            "coverage": 0,
            "usable": 0,
            "reason": "draft",
            "quorum_met": False,
            "challenge_reason": "",
            "resolve_count": 0,
        }
        self.claims[claim_id] = json.dumps(rec)
        return claim_id

    @gl.public.write
    def add_source(self, claim_id: str, url: str, label: str) -> str:
        rec = self._require(claim_id)
        self._only_creator(rec)
        if rec["status"] != "DRAFT":
            raise Exception("sources_not_editable")
        source = _source_obj(url, label)
        for existing in rec["sources"]:
            if existing["url"] == source["url"]:
                raise Exception("duplicate_source")
        if len(rec["sources"]) >= MAX_SOURCES:
            raise Exception("too_many_sources")
        rec["sources"].append(source)
        self._write(rec)
        return json.dumps(rec["sources"])

    @gl.public.write
    def lock_sources(self, claim_id: str) -> str:
        rec = self._require(claim_id)
        self._only_creator(rec)
        if rec["status"] != "DRAFT":
            raise Exception("already_locked")
        if len(rec["sources"]) < MIN_SOURCES:
            raise Exception("need_at_least_two_sources")
        if len(rec["sources"]) < int(rec["min_coverage"]):
            raise Exception("not_enough_sources_for_coverage")
        rec["status"] = "LOCKED"
        rec["reason"] = "sources_locked"
        self._write(rec)
        return rec["status"]

    @gl.public.write
    def resolve(self, claim_id: str) -> typing.Any:
        """
        Run multi-source extraction under GenLayer consensus, then settle
        with deterministic quorum math.

        Anyone may call this once sources are locked, unresolved, or challenged.
        """
        rec = self._require(claim_id)
        if rec["status"] not in ("LOCKED", "UNRESOLVED", "CHALLENGED"):
            raise Exception("not_resolvable")

        sources = rec["sources"]
        if len(sources) < MIN_SOURCES:
            raise Exception("need_at_least_two_sources")

        question = rec["question"]
        claim_type = rec["claim_type"]
        allowed = list(rec["allowed_outcomes"])
        tolerance_bps = int(rec["tolerance_bps"])
        locked_urls = [s["url"] for s in sources]

        def leader_fn():
            return _extract_all_sources(
                locked_urls, question, claim_type, allowed, tolerance_bps
            )

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return _validator_handles_leader_error(leader_result, leader_fn)
            leader_reports = leader_result.calldata
            if not _valid_report_list(leader_reports, locked_urls):
                return False
            try:
                validator_reports = leader_fn()
            except Exception:
                return False
            return _reports_equivalent(
                leader_reports, validator_reports, claim_type, tolerance_bps
            )

        reports = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        if not _valid_report_list(reports, locked_urls):
            raise Exception("invalid_consensus_reports")

        settlement = _compute_quorum(
            claim_type,
            allowed,
            int(rec["min_quorum"]),
            int(rec["min_coverage"]),
            tolerance_bps,
            reports,
        )

        rec["reports"] = reports
        rec["outcome"] = settlement["outcome"]
        rec["numeric_value"] = settlement["numeric_value"]
        rec["tally"] = settlement["tally"]
        rec["coverage"] = settlement["coverage"]
        rec["usable"] = settlement["usable"]
        rec["reason"] = settlement["reason"]
        rec["quorum_met"] = settlement["quorum_met"]
        rec["resolve_count"] = int(rec.get("resolve_count", 0)) + 1
        rec["status"] = SETTLED if settlement["status"] == SETTLED else UNRESOLVED
        self._write(rec)
        return json.dumps(
            {
                "claim_id": rec["claim_id"],
                "status": rec["status"],
                "outcome": rec["outcome"],
                "numeric_value": rec["numeric_value"],
                "reason": rec["reason"],
                "tally": rec["tally"],
                "coverage": rec["coverage"],
            },
            sort_keys=True,
        )

    @gl.public.write
    def challenge(self, claim_id: str, extra_url: str, extra_label: str, reason: str) -> str:
        """
        Add one independent source and reopen extraction.

        A challenge is only allowed after a resolve attempt and only while
        the challenge budget remains. This is the primitive's appeal path.
        """
        rec = self._require(claim_id)
        if rec["status"] not in (SETTLED, UNRESOLVED):
            raise Exception("not_challengeable")
        if int(rec["challenges_used"]) >= int(rec["challenge_budget"]):
            raise Exception("challenge_budget_exhausted")
        reason = (reason or "").strip()
        if len(reason) < 8:
            raise Exception("challenge_reason_too_short")
        if len(reason) > 500:
            raise Exception("challenge_reason_too_long")

        source = _source_obj(extra_url, extra_label or "challenge")
        for existing in rec["sources"]:
            if existing["url"] == source["url"]:
                raise Exception("duplicate_source")
        if len(rec["sources"]) >= MAX_SOURCES:
            raise Exception("too_many_sources")

        rec["sources"].append(source)
        rec["challenges_used"] = int(rec["challenges_used"]) + 1
        rec["challenge_reason"] = reason
        rec["status"] = "CHALLENGED"
        rec["reason"] = "challenged"
        rec["quorum_met"] = False
        self._write(rec)
        return rec["status"]

    @gl.public.write
    def finalize(self, claim_id: str) -> str:
        """
        Freeze a SETTLED claim. After this, get_settlement is immutable.
        """
        rec = self._require(claim_id)
        if rec["status"] != SETTLED:
            raise Exception("only_settled_can_finalize")
        rec["status"] = "FINAL"
        rec["reason"] = "finalized"
        self._write(rec)
        return rec["status"]

    # ------------------------------------------------------------------
    # Internal state helpers
    # ------------------------------------------------------------------

    def _read(self, claim_id: str) -> dict | None:
        claim_id = str(claim_id).strip()
        if claim_id not in self.claims:
            return None
        try:
            rec = json.loads(self.claims[claim_id])
        except Exception:
            return None
        if not isinstance(rec, dict):
            return None
        return rec

    def _require(self, claim_id: str) -> dict:
        rec = self._read(claim_id)
        if rec is None:
            raise Exception("claim_not_found")
        return rec

    def _write(self, rec: dict) -> None:
        self.claims[str(rec["claim_id"])] = json.dumps(rec)

    def _only_creator(self, rec: dict) -> None:
        if rec.get("creator", "").lower() != gl.message.sender_address.as_hex.lower():
            raise Exception("only_creator")


# ======================================================================
# Extraction + consensus helpers (no storage access)
# ======================================================================

def _extract_all_sources(
    urls: list[str],
    question: str,
    claim_type: str,
    allowed: list[str],
    tolerance_bps: int,
) -> list[dict]:
    reports: list[dict] = []
    fetched_ok = 0
    for url in urls:
        report = _extract_one_source(url, question, claim_type, allowed, tolerance_bps)
        reports.append(report)
        if report.get("fetch_ok"):
            fetched_ok += 1
    if fetched_ok == 0:
        raise Exception("[TRANSIENT] all_sources_failed")
    return reports


def _extract_one_source(
    url: str,
    question: str,
    claim_type: str,
    allowed: list[str],
    tolerance_bps: int,
) -> dict:
    body = ""
    fetch_ok = False
    try:
        page = gl.nondet.web.get(url)
        raw = page.body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        body = str(raw)[:BODY_LIMIT]
        fetch_ok = True
    except Exception as exc:
        return {
            "url": url,
            "fetch_ok": False,
            "outcome": UNRESOLVED,
            "numeric_value": None,
            "excerpt": f"fetch_failed:{type(exc).__name__}",
            "confidence": 0,
        }

    allowed_txt = ", ".join(allowed) if allowed else "(numeric — return the number the source states)"
    prompt = f"""You extract a structured fact from ONE source page for an on-chain quorum oracle.
Do not use outside knowledge. Use only the page text.

CLAIM_TYPE: {claim_type}
QUESTION: {question}
ALLOWED_OUTCOMES: {allowed_txt}
NUMERIC_TOLERANCE_BPS: {tolerance_bps}
SOURCE_URL: {url}

PAGE:
{body}

Return ONLY JSON:
{{
  "outcome": "YES" | "NO" | "<one allowed enum>" | "VALUE" | "UNRESOLVED",
  "numeric_value": null or number,
  "excerpt": "short quote or paraphrase from THIS page that supports the extraction",
  "confidence": integer 0-100
}}

Rules:
- BINARY: YES or NO if the page itself answers the question; otherwise UNRESOLVED.
- ENUM: outcome must be one of ALLOWED_OUTCOMES, else UNRESOLVED.
- NUMERIC: outcome is VALUE and numeric_value is the number the page states for the question.
- If the page is unrelated, empty, paywalled, or silent, outcome is UNRESOLVED.
- excerpt must come from the page. Never invent citations.
"""
    raw_llm = gl.nondet.exec_prompt(prompt)
    parsed = _parse_extract_json(raw_llm, claim_type, allowed)
    parsed["url"] = url
    parsed["fetch_ok"] = fetch_ok
    return parsed


def _parse_extract_json(raw: typing.Any, claim_type: str, allowed: list[str]) -> dict:
    text = raw if isinstance(raw, str) else str(raw)
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    outcome = _normalize_outcome(data.get("outcome"), claim_type, allowed)
    number = _parse_number(data.get("numeric_value"))
    if claim_type == "NUMERIC":
        if number is None:
            outcome = UNRESOLVED
        elif outcome != UNRESOLVED:
            outcome = "VALUE"
    else:
        number = None

    try:
        confidence = int(data.get("confidence", 0))
    except Exception:
        confidence = 0
    confidence = max(0, min(100, confidence))
    excerpt = str(data.get("excerpt", data.get("rationale", "")))[:400]
    return {
        "outcome": outcome,
        "numeric_value": number,
        "excerpt": excerpt,
        "confidence": confidence,
    }


def _valid_report_list(reports: typing.Any, locked_urls: list[str]) -> bool:
    if not isinstance(reports, list):
        return False
    if len(reports) != len(locked_urls):
        return False
    seen = set()
    for report, expected in zip(reports, locked_urls):
        if not isinstance(report, dict):
            return False
        url = str(report.get("url", "")).strip()
        if url != expected or url in seen:
            return False
        seen.add(url)
        if "fetch_ok" not in report:
            return False
        if "outcome" not in report:
            return False
    return True


def _reports_equivalent(
    leader_reports: list,
    validator_reports: list,
    claim_type: str,
    tolerance_bps: int,
) -> bool:
    """
    Independent verification. Never trust leader formatting alone.

    Compared: url identity, fetch_ok, outcome, numeric_value (with tolerance).
    Not compared: excerpt, confidence, raw page bytes.
    Gate: UNRESOLVED vs a concrete outcome is a reject (retry), not a settle.
    """
    if not _same_url_order(leader_reports, validator_reports):
        return False
    for leader, validator in zip(leader_reports, validator_reports):
        l_ok = bool(leader.get("fetch_ok"))
        v_ok = bool(validator.get("fetch_ok"))
        if l_ok != v_ok:
            return False
        if not l_ok:
            continue
        l_out = _normalize_outcome(leader.get("outcome"), claim_type, [])
        v_out = _normalize_outcome(validator.get("outcome"), claim_type, [])
        if l_out == UNRESOLVED or v_out == UNRESOLVED:
            if l_out != v_out:
                return False
            continue
        if l_out != v_out:
            return False
        if claim_type == "NUMERIC":
            l_num = _parse_number(leader.get("numeric_value"))
            v_num = _parse_number(validator.get("numeric_value"))
            if l_num is None or v_num is None:
                return False
            if not _within_tolerance(l_num, v_num, tolerance_bps) and not _within_tolerance(
                v_num, l_num, tolerance_bps
            ):
                return False
    return True


def _same_url_order(a: list, b: list) -> bool:
    if len(a) != len(b):
        return False
    for left, right in zip(a, b):
        if str(left.get("url", "")) != str(right.get("url", "")):
            return False
    return True


def _validator_handles_leader_error(leader_result, leader_fn) -> bool:
    """Classify leader errors. Transient/all-source failures can agree; LLM errors retry."""
    leader_msg = getattr(leader_result, "message", "") or str(leader_result)
    try:
        leader_fn()
        return False
    except Exception as exc:
        validator_msg = getattr(exc, "message", "") or str(exc)
        if validator_msg.startswith("[TRANSIENT]") and leader_msg.startswith("[TRANSIENT]"):
            return True
        if validator_msg.startswith("[EXPECTED]") and validator_msg == leader_msg:
            return True
        return False


# ======================================================================
# Deterministic quorum math (mirrors lib/quorum_math.py)
# ======================================================================

def _compute_quorum(
    claim_type: str,
    allowed: list[str],
    min_quorum: int,
    min_coverage: int,
    tolerance_bps: int,
    reports: list,
) -> dict:
    fetched = [r for r in reports if bool(r.get("fetch_ok"))]
    coverage = len(fetched)
    if coverage < min_coverage:
        return _fail("insufficient_coverage", {}, coverage)
    if claim_type == "NUMERIC":
        return _numeric_quorum(fetched, min_quorum, tolerance_bps, coverage)
    return _categorical_quorum(claim_type, allowed, fetched, min_quorum, coverage)


def _categorical_quorum(
    claim_type: str, allowed: list[str], fetched: list, min_quorum: int, coverage: int
) -> dict:
    tally: dict[str, int] = {}
    usable = 0
    for report in fetched:
        outcome = _normalize_outcome(report.get("outcome"), claim_type, allowed)
        if outcome == UNRESOLVED:
            continue
        tally[outcome] = tally.get(outcome, 0) + 1
        usable += 1
    if usable < min_quorum or not tally:
        return _fail("no_quorum", tally, coverage)
    ranked = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
    winner, win_count = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if win_count < min_quorum:
        return _fail("no_quorum", tally, coverage)
    if win_count == second:
        return _fail("tie", tally, coverage)
    return {
        "status": SETTLED,
        "outcome": winner,
        "numeric_value": None,
        "reason": "quorum",
        "coverage": coverage,
        "usable": usable,
        "tally": tally,
        "quorum_met": True,
    }


def _numeric_quorum(fetched: list, min_quorum: int, tolerance_bps: int, coverage: int) -> dict:
    values: list[float] = []
    for report in fetched:
        if _normalize_outcome(report.get("outcome"), "NUMERIC", []) == UNRESOLVED:
            continue
        number = _parse_number(report.get("numeric_value"))
        if number is None:
            continue
        values.append(number)
    tally = {"VALUE": len(values), UNRESOLVED: coverage - len(values)}
    if len(values) < min_quorum:
        return _fail("no_quorum", tally, coverage)
    center = _median(values)
    band = [v for v in values if _within_tolerance(v, center, tolerance_bps)]
    if len(band) < min_quorum:
        return _fail("numeric_dispersion", tally, coverage)
    settled_value = _median(band)
    return {
        "status": SETTLED,
        "outcome": "VALUE",
        "numeric_value": settled_value,
        "reason": "numeric_band",
        "coverage": coverage,
        "usable": len(band),
        "tally": {"in_band": len(band), "extracted": len(values)},
        "quorum_met": True,
    }


def _fail(reason: str, tally: dict, coverage: int) -> dict:
    return {
        "status": UNRESOLVED,
        "outcome": UNRESOLVED,
        "numeric_value": None,
        "reason": reason,
        "coverage": coverage,
        "usable": 0,
        "tally": tally,
        "quorum_met": False,
    }


def _normalize_outcome(raw, claim_type: str, allowed: list[str]) -> str:
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
        if allowed_u:
            return text if text in allowed_u else UNRESOLVED
        return text if text and text != UNRESOLVED else UNRESOLVED
    if claim_type == "NUMERIC":
        return "VALUE" if text not in (UNRESOLVED, "") else UNRESOLVED
    return UNRESOLVED


def _parse_number(raw):
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
    except Exception:
        return None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _within_tolerance(value: float, center: float, tolerance_bps: int) -> bool:
    if tolerance_bps < 0:
        return False
    if center == 0.0:
        return value == 0.0
    return abs(value - center) / abs(center) <= (tolerance_bps / 10000.0)


def _parse_u(raw: str, default: int) -> int:
    text = str(raw or "").strip()
    if text == "":
        return default
    try:
        value = int(text)
    except Exception:
        raise Exception("invalid_integer")
    if value < 0:
        raise Exception("negative_integer")
    return value


def _parse_outcomes(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x).strip().upper() for x in data if str(x).strip()]
        except Exception:
            raise Exception("invalid_allowed_outcomes_json")
    parts = [p.strip().upper() for p in text.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _parse_sources(raw: str) -> list[dict]:
    text = (raw or "").strip()
    if not text:
        return []
    urls: list[str] = []
    if text.startswith("["):
        try:
            data = json.loads(text)
        except Exception:
            raise Exception("invalid_sources_json")
        if not isinstance(data, list):
            raise Exception("invalid_sources_json")
        for item in data:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
    else:
        urls = [p.strip() for p in text.replace("\n", ",").split(",")]
    sources = []
    seen = set()
    for url in urls:
        if not url:
            continue
        obj = _source_obj(url, "")
        if obj["url"] in seen:
            raise Exception("duplicate_source")
        seen.add(obj["url"])
        sources.append(obj)
    return sources


def _source_obj(url: str, label: str) -> dict:
    url = (url or "").strip()
    label = (label or "").strip()[:80]
    if not (url.startswith("https://") or url.startswith("http://")):
        raise Exception("invalid_source_url")
    if len(url) > 500:
        raise Exception("source_url_too_long")
    return {"url": url, "label": label}
