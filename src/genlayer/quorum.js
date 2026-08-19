/**
 * SourceQuorum + QuorumBond — genuine GenLayer read/write paths only.
 *
 * Writes: writeContract / deployContract → waitForTransactionReceipt
 * Reads:  readContract
 * Live consensus: getTransaction + getLastRoundData while waiting
 */
import { TransactionStatus } from "genlayer-js/types";
import {
  getReadClient,
  getWriteClient,
  initializeConsensus,
  getActiveNetworkKey,
} from "./client.js";
import { getNetwork } from "./networks.js";
import oracleSource from "../../contracts/source_quorum.py?raw";
import bondSource from "../../contracts/quorum_bond.py?raw";

export { oracleSource, bondSource };

const ORACLE_KEY = "sourcequorum.oracle";
const BOND_KEY = "sourcequorum.bond";

export function loadSavedOracle() {
  try {
    return localStorage.getItem(ORACLE_KEY) || "";
  } catch {
    return "";
  }
}

export function loadSavedBond() {
  try {
    return localStorage.getItem(BOND_KEY) || "";
  } catch {
    return "";
  }
}

export function saveOracle(address) {
  try {
    if (address) localStorage.setItem(ORACLE_KEY, address);
    else localStorage.removeItem(ORACLE_KEY);
  } catch {
    /* ignore */
  }
}

export function saveBond(address) {
  try {
    if (address) localStorage.setItem(BOND_KEY, address);
    else localStorage.removeItem(BOND_KEY);
  } catch {
    /* ignore */
  }
}

function requireAddress(address, label = "contract") {
  if (!address || !/^0x[0-9a-fA-F]{40}$/.test(address)) {
    throw new Error(`Set a valid ${label} address first (0x + 40 hex).`);
  }
  return address;
}

function extractContractAddress(receipt) {
  return (
    receipt?.data?.contract_address ||
    receipt?.to_address ||
    receipt?.txDataDecoded?.contractAddress ||
    receipt?.contractAddress ||
    receipt?.data?.contractAddress ||
    null
  );
}

export async function deployOracle({ onProgress } = {}) {
  const client = getWriteClient();
  await initializeConsensus();
  onProgress?.({ phase: "deploy_submit", message: "Submitting SourceQuorum deployContract…" });
  const txHash = await client.deployContract({ code: oracleSource, args: [] });
  onProgress?.({ phase: "deploy_wait", message: "Waiting for validator acceptance…", txHash });
  const receipt = await waitWithConsensus(txHash, {
    onRound: (info) => onProgress?.({ phase: "consensus", ...info, txHash }),
  });
  const address = extractContractAddress(receipt);
  if (!address) throw new Error("Deploy accepted but contract address missing from receipt.");
  saveOracle(address);
  onProgress?.({ phase: "deploy_done", message: "SourceQuorum deployed", txHash, address, receipt });
  return { address, txHash, receipt };
}

export async function deployBond(oracleAddress, { onProgress } = {}) {
  const oracle = requireAddress(oracleAddress, "oracle");
  const client = getWriteClient();
  await initializeConsensus();
  onProgress?.({ phase: "deploy_submit", message: "Submitting QuorumBond deployContract…" });
  const txHash = await client.deployContract({ code: bondSource, args: [oracle] });
  onProgress?.({ phase: "deploy_wait", message: "Waiting for validator acceptance…", txHash });
  const receipt = await waitWithConsensus(txHash, {
    onRound: (info) => onProgress?.({ phase: "consensus", ...info, txHash }),
  });
  const address = extractContractAddress(receipt);
  if (!address) throw new Error("Bond deploy accepted but address missing from receipt.");
  saveBond(address);
  onProgress?.({ phase: "deploy_done", message: "QuorumBond deployed", txHash, address, receipt });
  return { address, txHash, receipt };
}

async function writeMethod(address, functionName, args, { onProgress, value = 0n, label } = {}) {
  const client = getWriteClient();
  await initializeConsensus();
  onProgress?.({
    phase: "write_submit",
    message: `Submitting ${label || functionName}…`,
  });
  const txHash = await client.writeContract({
    address,
    functionName,
    args,
    value,
  });
  onProgress?.({
    phase: "write_wait",
    message: "Transaction in flight — watching Optimistic Democracy rounds…",
    txHash,
  });
  const receipt = await waitWithConsensus(txHash, {
    onRound: (info) => onProgress?.({ phase: "consensus", ...info, txHash }),
  });
  onProgress?.({
    phase: "write_done",
    message: `${label || functionName} accepted`,
    txHash,
    receipt,
  });
  return { txHash, receipt };
}

