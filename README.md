# Unwind

A local workbench for **following money across blockchains** and **taking programs apart**, with an Obsidian-style vault where every wallet, case and binary becomes a linked Markdown note. The same tools are exposed to your coding agent over MCP (like REA).

Python standard library + plain JS, no build step, no accounts. Runs entirely on your computer. The only dependency is the official Claude SDK (for Claude in the AI assistant); the launcher installs it into `./.deps` on first run.

Works on macOS (full binary analysis uses Xcode's command-line tools: `xcode-select --install`). Chain tracing, forensics, malware triage of scripts and Windows/Linux files, the vault and the AI assistant also work on Linux.

## Download

Get the installer for your computer from the [latest release](https://github.com/jukeiss/unwind/releases/latest):

| Your computer | Download |
|---|---|
| Mac (Apple Silicon or Intel) | `.dmg` → drag Unwind to Applications |
| Windows | `Setup-x64.exe` (installer) or `portable-x64.exe` (no install) |
| Ubuntu / Debian | `.deb` → `sudo apt install ./Unwind-*.deb` |
| Fedora / openSUSE | `.rpm` → `sudo dnf install ./Unwind-*.rpm` |
| Any Linux | `.AppImage` (make it executable, run it) or `.flatpak` (`flatpak install --user Unwind-*.flatpak`) |

The builds aren't code-signed yet: on macOS right-click the app → **Open** the first time; on Windows click **More info** → **Run anyway**. Installed apps keep your notes in `~/Unwind Vault`.

## Run from source

```bash
git clone https://github.com/jukeiss/unwind.git
cd unwind
./unwind
```

It opens `http://127.0.0.1:7878`. Options: `--port 9000`, `--no-open`. Your notes go in `./vault` (never committed). Use another folder with `UNWIND_VAULT=/path/to/folder ./unwind`.

## Bring your own keys

Everything works without keys. Keys make it faster and unlock more: an AI model, Etherscan (18 more EVM chains), a Solana RPC such as Helius, VirusTotal / MalwareBazaar.

- **Import them in one go:** Settings → *Import your API keys*. Paste or drop a `.env` file, shell exports, a JSON object or bare keys. Unwind recognises standard names (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `NANOGPT_API_KEY`, `GLM_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `ETHERSCAN_API_KEY`, `HELIUS_API_KEY`, `SOLANA_RPC_URL`, `VIRUSTOTAL_API_KEY`, `MALWAREBAZAAR_API_KEY`, …) and prefixes (`sk-ant-`, `sk-or-`, `gsk_`, `AIza`, …).
- **Or use environment variables:** `export DEEPSEEK_API_KEY=... && ./unwind`.
- Keys are stored in `~/.config/unwind/settings.json` with owner-only permissions, and each one is sent only to its own service. *Export .env* gives you a masked copy to share or a full copy to move to another machine.

## Connect your own APIs

Settings → *Your own APIs*: import any OpenAPI / Swagger spec (URL or pasted JSON) or enter endpoints by hand (`GET /address/{address}?chain Look up an address`). Each API gets a **Try** panel and becomes a tool the AI assistant and MCP clients can call (`api_<name>`). Connectors are **read-only by default**: POST/PUT/PATCH/DELETE run only if you tick *Allow changes*. Definitions and keys live in `~/.config/unwind/connectors.json` (owner-only).

## Connect your coding agent

```bash
claude mcp add unwind -- python3 /full/path/to/unwind/unwind_mcp.py
```

Then ask things like *"Use unwind to trace where the money from bc1q… went, 3 hops, and save the case to my vault"* or *"Use unwind to open Calculator.app and find the code behind the % button."* 29 tools: `bin_*`, `chain_*`, `exposure`, `utxo_*`, `peel_chain`, `cluster`, `sweeps`, `links`, `match_amounts`, `pass_through`, `vault_*`.

## What's in it

**Workspace (Obsidian-style)**: ribbon, file tree, tabs, backlinks / outgoing links / unlinked mentions, `[[wikilink]]` autocomplete, callouts, `#tags`, graph view, ⌘K command palette, ⌘O quick switcher. The vault is plain Markdown, so you can open the folder in Obsidian too.

**Chains**: 27 with no key, ~45 with a free Etherscan key (Settings).
- UTXO: Bitcoin, Litecoin, Bitcoin testnet
- EVM via Blockscout: Ethereum, Optimism, zkSync, Unichain, Soneium, Ink, Hemi, Metal, Mode, Lisk, Celo, Rootstock, Plume, Fuse, testnets
- EVM via Routescan: Avalanche, Blast, Mantle
- EVM via Etherscan key: Base, Arbitrum, Polygon, BNB, Linea, Scroll, Gnosis, Sonic, Berachain, Taiko, Abstract, World Chain, opBNB, Moonbeam, ApeChain, Sei, Arbitrum Nova, Fraxtal
- Solana, Tron, XRP Ledger, TON
- Monero: transaction inspection only (see limits)

**Tracing**: multi-hop, in / out / both, per-hop fan-out, minimum USD. Stops at exchanges, contracts and mixers. On UTXO chains, change outputs are followed as the same owner, so peel chains show up as dashed runs. Results are drawn as a layered flow graph.

**Flags**: whale, large, small, empty, known, exchange, DEX/router, bridge, mixer, mixer nearby, CoinJoin, contract, smart wallet (EIP-7702), service, change, deposit address, destination tag, fresh, high activity, scam flag, historic, mined coins, in your vault.

**Forensics lab**
- Change detection: address reuse, script-type match, round-number payment and unnecessary-input checks, with a confidence and reasons
- Peel-chain detection
- Clustering by common-input ownership plus change; CoinJoins are skipped
- Coin history: coin ID (`txid:vout`), creating block, the mining pool decoded from the coinbase tag, where it was spent, and ancestry
- CoinJoin detection: Whirlpool, Wasabi-style, JoinMarket
- Mixer exposure, first seen, first funder
- Same-owner links that are cryptographically certain (EVM↔all EVM, EVM↔Tron, BTC↔LTC)
- Amount matching across chains with false-positive control: round or ambiguous matches are downgraded, weak ones hidden
- Pass-through (layering hop) detection
- Exchange deposit-address detection

**Binary workbench**: identity, architectures, code signature, linked libraries, sections, entry point. Functions come from symbols plus `LC_FUNCTION_STARTS`, so stripped binaries work too. Also strings with presets, imports, highlighted disassembly with clickable calls and back navigation, string→code cross-references, hex view, and starred "functions of interest" saved to the vault.

## AI assistant (⌘J)

Connect any of 21 providers in **Settings → AI models**: Claude (official Anthropic SDK, bundled in `.deps/`), OpenAI, DeepSeek, NanoGPT, GLM (Zhipu and Z.ai), OpenRouter, Gemini, Groq, Mistral, xAI, Moonshot/Kimi, Qwen, Together, Fireworks, Perplexity, Cerebras, SiliconFlow, Ollama, LM Studio, or any OpenAI-compatible endpoint. Paste a key, press **Models** to list what you can use, **Test**, and star a default.

The assistant panel knows which tab you're looking at and can call Unwind's own tools (binaries, chains, forensics, vault) by itself. **✦ Explain with AI** in the disassembler sends the current function's code, strings, calls and callers. **Ask AI to assess** in a malware report sends the triage findings. Chats save to `AI/` in the vault.

## Reverse engineering & malware analysis

- Objective-C method names recovered from metadata even in stripped binaries (including arm64e relative method lists), so `sub_…` becomes `-[Document saveToURL:…]`
- Swift and C++ symbols demangled everywhere
- **Classes** tab: Objective-C/Swift classes, methods (click to disassemble), fields
- **Malware triage** tab, static only (the file is read and never run): hashes, entropy and packing, code signature, notarization, Gatekeeper, hardened runtime, entitlements, quarantine flag, app-bundle launch items and scripts, capabilities mapped to MITRE ATT&CK, indicators (URLs, domains, IPs, crypto wallets, webhooks, bot tokens, onion links), YARA (`brew install yara`; rules in the vault's `YARA/` folder), a risk score with reasons, and **hidden strings** (base64, hex and single-byte-XOR payloads decoded). Works on Mach-O, Windows PE, ELF and scripts.
- Optional hash-only reputation lookups (VirusTotal, MalwareBazaar). Only the SHA-256 is sent.
- Save any report to the vault (`Malware/`), with wallet addresses linked to wallet notes.

## Wallet history

The **History** tab reads a wallet's full history (**Load everything** pages back to its first transaction) and turns each transaction into an action: bought X with Y, sold, swapped, NFT bought/sold/minted, contract or token created, bridged, approved, sent, received, mined, spam airdrop. It shows what the wallet bought and sold, its NFTs, what it created, who it deals with most, fees, an activity heatmap and a filterable day-by-day timeline. EVM chains include internal transfers, and Etherscan-family chains include NFTs.

In traces, click a wallet and use **Expand →** / **← Expand** to grow the graph, **Hide** to drop noise, and **Label** to name a wallet everywhere.

## Obsidian extras

Note outline in the sidebar, bookmarks (⌘K → "Bookmark"), daily notes (⌘D → `Journal/`), and templates (⌘K → "New note from template": wallet investigation, malware sample, reverse engineering, daily).

## Limits (read these)

- **Monero** hides senders, receivers and amounts. Unwind can't look up a Monero wallet or link Monero wallets, and doesn't pretend to. It shows public transaction fingerprints, and amount matching works on the transparent chains before and after a swap.
- Heuristics are heuristics. Every result says which rule fired and how sure it is: "certain" means the same key, while "strong" or "possible" are leads to verify.
- Public explorers are rate-limited: deep traces take 20–60 s.
- Binary analysis is read-only. It's for understanding software, interoperability and security research on programs you're allowed to examine. It doesn't patch binaries or remove protections.

## Privacy

Lookups go straight from your Mac to public APIs (Blockstream, mempool.space, Blockscout, Routescan, Etherscan if you add a key, public Solana, Tron, XRP and TON endpoints, xmrchain.net, CoinGecko). The server binds to 127.0.0.1 only, checks the Host header, and requires a per-launch token, so other websites can't call it. The Etherscan key is stored in `~/.config/unwind/settings.json` with permissions 600.

## Files

| File | What it does |
|---|---|
| `app.py` | Local web server + API |
| `unwind_mcp.py` | MCP server for coding agents |
| `chaintrace.py` | Chain adapters, detection, wallets, activity, tracing, flags |
| `forensics.py` | Coins, coin history, mining pool, CoinJoin, exposure |
| `heuristics.py` | Change detection, peel chains, clustering, deposit sweeps |
| `correlate.py` | Same-key links, amount matching, pass-through |
| `dissect.py` | Binary analysis |
| `vault.py` | Markdown vault: notes, links, backlinks, graph, writers |
| `ui/` | The interface |
