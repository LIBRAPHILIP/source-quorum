"""
Direct-mode tests for SourceQuorum (genlayer-test).

These run in-memory without Studio. Web and LLM calls are mocked so the
test asserts the contract's consensus wiring and state machine, not a
live model.

    pip install -r requirements.txt
    pytest tests/direct/test_source_quorum.py -v
"""

from __future__ import annotations

import json


def _mock_pages(direct_vm, pages: dict[str, str]) -> None:
    for url, body in pages.items():
        escaped = url.replace(".", r"\.")
        direct_vm.mock_web(
            escaped,
            {"status": 200, "body": body},
        )


def _mock_extracts(direct_vm, mapping: list[tuple[str, dict]]) -> None:
    for needle, payload in mapping:
        direct_vm.mock_llm(needle, json.dumps(payload))


def test_create_lock_and_binary_quorum(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/source_quorum.py")
    direct_vm.sender = direct_alice

    claim_id = contract.create_claim(
        "Did GenLayer publish official Intelligent Contract documentation?",
        "BINARY",
        "YES,NO",
        "2",
        "2",
        "0",
        "1",
        "https://docs.genlayer.com/developers/intelligent-contracts/introduction,https://genlayer.com",
    )
    assert claim_id == "0"
    contract.lock_sources(claim_id)

    _mock_pages(
        direct_vm,
        {
            "https://docs.genlayer.com/developers/intelligent-contracts/introduction": (
                "Intelligent Contracts are Python smart contracts on GenLayer."
            ),
            "https://genlayer.com": "GenLayer is the Intelligent Contract Network.",
        },
    )
    _mock_extracts(
        direct_vm,
        [
            (
                r".*",
                {
                    "outcome": "YES",
                    "numeric_value": None,
                    "excerpt": "Intelligent Contracts are Python smart contracts",
                    "confidence": 90,
                },
            )
        ],
    )

    raw = contract.resolve(claim_id)
    result = json.loads(raw)
    assert result["status"] == "SETTLED"
    assert result["outcome"] == "YES"

    settlement = json.loads(contract.get_settlement(claim_id))
    assert settlement["quorum_met"] is True
    assert settlement["finalized"] is False

    contract.finalize(claim_id)
    settlement = json.loads(contract.get_settlement(claim_id))
    assert settlement["status"] == "FINAL"
    assert settlement["finalized"] is True


def test_tie_stays_unresolved(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/source_quorum.py")
    direct_vm.sender = direct_alice
    claim_id = contract.create_claim(
        "Which side won the exhibition match described on these pages?",
        "ENUM",
        "HOME,AWAY,DRAW",
        "2",
        "2",
        "0",
        "1",
        "https://example.org/home1,https://example.org/home2,https://example.org/away1,https://example.org/away2",
    )
    contract.lock_sources(claim_id)

    _mock_pages(
        direct_vm,
        {
            "https://example.org/home1": "Home side claimed the win.",
            "https://example.org/home2": "Home confirmed.",
            "https://example.org/away1": "Away side claimed the win.",
            "https://example.org/away2": "Away confirmed.",
        },
    )
    direct_vm.mock_llm(r".*example\.org/home.*", json.dumps({"outcome": "HOME", "excerpt": "home", "confidence": 70}))
    direct_vm.mock_llm(r".*example\.org/away.*", json.dumps({"outcome": "AWAY", "excerpt": "away", "confidence": 70}))

    raw = contract.resolve(claim_id)
    result = json.loads(raw)
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == "tie"


def test_challenge_adds_source(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/source_quorum.py")
    direct_vm.sender = direct_alice
    claim_id = contract.create_claim(
        "Is the Equivalence Principle documented by GenLayer?",
        "BINARY",
        "YES,NO",
        "2",
        "2",
        "0",
        "1",
        "https://docs.genlayer.com/a,https://docs.genlayer.com/b",
    )
    contract.lock_sources(claim_id)

    _mock_pages(
        direct_vm,
        {
            "https://docs.genlayer.com/a": "Equivalence Principle lets validators compare results.",
            "https://docs.genlayer.com/b": "Validators reach consensus on meaning.",
        },
    )
    direct_vm.mock_llm(
        r".*",
        json.dumps(
            {
                "outcome": "YES",
                "excerpt": "Equivalence Principle",
                "confidence": 88,
            }
        ),
    )
    contract.resolve(claim_id)

    direct_vm.sender = direct_bob
    status = contract.challenge(
        claim_id,
        "https://docs.genlayer.com/c",
        "third",
        "Need a third independent page before finalize.",
    )
    assert status == "CHALLENGED"
    rec = json.loads(contract.get_claim(claim_id))
    assert len(rec["sources"]) == 3
    assert rec["challenges_used"] == 1
