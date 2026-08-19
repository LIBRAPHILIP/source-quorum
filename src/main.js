import {
  setNetwork,
  useEphemeralAccount,
  connectInjectedWallet,
  getActiveAccount,
  getWalletMode,
  probeNetworkHealth,
  getActiveNetworkKey,
} from "./genlayer/client.js";
import { getNetwork, explorerAddressUrl, explorerTxUrl } from "./genlayer/networks.js";
import {
  loadSavedOracle,
  loadSavedBond,
  saveOracle,
  saveBond,
  deployOracle,
  deployBond,
  createClaim,
  lockSources,
  resolveClaim,
  challengeClaim,
  finalizeClaim,
  createBond,
  settleBond,
  withdrawBond,
  readMeta,
  readClaims,
  readSettlement,
  readBonds,
  summarizeConsensus,
  short,
} from "./genlayer/quorum.js";
import deployed from "./deployed.json";

const $ = (id) => document.getElementById(id);

const TEMPLATES = [
  {
    name: "Python Intelligent Contracts",
    question: "Do official GenLayer docs state that Intelligent Contracts are written in Python?",
    claimType: "BINARY",
    allowed: "YES,NO",
    sources: [
      "https://docs.genlayer.com/developers/intelligent-contracts/introduction",
      "https://docs.genlayer.com/developers/intelligent-contracts/first-intelligent-contract",
    ],
  },
  {
    name: "Equivalence Principle",
    question:
      "Is the Equivalence Principle the method GenLayer validators use to reach consensus on non-deterministic Intelligent Contract outputs?",
    claimType: "BINARY",
    allowed: "YES,NO",
    sources: [
      "https://docs.genlayer.com/developers/intelligent-contracts/equivalence-principle",
      "https://docs.genlayer.com/understand-genlayer-protocol/core-concepts/optimistic-democracy/equivalence-principle",
    ],
  },
  {
    name: "Official boilerplate exists",
    question:
      "Does the genlayerlabs GitHub organization publish a public repository named genlayer-project-boilerplate?",
    claimType: "BINARY",
    allowed: "YES,NO",
    sources: [
      "https://github.com/genlayerlabs/genlayer-project-boilerplate",
      "https://github.com/genlayerlabs",
    ],
  },
];

function log(line) {
  const el = $("feedLog");
  const time = new Date().toISOString().slice(11, 19);
  el.textContent = `[${time}] ${line}\n` + el.textContent;
}

function setBusy(busy) {
  document.querySelectorAll("button").forEach((b) => {
    if (b.dataset.keep) return;
    b.disabled = busy;
  });
}

function accountAddress() {
  const acc = getActiveAccount();
  if (!acc) return "";
  return typeof acc === "string" ? acc : acc.address || "";
}

function onProgress(info) {
  if (!info) return;
  if (info.message) {
    $("feedHeadline").textContent = info.message;
    log(info.message);
  }
  if (info.txHash) {
    const net = getNetwork(getActiveNetworkKey());
    log(`tx ${info.txHash}`);
    log(explorerTxUrl(net, info.txHash));
  }
  if (info.address) log(`address ${info.address}`);
  if (info.phase === "consensus") {
    const sum = summarizeConsensus(info);
    $("feedHeadline").textContent = sum.headline;
    for (const row of sum.details) log(`${row.label}: ${row.value}`);
  }
}

function paintSession() {
  const addr = accountAddress();
  const mode = getWalletMode();
  const net = getNetwork(getActiveNetworkKey());
  $("sessionLine").textContent = addr
    ? `${mode} ${short(addr)} on ${net.label}. Fund it before deploying or bonding.`
    : "No account yet. Use ephemeral on Studionet, or a funded wallet on Bradbury.";
  if (addr && !$("bondBeneficiary").value) $("bondBeneficiary").value = addr;
}

function paintExplorer() {
  const net = getNetwork(getActiveNetworkKey());
  const oracle = $("oracleAddress").value.trim();
  const a = $("oracleExplorer");
  if (/^0x[0-9a-fA-F]{40}$/.test(oracle)) {
    a.href = explorerAddressUrl(net, oracle);
    a.textContent = "Explorer contract";
  } else {
    a.href = net.explorer;
    a.textContent = "Explorer";
  }
}

