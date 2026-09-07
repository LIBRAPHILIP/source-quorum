# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
QuorumBond — composable parametric release against SourceQuorum.

This is a consumer of the SourceQuorum primitive, not a second oracle.
It never calls an LLM. It reads get_settlement(claim_id) from a deployed
SourceQuorum contract and releases or refunds bonded GEN accordingly.

Use it for:
  - parametric insurance (NUMERIC claim settles in-band)
  - prediction-style side bets (BINARY / ENUM)
  - milestone release (BINARY "was the public criterion met?")
"""

from genlayer import *

import json
import typing


VERSION = "1.2.0-quorum-bond"
NUMERIC_SCALE = 10000


@gl.contract_interface
class SourceQuorumIface:
    class View:
        def get_settlement(self, claim_id: str) -> str: ...
        def get_meta(self) -> dict: ...

    class Write:
        pass


class QuorumBond(gl.Contract):
    bond_count: u256
    bonds: TreeMap[str, str]
    oracle: Address
    version: str
    title: str

    def __init__(self, oracle_address: str):
        addr = (oracle_address or "").strip()
        if not addr:
            raise Exception("oracle_required")
        self.oracle = Address(addr)
        self.bond_count = u256(0)
        self.version = VERSION
        self.title = "QuorumBond"

    @gl.public.view
    def get_meta(self) -> dict[str, str]:
        return {
            "title": self.title,
            "version": self.version,
            "oracle": self.oracle.as_hex,
            "bond_count": str(self.bond_count),
            "primitive": "parametric-release-against-source-quorum",
            "consensus": "none-locally — settlement is read from SourceQuorum",
        }

    @gl.public.view
    def get_oracle(self) -> str:
        return self.oracle.as_hex

    @gl.public.view
    def get_bond_count(self) -> u256:
        return self.bond_count

    @gl.public.view
    def get_bond(self, bond_id: str) -> str:
        bond_id = str(bond_id).strip()
        if bond_id not in self.bonds:
            return json.dumps({"error": "bond_not_found", "bond_id": bond_id})
        return self.bonds[bond_id]

    @gl.public.view
    def preview_settlement(self, claim_id: str) -> str:
        oracle = SourceQuorumIface(self.oracle)
        return oracle.view().get_settlement(claim_id)

    @gl.public.write.payable
    def create_bond(
        self,
        claim_id: str,
        expected_outcome: str,
        expected_numeric_min: str,
        expected_numeric_max: str,
        beneficiary: str,
    ) -> str:
        """
        Lock gl.message.value against a SourceQuorum claim.

        BINARY/ENUM: payout if settlement.outcome == expected_outcome.
        NUMERIC: payout if consensus numeric_ticks is inside [min, max] (inclusive).
        Otherwise the funder may withdraw the refund after settle_bond.
        """
        value = gl.message.value
        if value == u256(0):
            raise Exception("zero_value")

        claim_id = (claim_id or "").strip()
        if not claim_id:
            raise Exception("claim_id_required")

        expected_outcome = (expected_outcome or "").strip().upper()
        if not expected_outcome:
            raise Exception("expected_outcome_required")

        beneficiary_addr = (beneficiary or "").strip()
        if not beneficiary_addr:
            raise Exception("beneficiary_required")

        settlement = self._read_settlement(claim_id)
        if settlement.get("error") == "claim_not_found":
            raise Exception("unknown_claim")
        if settlement.get("finalized") is True or settlement.get("status") == "FINAL":
            raise Exception("claim_already_final")

        nmin = _optional_float(expected_numeric_min)
        nmax = _optional_float(expected_numeric_max)
        if nmin is not None and nmax is not None and nmin > nmax:
            raise Exception("numeric_range_inverted")

        bond_id = str(int(self.bond_count))
        self.bond_count = self.bond_count + u256(1)
        rec = {
            "bond_id": bond_id,
            "claim_id": claim_id,
            "funder": gl.message.sender_address.as_hex,
            "beneficiary": Address(beneficiary_addr).as_hex,
            "expected_outcome": expected_outcome,
            "expected_numeric_min": nmin,
            "expected_numeric_max": nmax,
            "amount": str(int(value)),
            "status": "OPEN",
            "payee": "",
            "withdrawn": False,
            "resolution_status": "",
            "resolution_outcome": "",
            "matched": False,
        }
        self.bonds[bond_id] = json.dumps(rec)
        return bond_id

    @gl.public.write
    def settle_bond(self, bond_id: str) -> str:
        """
        Read the oracle only after the claim is FINAL (immutable).
        SETTLED is still challengeable and must not assign a payee.
        Idempotent: a later re-call does not flip a decided bond.
        """
        rec = self._require(bond_id)
        if rec["status"] != "OPEN":
            return rec["status"]

        settlement = self._read_settlement(rec["claim_id"])
        status = str(settlement.get("status", ""))
        finalized = bool(settlement.get("finalized") or settlement.get("immutable"))
        if status != "FINAL" and not finalized:
            raise Exception("claim_not_final")

        matched = _matches(rec, settlement)
        rec["resolution_status"] = status
        rec["resolution_outcome"] = str(settlement.get("outcome", ""))
        rec["matched"] = matched
        rec["payee"] = rec["beneficiary"] if matched else rec["funder"]
        rec["status"] = "PAYABLE"
        self._write(rec)
        return rec["status"]

    @gl.public.write
    def withdraw(self, bond_id: str) -> str:
        rec = self._require(bond_id)
        if rec["status"] != "PAYABLE":
            raise Exception("not_payable")
        if rec["withdrawn"]:
            raise Exception("already_withdrawn")
        sender = gl.message.sender_address.as_hex.lower()
        if sender != str(rec["payee"]).lower():
            raise Exception("not_payee")

        amount = u256(int(rec["amount"]))
        if amount == u256(0):
            raise Exception("zero_amount")
        if self.balance < amount:
            raise Exception("insufficient_contract_balance")

        rec["withdrawn"] = True
        rec["status"] = "PAID" if rec["matched"] else "REFUNDED"
        self._write(rec)

        # External transfer to EOA / chain-layer address (ghost contract path).
        _Recipient(Address(rec["payee"])).emit_transfer(value=amount, on="finalized")
        return rec["status"]

    def _read_settlement(self, claim_id: str) -> dict:
        oracle = SourceQuorumIface(self.oracle)
        raw = oracle.view().get_settlement(claim_id)
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw)
        except Exception:
            raise Exception("oracle_unreadable")
        if not isinstance(data, dict):
            raise Exception("oracle_unreadable")
        return data

    def _require(self, bond_id: str) -> dict:
        bond_id = str(bond_id).strip()
        if bond_id not in self.bonds:
            raise Exception("bond_not_found")
        rec = json.loads(self.bonds[bond_id])
        if not isinstance(rec, dict):
            raise Exception("corrupt_bond")
        return rec

    def _write(self, rec: dict) -> None:
        self.bonds[str(rec["bond_id"])] = json.dumps(rec)


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


def _optional_float(raw: str) -> typing.Any:
    text = str(raw or "").strip()
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        raise Exception("invalid_number")


def _matches(bond: dict, settlement: dict) -> bool:
    if not bool(settlement.get("quorum_met", False)) and str(
        settlement.get("status", "")
    ) not in ("SETTLED", "FINAL"):
        return False
    expected = str(bond.get("expected_outcome", "")).upper()
    actual = str(settlement.get("outcome", "")).upper()
    if expected == "VALUE" or actual == "VALUE":
        ticks = _settlement_ticks(settlement)
        if ticks is None:
            return False
        nmin = _to_ticks(bond.get("expected_numeric_min"))
        nmax = _to_ticks(bond.get("expected_numeric_max"))
        if nmin is not None and ticks < nmin:
            return False
        if nmax is not None and ticks > nmax:
            return False
        return True
    return expected == actual and expected not in ("", "UNRESOLVED")


def _settlement_ticks(settlement: dict) -> typing.Any:
    raw = settlement.get("numeric_ticks")
    if raw is not None and raw != "":
        try:
            return int(raw)
        except Exception:
            pass
    return _to_ticks(settlement.get("numeric_value"))


def _to_ticks(raw) -> typing.Any:
    if raw is None or raw == "":
        return None
    try:
        number = float(raw)
    except Exception:
        return None
    scaled = number * NUMERIC_SCALE
    if scaled >= 0:
        return int(scaled + 0.5)
    return int(scaled - 0.5)
