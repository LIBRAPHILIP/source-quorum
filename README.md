# SourceQuorum

**Public-fact bonds on [GenLayer](https://genlayer.com).** Independent official sources must agree under validator consensus before GEN moves.

This is a complete Project: Intelligent Contracts plus an app that actually talks to GenLayer.

| | |
|---|---|
| Live app | https://source-quorum.vercel.app |
| GitHub | https://github.com/LIBRAPHILIP/source-quorum |
| Oracle contract | [`contracts/source_quorum.py`](contracts/source_quorum.py) |
| Bond contract | [`contracts/quorum_bond.py`](contracts/quorum_bond.py) |
| Submission notes | [`docs/PROJECT.md`](docs/PROJECT.md) |
| Consensus spec | [`docs/CONSENSUS.md`](docs/CONSENSUS.md) |

## The problem

Two parties can agree that “the public record will decide” and still fight about what that record said. A single URL, a single model, or a single counterparty is a single point of trust.

SourceQuorum makes the source set explicit and on-chain. Each validator re-fetches every locked page. Settlement is quorum math, not a better LLM paragraph.

## What the app does

1. Connect an ephemeral Studionet account or a wallet.
2. Deploy **SourceQuorum** and **QuorumBond** (or bind existing addresses).
3. Open a typed public fact with two or more live HTTPS sources.
4. Lock the source set.
5. **Resolve** — `writeContract("resolve")` → `waitForTransactionReceipt` while the UI streams `getTransaction` / `getLastRoundData`.
6. Challenge with an extra source, or finalize.
7. Bond GEN against an expected outcome. After settlement, settle and withdraw once.

The frontend never invents validator votes. If the RPC has no round data yet, the feed says so.

## Real-world data

Templates use live official pages, not fixtures:

- GenLayer Intelligent Contract docs
- Equivalence Principle docs
- The public `genlayerlabs/genlayer-project-boilerplate` repository

Anyone can paste other authoritative HTTPS sources (agency pages, specs, announcements).

## How consensus is used

```
locked sources
  → each validator: gl.nondet.web.get(url) + extract one fact
  → compare url set, fetch_ok, outcome, numeric_value
  → UNRESOLVED vs a concrete outcome is a reject
  → compute_quorum() after consensus
  → QuorumBond reads get_settlement (no LLM)
```

## Run locally

```bash
npm install
npm run dev
```

Open the Vite URL. Studionet is the default network.

```bash
npm run test:math
npm run build
```

On-chain deploy (funded account):

```bash
npm run deploy:studionet
# or
PRIVATE_KEY=0x… npm run deploy:bradbury
```

Addresses land in `src/deployed.json` and `deployments/`.

## Explorer URL for the portal

After deploy, the required **GenLayer Explorer Contract** field is:

```
https://explorer-bradbury.genlayer.com/address/0x<40 hex chars>
```

or, on Studio:

```
https://explorer-studio.genlayer.com/address/0x<40 hex chars>
```

Not GitHub. Not Vercel. Not `/tx/…`. Not `explorer.genlayer.com`.

## License

MIT