export function createClaim(oracle, fields, opts) {
  return writeMethod(
    requireAddress(oracle, "oracle"),
    "create_claim",
    [
      fields.question,
      fields.claimType,
      fields.allowedOutcomes || "",
      String(fields.minQuorum ?? "2"),
      String(fields.minCoverage ?? "2"),
      String(fields.toleranceBps ?? "0"),
      String(fields.challengeBudget ?? "1"),
      fields.initialSources || "",
    ],
    { ...opts, label: "create_claim" }
  );
}

export function addSource(oracle, claimId, url, label, opts) {
  return writeMethod(requireAddress(oracle, "oracle"), "add_source", [String(claimId), url, label || ""], {
    ...opts,
    label: "add_source",
  });
}

export function lockSources(oracle, claimId, opts) {
  return writeMethod(requireAddress(oracle, "oracle"), "lock_sources", [String(claimId)], {
    ...opts,
    label: "lock_sources",
  });
}

export function resolveClaim(oracle, claimId, opts) {
  return writeMethod(requireAddress(oracle, "oracle"), "resolve", [String(claimId)], {
    ...opts,
    label: "resolve (multi-source consensus)",
  });
}

export function challengeClaim(oracle, claimId, extraUrl, extraLabel, reason, opts) {
  return writeMethod(
    requireAddress(oracle, "oracle"),
    "challenge",
    [String(claimId), extraUrl, extraLabel || "challenge", reason],
    { ...opts, label: "challenge" }
  );
}

export function finalizeClaim(oracle, claimId, opts) {
  return writeMethod(requireAddress(oracle, "oracle"), "finalize", [String(claimId)], {
    ...opts,
    label: "finalize",
  });
}

export function createBond(bond, fields, opts) {
  const wei = parseGenToWei(fields.amountGen);
  return writeMethod(
    requireAddress(bond, "bond"),
    "create_bond",
    [
      String(fields.claimId),
      fields.expectedOutcome,
      fields.numericMin ?? "",
      fields.numericMax ?? "",
      fields.beneficiary,
    ],
    { ...opts, value: wei, label: "create_bond" }
  );
}

export function settleBond(bond, bondId, opts) {
  return writeMethod(requireAddress(bond, "bond"), "settle_bond", [String(bondId)], {
    ...opts,
    label: "settle_bond",
  });
}

export function withdrawBond(bond, bondId, opts) {
  return writeMethod(requireAddress(bond, "bond"), "withdraw", [String(bondId)], {
    ...opts,
    label: "withdraw",
  });
}

export function parseGenToWei(raw) {
  const text = String(raw ?? "").trim();
  if (!text) throw new Error("Enter a GEN amount.");
  const n = Number(text);
  if (!Number.isFinite(n) || n <= 0) throw new Error("GEN amount must be a positive number.");
  return BigInt(Math.round(n * 1e18));
}

function parseMaybeJson(value) {
  if (value == null) return value;
  if (typeof value === "object") return value;
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  return value;
}

export async function readMeta(oracle) {
  return getReadClient().readContract({
    address: requireAddress(oracle, "oracle"),
    functionName: "get_meta",
    args: [],
  });
}

export async function readClaim(oracle, claimId) {
  const raw = await getReadClient().readContract({
    address: requireAddress(oracle, "oracle"),
    functionName: "get_claim",
    args: [String(claimId)],
  });
  return parseMaybeJson(raw);
}

export async function readSettlement(oracle, claimId) {
  const raw = await getReadClient().readContract({
    address: requireAddress(oracle, "oracle"),
    functionName: "get_settlement",
    args: [String(claimId)],
  });
  return parseMaybeJson(raw);
}

export async function readClaims(oracle, offset = 0, limit = 20) {
  const raw = await getReadClient().readContract({
    address: requireAddress(oracle, "oracle"),
    functionName: "list_claims",
    args: [BigInt(offset), BigInt(limit)],
  });
  if (!Array.isArray(raw)) return raw ? [parseMaybeJson(raw)] : [];
  return raw.map(parseMaybeJson);
}

export async function readBondMeta(bond) {
  return getReadClient().readContract({
    address: requireAddress(bond, "bond"),
    functionName: "get_meta",
    args: [],
  });
}

export async function readBond(bond, bondId) {
  const raw = await getReadClient().readContract({
    address: requireAddress(bond, "bond"),
    functionName: "get_bond",
    args: [String(bondId)],
  });
  return parseMaybeJson(raw);
}

