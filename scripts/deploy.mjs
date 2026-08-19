/**
 * Deploy SourceQuorum (and optionally QuorumBond) with genlayer-js.
 *
 *   node scripts/deploy.mjs studionet
 *   node scripts/deploy.mjs bradbury
 *   PRIVATE_KEY=0x… node scripts/deploy.mjs bradbury --with-bond
 *
 * QuorumBond is constructed with the freshly deployed oracle address.
 */
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studionet, testnetBradbury, localnet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

const NETWORKS = {
  studionet,
  bradbury: testnetBradbury,
  testnetBradbury,
  localnet,
};

function pickAddress(receipt) {
  return (
    receipt?.data?.contract_address ||
    receipt?.to_address ||
    receipt?.txDataDecoded?.contractAddress ||
    receipt?.contractAddress ||
    receipt?.data?.contractAddress ||
    null
  );
}

async function deployOne(client, relPath, args, label) {
  const code = new Uint8Array(readFileSync(path.join(root, relPath)));
  console.log(`Deploying ${label}…`);
  const txHash = await client.deployContract({ code, args });
  console.log("  tx:", txHash);
  const receipt = await client.waitForTransactionReceipt({
    hash: txHash,
    status: TransactionStatus.ACCEPTED,
    retries: 400,
    interval: 4000,
    fullTransaction: true,
  });
  const address = pickAddress(receipt);
  console.log("  status:", receipt.statusName || receipt.status);
  console.log("  consensus:", receipt.result_name || receipt.result);
  if (!address) {
    console.error(JSON.stringify(receipt, (_, v) => (typeof v === "bigint" ? v.toString() : v), 2));
    throw new Error(`no address for ${label}`);
  }
  console.log("  address:", address);
  return { address, txHash, receipt };
}

async function main() {
  const argv = process.argv.slice(2).filter((a) => a !== "--with-bond");
  const withBond = process.argv.includes("--with-bond");
  const netName = (argv[0] || "studionet").toLowerCase();
  const chain = NETWORKS[netName];
  if (!chain) {
    console.error("Use: studionet | bradbury | localnet");
    process.exit(1);
  }

  let account;
  const pk = process.env.PRIVATE_KEY || process.env.GENLAYER_PRIVATE_KEY;
  if (pk) {
    const { privateKeyToAccount: pka } = await import("viem/accounts");
    account = pka(pk.startsWith("0x") ? pk : `0x${pk}`);
    console.log("Account:", account.address);
  } else {
    account = createAccount();
    console.log("Ephemeral account:", account.address);
    console.log("Fund it on Studionet (Studio faucet) or set PRIVATE_KEY.");
  }

  const client = createClient({ chain, account });
  await client.initializeConsensusSmartContract();

  const oracle = await deployOne(client, "contracts/source_quorum.py", [], "SourceQuorum");
  const payload = {
    primitive: "SourceQuorum",
    version: "1.0.0-source-quorum",
    address: oracle.address,
    chainId: chain.id,
    network: netName,
    deployTx: oracle.txHash,
    deployedAt: new Date().toISOString(),
  };

  if (withBond) {
    const bond = await deployOne(
      client,
      "contracts/quorum_bond.py",
      [oracle.address],
      "QuorumBond"
    );
    payload.bond = {
      address: bond.address,
      deployTx: bond.txHash,
      oracle: oracle.address,
    };
  }

  mkdirSync(path.join(root, "deployments"), { recursive: true });
  const out = path.join(root, "deployments", `source-quorum-${chain.id}.json`);
  writeFileSync(out, JSON.stringify(payload, null, 2));
  writeFileSync(path.join(root, "src", "deployed.json"), JSON.stringify(payload, null, 2));
  console.log("\nWrote", out);
}

main().catch((err) => {
  console.error("Deploy failed:", err);
  process.exit(1);
});
