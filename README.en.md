# DSH Free Model Bridge

[![Stars](https://img.shields.io/github/stars/zhanglmyf/dsh-free-model-bridge?style=social)](https://github.com/zhanglmyf/dsh-free-model-bridge/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)

[中文](README.md) | **English**

Auto-load and continuously refresh **free cloud models** for DSH (DeepSeek Harness) — solves the stale static model list problem (dead entries, no new models).

## How it works

1. Fetch catalog from the OpenAI-compatible gateway's `/v1/models`
2. Filter out non-chat models (embedding / rerank / moderation / vision…)
3. Rate-limited liveness probe (serial, ≥1.5s apart, 1 request each; **circuit-break on 429**)
4. Remove dead (404/410), add new verified, keep timeouts
5. Regenerate a merged DSH patch (local + cloud providers in one)
6. Optional scheduled maintenance (systemd / cron / launchd / Windows)

## Quick start

```bash
cp config.example.json config.json
python3 scripts/model_sync.py --config config.json --dry-run   # preview
python3 scripts/model_sync.py --config config.json             # sync
python3 scripts/gen_patch.py --config config.json              # write merged patch
dsh --profile web --dump-config                                # verify
bash templates/install-schedule.sh systemd                     # optional scheduler
```

## Deploy modes

Set `target.mode`: `local` (this machine) / `ssh` (LAN or remote, supports jump host).

## Does it work with desktop DSH?

The model-list logic is portable, but the injection path differs: one-click for CLI/Web, one manual merge for the official desktop app.

| DSH form | Support |
|---|---|
| CLI / Web UI (`npx @deepseek-ai/dsh web`) | **Full**: load the generated patch with `dsh web --patch <file>`; `restart_command` works too. |
| Official desktop app (Windows x64 / macOS Apple Silicon) | **Partial**: it bundles Harness and still uses `~/.dsh`, but exposes no `--patch` flag. Merge the generated patch into `~/.dsh/profiles/<profile>/cordis.patch.yml` (our JSON output is valid YAML), then restart the app. |
| Mobile | No native DSH; browser access to a remote Web UI only. No iOS/Android client here. |

Desktop notes: the sync scripts are Python 3.9+ and run on Windows/macOS/Linux — use absolute paths on Windows. `local.models_command: "ollama list"` needs a local Ollama CLI; leave it empty and use `local.models` if you have none. Gateway URLs must be reachable **from the machine running the script**. Back up `~/.dsh` before merging, since desktop upgrades may migrate profiles.

**Verification status**: end-to-end verified on Ubuntu + DSH Web/CLI (filtering, probing, 429 circuit-break, list write-back, dual-provider patch, SSH mode). The Windows/macOS desktop apps were analysed for config-path compatibility but **not run on a real desktop install**. PRs with desktop verification are welcome.

## Docs

- [How it works](docs/HOW-IT-WORKS.md)
- [Deploy modes](docs/DEPLOY-MODES.md)
- [Configuration](docs/CONFIGURATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Related projects

- [xiaomi-speaker-workbuddy-bridge](https://github.com/zhanglmyf/xiaomi-speaker-workbuddy-bridge) — Turn any Xiaomi speaker into a voice AI assistant
- [dsh-universal-installer](https://github.com/zhanglmyf/dsh-universal-installer) — Deploy DeepSeek Harness anywhere
- [dsh-free-model-bridge](https://github.com/zhanglmyf/dsh-free-model-bridge) **(this project)** — Auto-load free cloud models into DSH
- [lan-transparent-proxy](https://github.com/zhanglmyf/lan-transparent-proxy) — One-click LAN transparent proxy

## License

MIT.
