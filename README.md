# ghost-downloader-cli

**Unofficial headless command-line frontend for [Ghost-Downloader-3](https://github.com/XiaoYouChR/Ghost-Downloader-3)** — the multi-threaded downloader, without the GUI.

> ⚠️ This is **not** the official Ghost-Downloader. It vendors the upstream engine via `git subtree` (`upstream/`) and adds a thin `cli/` layer on top. All credit for the download engine goes to [XiaoYouChR](https://github.com/XiaoYouChR).

## Features

- `gd-cli download <url>` — one-shot multi-threaded download, blocks until done
- `gd-cli daemon` — background engine exposing an **aria2-compatible JSON-RPC** API (port 16800), so anything that speaks aria2 RPC (curl, aria2 clients, scripts) can drive it
- `gd-cli rpc …` — control a running daemon: `add` / `list` / `pause` / `resume` / `status` / `shutdown`
- HTTP(S), FTP, bilibili, m3u8, yt-dlp, huggingface, github packs all load; BitTorrent/ed2k are skipped unless `libtorrent` is installed

## Install

```bash
git clone https://github.com/guyiicn/ghost-downloader-cli
cd ghost-downloader-cli
pip install .
gd-cli --help
```

Requires Python 3.13+.

## Usage

### One-shot download

```bash
gd-cli download https://example.com/big-file.zip -o ~/Downloads --progress
```

### Daemon + RPC

```bash
# Terminal 1
gd-cli daemon

# Terminal 2 (or any aria2 client)
gd-cli rpc add https://example.com/file.iso -o ~/Downloads
gd-cli rpc status <gid>
gd-cli rpc list
gd-cli rpc pause <gid>
gd-cli rpc resume <gid>
gd-cli rpc shutdown
```

The daemon speaks the aria2 JSON-RPC protocol, so plain curl works too:

```bash
curl -s http://127.0.0.1:16800/jsonrpc -d '{"jsonrpc":"2.0","id":"1","method":"aria2.addUri","params":[["https://example.com/f.zip"],{"dir":"/tmp"}]}'
```

RPC methods supported: `aria2.getVersion`, `aria2.getGlobalOption`, `aria2.addUri`, `aria2.tellStatus`, `aria2.pause`, `aria2.unpause`, `aria2.shutdown`.

## How it works

Upstream Ghost-Downloader-3 is a PySide6 GUI app, but its engine (`app/`) is UI-independent: it needs an asyncio loop on a background thread, a config object, and a file-watcher. `cli/` provides:

- `cli/stubs.py` — minimal Qt shims when PySide6 isn't installed (the config classes only need `QStandardPaths`)
- `cli/runner.py` — `CoroutineRunner` wired to a uvloop/asyncio loop thread (no QTimer)
- `cli/engine.py` — engine assembly: config dir `~/.config/ghost-downloader-cli/`, RPC listener on, browser extension off
- `cli/patch_rpc.py` — extends the upstream aria2 RPC service with pause/status/shutdown

Upstream code lives untouched in `upstream/` (subtree). To sync:

```bash
git subtree pull --prefix=upstream https://github.com/XiaoYouChR/Ghost-Downloader-3 main --squash
```

## Differences from the GUI app

- No window, tray, clipboard monitor, browser-extension bridge, or update prompts
- Config: `~/.config/ghost-downloader-cli/config.json` (same keys, no theme/geometry)
- BitTorrent pack needs `pip install libtorrent` separately

## License

GPL-3.0-or-later (inherited from upstream). See [LICENSE](LICENSE) and upstream's [LICENSE](upstream/LICENSE).
