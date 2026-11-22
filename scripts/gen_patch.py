#!/usr/bin/env python3
"""
DSH Patch Generator — 从模型清单生成 DSH 的合并 provider patch

职责
----
把「本地模型（Ollama）」和「免费云端模型（model_sync.py 维护的清单）」
合并进同一个 DSH patch，实现一个下拉里同时看到两边、按需切换。

为什么需要它
------------
代理网关生成的 patch 会整体替换 providers 对象（不是深合并），会把本地
provider 冲掉。所以自己生成一份包含两个 provider 的 patch，绕开这个问题。

数据流
------
  ollama list ──────────────> 本地模型段
  cloud-models.json ────────> 云端模型段
              gen_patch.py ──> fcc-merged.patch.yml

用法
----
    python3 gen_patch.py --config config.json --dry-run
    python3 gen_patch.py --config config.json

纯标准库。
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path

VERSION = "1.0.0"

DEFAULT_LOCAL_MODELS = [
    {"id": "qwen3:8b", "name": "Qwen3 8B", "contextWindow": 131072, "maxTokens": 8192},
]

DEFAULTS = {
    "output": {
        "patch_path": "~/.dsh/fcc-merged.patch.yml",
        "format": "json",           # json | yaml（DSH 两种都认）
        "backup": True,
    },
    "local": {
        "enabled": True,
        "provider_id": "local-ollama",
        "display_name": "Local Ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "api": "openai-completions",
        "api_key_env": "OLLAMA_API_KEY",
        "models_command": "ollama list",   # 留空则用 models 静态列表
        "models": DEFAULT_LOCAL_MODELS,
        "default_input": ["text"],
    },
    "cloud": {
        "enabled": True,
        "provider_id": "free-claude-code",
        "display_name": "Free Cloud Models",
        "base_url": "http://127.0.0.1:8082/v1",
        "api": "openai-responses",
        "api_key_env": "FCC_DSH_API_KEY",
        "models_path": "~/.dsh/cloud-models.json",
    },
    "default_model": {
        "provider": "local-ollama",
        "model": "qwen3:8b",
    },
    "disable_builtin": ["llm-deepseek", "llm-deepseek-account", "web-search-deepseek"],
    "target": {
        "mode": "local", "host": "", "user": "", "port": 22,
        "ssh_key": "", "ssh_options": "",
    },
}


def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULTS))
    if path and Path(path).exists():
        cfg = deep_merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


def parse_ollama_list(text: str) -> list[dict]:
    """把 `ollama list` 输出解析成模型对象。跳过表头。"""
    models = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        mid = parts[0]
        models.append({
            "id": mid, "name": mid,
            "contextWindow": 131072, "maxTokens": 8192,
        })
    return models


def build_patch(cfg) -> list[dict]:
    providers = {}

    if cfg["local"]["enabled"]:
        models = cfg["local"]["models"]
        cmd = cfg["local"]["models_command"]
        if cmd:
            try:
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                if p.returncode == 0 and p.stdout.strip():
                    models = parse_ollama_list(p.stdout)
            except Exception:
                pass  # 拉取失败用静态列表兜底
        providers[cfg["local"]["provider_id"]] = {
            "displayName": cfg["local"]["display_name"],
            "apiKeyEnv": cfg["local"]["api_key_env"],
            "api": cfg["local"]["api"],
            "baseURL": cfg["local"]["base_url"],
            "models": models,
            "defaultInput": cfg["local"]["default_input"],
        }

    if cfg["cloud"]["enabled"]:
        path = os.path.expanduser(cfg["cloud"]["models_path"])
        cloud_models = []
        if Path(path).exists():
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                cloud_models = data.get("models", []) if isinstance(data, dict) else data
            except Exception:
                pass
        providers[cfg["cloud"]["provider_id"]] = {
            "displayName": cfg["cloud"]["display_name"],
            "apiKeyEnv": cfg["cloud"]["api_key_env"],
            "api": cfg["cloud"]["api"],
            "baseURL": cfg["cloud"]["base_url"],
            "models": cloud_models,
        }

    patch = [
        {
            "id": "llm-pi-ai",
            "name": "@deepseek-ai/dsh-llm-pi-ai",
            "config": {"providers": providers},
        },
        {
            "id": "agent-default-model",
            "name": "@deepseek-ai/dsh-agent-default-model",
            "config": {
                "provider": cfg["default_model"]["provider"],
                "model": cfg["default_model"]["model"],
            },
        },
    ]
    for pid in cfg["disable_builtin"]:
        patch.append({"id": pid, "disabled": True})
    return patch


def to_yaml(patch: list[dict]) -> str:
    """极简 JSON→YAML 序列化，够 DSH patch 用；复杂结构回退用 JSON 块。"""
    lines = []
    for entry in patch:
        if entry.get("disabled"):
            lines.append(f"- id: {entry['id']}")
            lines.append("  disabled: true")
            continue
        lines.append(f"- id: {entry['id']}")
        lines.append(f"  name: {entry.get('name', '')}")
        cfg = entry.get("config", {})
        if "providers" in cfg:
            lines.append("  config:")
            lines.append("    providers:")
            for pid, p in cfg["providers"].items():
                lines.append(f"      {pid}:")
                lines.append(f"        displayName: {p['displayName']}")
                lines.append(f"        apiKeyEnv: {p['apiKeyEnv']}")
                lines.append(f"        api: {p['api']}")
                lines.append(f"        baseURL: {p['baseURL']}")
                if "defaultInput" in p:
                    lines.append("        defaultInput: [" + ", ".join(p["defaultInput"]) + "]")
                lines.append("        models:")
                for m in p["models"]:
                    lines.append(f"          - id: {m['id']}")
                    for k in ("name", "contextWindow", "maxTokens"):
                        if k in m:
                            lines.append(f"            {k}: {m[k]}")
                    if "reasoningEfforts" in m:
                        lines.append("            reasoningEfforts:")
                        for rk, rv in m["reasoningEfforts"].items():
                            lines.append(f"              {rk}: {rv}")
        else:
            lines.append("  config:")
            for k, v in cfg.items():
                lines.append(f"    {k}: {v}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="DSH Patch Generator")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args()
    cfg = load_config(args.config)
    patch = build_patch(cfg)

    fmt = cfg["output"]["format"]
    content = json.dumps(patch, ensure_ascii=False, indent=2) + "\n" if fmt == "json" else to_yaml(patch)

    if args.dry_run:
        print(content)
        return 0

    out = os.path.expanduser(cfg["output"]["patch_path"])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if cfg["output"]["backup"] and Path(out).exists():
        shutil.copy(out, out + ".bak-" + date.today().isoformat())
    Path(out).write_text(content, encoding="utf-8")

    local_n = len(patch[0]["config"]["providers"].get(cfg["local"]["provider_id"], {}).get("models", []))
    cloud_n = len(patch[0]["config"]["providers"].get(cfg["cloud"]["provider_id"], {}).get("models", []))
    print(f"生成 patch: {out}")
    print(f"  本地模型 {local_n} + 云端模型 {cloud_n}")
    print("验证: dsh --profile web --dump-config")
    return 0


if __name__ == "__main__":
    sys.exit(main())