export async function readBonds(bond, offset = 0, limit = 20) {
  const raw = await getReadClient().readContract({
    address: requireAddress(bond, "bond"),
    functionName: "list_bonds",
    args: [BigInt(offset), BigInt(limit)],
  });
  if (!Array.isArray(raw)) return raw ? [parseMaybeJson(raw)] : [];
  return raw.map(parseMaybeJson);
}

export async function waitWithConsensus(txHash, { onRound, preferFinalized = false } = {}) {
  const client = getReadClient();
  const target = preferFinalized ? TransactionStatus.FINALIZED : TransactionStatus.ACCEPTED;
  let stopped = false;
  const poll = (async () => {
    let ticks = 0;
    while (!stopped && ticks < 200) {
      ticks += 1;
      try {
        onRound?.(await fetchConsensusSnapshot(txHash));
      } catch {
        /* round data may not exist yet */
      }
      await sleep(2500);
    }
  })();
  try {
    const receipt = await client.waitForTransactionReceipt({
      hash: txHash,
      status: target,
      retries: 360,
      interval: 5000,
      fullTransaction: true,
    });
    try {
      onRound?.({
        ...(await fetchConsensusSnapshot(txHash)),
        terminal: true,
        receiptStatus: receipt.statusName,
      });
    } catch {
      /* optional */
    }
    return receipt;
  } finally {
    stopped = true;
    await poll.catch(() => {});
  }
}

export async function fetchConsensusSnapshot(txHash) {
  const client = getReadClient();
  const net = getNetwork(getActiveNetworkKey());
  const snapshot = {
    txHash,
    network: net.key,
    at: new Date().toISOString(),
    transaction: null,
    lastRound: null,
    canAppeal: null,
    rawErrors: [],
  };
  try {
    if (typeof client.getTransaction === "function") {
      snapshot.transaction = await client.getTransaction({ hash: txHash });
    }
  } catch (e) {
    snapshot.rawErrors.push(`getTransaction: ${e.message}`);
  }
  try {
    if (typeof client.getLastRoundData === "function") {
      snapshot.lastRound = await client.getLastRoundData({ txId: txHash });
    }
  } catch (e) {
    snapshot.rawErrors.push(`getLastRoundData: ${e.message}`);
  }
  try {
    if (typeof client.canAppeal === "function") {
      snapshot.canAppeal = await client.canAppeal({ txId: txHash });
    }
  } catch (e) {
    snapshot.rawErrors.push(`canAppeal: ${e.message}`);
  }
  return snapshot;
}

export function summarizeConsensus(snapshot) {
  if (!snapshot) return { headline: "No data yet", details: [] };
  const details = [];
  const tx = snapshot.transaction;
  if (tx) {
    details.push({
      label: "Tx status",
      value: String(tx.statusName || tx.status || "unknown"),
    });
    const resultName = tx.result_name || tx.resultName;
    if (resultName) details.push({ label: "Result", value: String(resultName) });
    const votes = tx.consensus_data?.votes;
    if (votes && typeof votes === "object") {
      const entries = Object.entries(votes);
      if (entries.length) {
        details.push({ label: "Validators", value: `${entries.length} nodes` });
        details.push({
          label: "Votes",
          value: entries.map(([addr, v]) => `${short(addr)}:${v}`).join(" · "),
        });
      }
    }
    if (tx.num_of_rounds != null) details.push({ label: "Rounds", value: String(tx.num_of_rounds) });
  }
  const lr = snapshot.lastRound;
  if (lr) {
    const roundNum = lr.round ?? lr[0] ?? lr.roundData?.round;
    if (roundNum != null) details.push({ label: "Consensus round", value: String(roundNum) });
  }
  if (snapshot.canAppeal != null) {
    details.push({ label: "Appealable", value: snapshot.canAppeal ? "yes" : "no" });
  }
  let headline = "Listening for validator rounds…";
  if (snapshot.terminal) headline = "Consensus reached a terminal state";
  else if (tx?.consensus_data?.votes) headline = "Live multi-validator votes";
  else if (lr) headline = "Live multi-validator round data";
  else if (tx) headline = `Transaction ${tx.statusName || "observed"} on GenLayer`;
  return { headline, details, txHash: snapshot.txHash };
}

export function short(addr) {
  if (!addr || typeof addr !== "string") return String(addr ?? "—");
  if (addr.length < 12) return addr;
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
