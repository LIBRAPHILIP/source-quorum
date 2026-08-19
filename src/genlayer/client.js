/**
 * Real GenLayer clients only. Reads and writes hit GenLayer RPC.
 * There is no simulated consensus path.
 */
import { createClient, createAccount } from "genlayer-js";
import { getNetwork } from "./networks.js";

let readClient = null;
let writeClient = null;
let activeNetworkKey = "studionet";
let activeAccount = null;
let walletMode = "none";

export function getActiveNetworkKey() {
  return activeNetworkKey;
}

export function getActiveAccount() {
  return activeAccount;
}

export function getWalletMode() {
  return walletMode;
}

export function getReadClient() {
  if (!readClient) {
    readClient = createClient({ chain: getNetwork(activeNetworkKey).chain });
  }
  return readClient;
}

export function getWriteClient() {
  if (!writeClient) {
    throw new Error("Connect a wallet or create an ephemeral account first.");
  }
  return writeClient;
}

export function setNetwork(key) {
  activeNetworkKey = key;
  const net = getNetwork(key);
  readClient = createClient({ chain: net.chain });
  writeClient = null;
  if (activeAccount) rebuildWriteClient();
  return net;
}

function rebuildWriteClient() {
  const net = getNetwork(activeNetworkKey);
  if (walletMode === "injected" && typeof window !== "undefined" && window.ethereum) {
    writeClient = createClient({
      chain: net.chain,
      account: activeAccount,
      provider: window.ethereum,
    });
  } else if (activeAccount) {
    writeClient = createClient({
      chain: net.chain,
      account: activeAccount,
    });
  }
}

export function useEphemeralAccount() {
  const account = createAccount();
  activeAccount = account;
  walletMode = "ephemeral";
  rebuildWriteClient();
  return {
    address: account.address,
    privateKey: account.privateKey ?? account?.account?.privateKey,
    mode: walletMode,
  };
}

export async function connectInjectedWallet() {
  if (typeof window === "undefined" || !window.ethereum) {
    throw new Error("No injected wallet found. Install MetaMask or use an ephemeral account.");
  }
  const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
  if (!accounts?.length) throw new Error("Wallet returned no accounts");
  activeAccount = accounts[0];
  walletMode = "injected";
  const net = getNetwork(activeNetworkKey);
  writeClient = createClient({
    chain: net.chain,
    account: accounts[0],
    provider: window.ethereum,
  });
  try {
    if (typeof writeClient.connect === "function") {
      await writeClient.connect(net.connectName);
    }
  } catch (err) {
    console.warn("client.connect failed", err);
    await ensureWalletChain(net);
  }
  return { address: accounts[0], mode: walletMode };
}

async function ensureWalletChain(net) {
  const chainIdHex = "0x" + net.chain.id.toString(16);
  try {
    await window.ethereum.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: chainIdHex }],
    });
  } catch (switchError) {
    if (switchError.code === 4902 || switchError?.data?.originalError?.code === 4902) {
      await window.ethereum.request({
        method: "wallet_addEthereumChain",
        params: [
          {
            chainId: chainIdHex,
            chainName: net.chain.name,
            nativeCurrency: net.chain.nativeCurrency,
            rpcUrls: [net.rpc],
            blockExplorerUrls: net.explorer ? [net.explorer] : [],
          },
        ],
      });
    } else {
      throw switchError;
    }
  }
}

export async function initializeConsensus() {
  const client = writeClient || readClient || getReadClient();
  if (typeof client.initializeConsensusSmartContract === "function") {
    await client.initializeConsensusSmartContract();
  }
}

export async function probeNetworkHealth() {
  const net = getNetwork(activeNetworkKey);
  const started = performance.now();
  const out = {
    key: net.key,
    label: net.label,
    rpc: net.rpc,
    chainId: net.chain.id,
    ok: false,
    latencyMs: null,
    remoteChainId: null,
    blockNumber: null,
    error: null,
  };
  try {
    const client = getReadClient();
    if (typeof client.getBlockNumber === "function") {
      out.blockNumber = await client.getBlockNumber();
    }
    const res = await fetch(net.rpc, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }),
    });
    out.latencyMs = Math.round(performance.now() - started);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    if (body.error) throw new Error(body.error.message || "RPC error");
    out.remoteChainId = parseInt(body.result, 16);
    out.ok = true;
  } catch (e) {
    out.error = e.message || String(e);
    out.latencyMs = Math.round(performance.now() - started);
  }
  return out;
}