async function refreshDesk() {
  const oracle = $("oracleAddress").value.trim();
  const bond = $("bondAddress").value.trim();
  if (!/^0x[0-9a-fA-F]{40}$/.test(oracle)) {
    $("deskMeta").textContent = "Bind an oracle to load claims via list_claims.";
    $("claimCards").innerHTML = "";
    return;
  }
  try {
    const meta = await readMeta(oracle);
    const claims = await readClaims(oracle, 0, 20);
    $("deskMeta").textContent = `${meta.title || "SourceQuorum"} ${meta.version || ""} · ${
      meta.claim_count || claims.length
    } claims · ${meta.consensus || "on-chain"}`;
    $("claimCards").innerHTML = claims
      .map((c) => {
        if (!c || c.error) return "";
        const sources = Array.isArray(c.sources) ? c.sources.map((s) => s.url).join("<br>") : "";
        return `<article class="card" data-id="${c.claim_id}">
          <h3>#${c.claim_id} · ${escapeHtml(c.question || "")}</h3>
          <p>
            <span class="tag">${c.status}</span>
            <span class="tag">${c.claim_type}</span>
            <span class="tag">${c.outcome || "—"}</span>
          </p>
          <p>${escapeHtml(String(c.reason || ""))} · coverage ${c.coverage ?? "—"}</p>
          <p>${sources}</p>
        </article>`;
      })
      .join("");
    $("claimCards").querySelectorAll(".card").forEach((card) => {
      card.addEventListener("click", () => {
        $("activeClaim").value = card.dataset.id;
        $("bondClaim").value = card.dataset.id;
      });
    });
  } catch (err) {
    $("deskMeta").textContent = err.message || String(err);
  }

  if (/^0x[0-9a-fA-F]{40}$/.test(bond)) {
    try {
      const bonds = await readBonds(bond, 0, 20);
      $("bondCards").innerHTML = bonds
        .map((b) => {
          if (!b || b.error) return "";
          return `<article class="card" data-id="${b.bond_id}">
            <h3>Bond #${b.bond_id} · claim ${b.claim_id}</h3>
            <p>
              <span class="tag">${b.status}</span>
              <span class="tag">${b.expected_outcome}</span>
            </p>
            <p>${short(b.funder)} → ${short(b.beneficiary)} · ${b.amount} wei</p>
          </article>`;
        })
        .join("");
      $("bondCards").querySelectorAll(".card").forEach((card) => {
        card.addEventListener("click", () => {
          $("activeBond").value = card.dataset.id;
        });
      });
    } catch (err) {
      $("bondCards").innerHTML = `<p class="muted">${escapeHtml(err.message)}</p>`;
    }
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function sourcesText() {
  return $("sources")
    .value.split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean)
    .join(",");
}

function applyTemplate(t) {
  $("question").value = t.question;
  $("claimType").value = t.claimType;
  $("allowed").value = t.allowed;
  $("sources").value = t.sources.join("\n");
}

async function run(fn) {
  setBusy(true);
  try {
    await fn();
  } catch (err) {
    console.error(err);
    $("feedHeadline").textContent = "Failed";
    log(err.message || String(err));
  } finally {
    setBusy(false);
    paintSession();
    paintExplorer();
  }
}

function bindStored() {
  const fromFile = deployed?.address || "";
  $("oracleAddress").value = loadSavedOracle() || fromFile || $("oracleAddress").value;
  $("bondAddress").value = loadSavedBond() || deployed?.bond?.address || $("bondAddress").value;
  paintExplorer();
}

$("templates").innerHTML = TEMPLATES.map(
  (t, i) => `<button type="button" data-i="${i}">${t.name}</button>`
).join("");
$("templates").addEventListener("click", (e) => {
  const i = e.target?.dataset?.i;
  if (i != null) applyTemplate(TEMPLATES[Number(i)]);
});

$("networkSelect").addEventListener("change", async () => {
  setNetwork($("networkSelect").value);
  paintSession();
  paintExplorer();
  await probe();
});

$("btnEphemeral").addEventListener("click", () => {
  const acc = useEphemeralAccount();
  paintSession();
  log(`Ephemeral ${acc.address}`);
  log("Fund this account in Studio (Studionet faucet) before deploying.");
});

$("btnWallet").addEventListener("click", () =>
  run(async () => {
    const acc = await connectInjectedWallet();
    paintSession();
    log(`Wallet ${acc.address}`);
  })
);

$("btnBind").addEventListener("click", () => {
  const oracle = $("oracleAddress").value.trim();
  const bond = $("bondAddress").value.trim();
  if (oracle) saveOracle(oracle);
  if (bond) saveBond(bond);
  paintExplorer();
  refreshDesk();
});

$("btnDeployOracle").addEventListener("click", () =>
  run(async () => {
    const { address } = await deployOracle({ onProgress });
    $("oracleAddress").value = address;
    paintExplorer();
    await refreshDesk();
  })
);

$("btnDeployBond").addEventListener("click", () =>
  run(async () => {
    const { address } = await deployBond($("oracleAddress").value.trim(), { onProgress });
    $("bondAddress").value = address;
    await refreshDesk();
  })
);

$("btnCreate").addEventListener("click", () =>
  run(async () => {
    const result = await createClaim(
      $("oracleAddress").value.trim(),
      {
        question: $("question").value,
        claimType: $("claimType").value,
        allowedOutcomes: $("allowed").value,
        minQuorum: $("minQuorum").value,
        minCoverage: $("minCoverage").value,
        toleranceBps: $("tolerance").value,
        challengeBudget: $("challengeBudget").value,
        initialSources: sourcesText(),
      },
      { onProgress }
    );
    log("create_claim submitted. Refresh the desk after acceptance.");
    $("activeClaim").value = $("activeClaim").value || "0";
    $("bondClaim").value = $("activeClaim").value;
    void result;
    await refreshDesk();
  })
);

$("btnLock").addEventListener("click", () =>
  run(async () => {
    await lockSources($("oracleAddress").value.trim(), $("activeClaim").value, { onProgress });
    await refreshDesk();
  })
);

$("btnResolve").addEventListener("click", () =>
  run(async () => {
    const oracle = $("oracleAddress").value.trim();
    const id = $("activeClaim").value;
    await resolveClaim(oracle, id, { onProgress });
    const settlement = await readSettlement(oracle, id);
    log(`settlement ${JSON.stringify(settlement)}`);
    await refreshDesk();
  })
);

$("btnChallenge").addEventListener("click", () =>
  run(async () => {
    await challengeClaim(
      $("oracleAddress").value.trim(),
      $("activeClaim").value,
      $("challengeUrl").value.trim(),
      "challenge",
      $("challengeReason").value.trim(),
      { onProgress }
    );
    await refreshDesk();
  })
);

$("btnFinalize").addEventListener("click", () =>
  run(async () => {
    await finalizeClaim($("oracleAddress").value.trim(), $("activeClaim").value, { onProgress });
    await refreshDesk();
  })
);

$("btnCreateBond").addEventListener("click", () =>
  run(async () => {
    await createBond(
      $("bondAddress").value.trim(),
      {
        claimId: $("bondClaim").value,
        expectedOutcome: $("bondOutcome").value,
        numericMin: $("bondMin").value,
        numericMax: $("bondMax").value,
        beneficiary: $("bondBeneficiary").value,
        amountGen: $("bondAmount").value,
      },
      { onProgress }
    );
    await refreshDesk();
  })
);

$("btnSettle").addEventListener("click", () =>
  run(async () => {
    await settleBond($("bondAddress").value.trim(), $("activeBond").value, { onProgress });
    await refreshDesk();
  })
);

$("btnWithdraw").addEventListener("click", () =>
  run(async () => {
    await withdrawBond($("bondAddress").value.trim(), $("activeBond").value, { onProgress });
    await refreshDesk();
  })
);

$("btnRefresh").addEventListener("click", () => refreshDesk());

async function probe() {
  const health = await probeNetworkHealth();
  $("netDot").className = "dot " + (health.ok ? "ok" : "bad");
  $("healthLine").textContent = health.ok
    ? `${health.label} reachable · chain ${health.remoteChainId} · ${health.latencyMs}ms`
    : `${health.label} unreachable: ${health.error}`;
}

bindStored();
setNetwork($("networkSelect").value);
paintSession();
applyTemplate(TEMPLATES[0]);
probe();
refreshDesk();
