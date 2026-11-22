#!/usr/bin/env python3
"""
Free Model Bridge — DSH 免费云端模型清单自动同步器

它解决什么问题
--------------
把免费云端模型（经 OpenAI 兼容代理网关暴露，如 FCC / 其他）接进 DSH 后，
provider patch 里的模型清单是静态 JSON：
  - 上游目录刷新不会回写它
  - 模型下架/改名后，下拉里留下点了报 404 的僵尸项
  - 新上线的免费模型不会自动出现

本脚本定期做：拉目录 → 过滤对话模型 → 限速探活 → 剔除失效/补入新模型 →
写回模型清单 JSON（本地模型段不碰）→ 调 gen_patch.py 重生成 patch → 可选重启。

数据流
------
  catalog 端点 ──过滤──> 候选模型 ──限速探活──> 模型清单 models.json
                                                     │
                                          gen_patch.py 读取
                                                     ↓
                                          DSH patch（云端段 + 本地段）

安全铁律（血泪教训，务必保留）
------------------------------
1. **绝不并发探测**：串行 + 每次间隔 >= 1.5s，避免打爆速率限制。
2. **429 立即熔断**：命中 429 就停止本轮，只保留已验证结果，不重试。
3. **超时不删**：个别慢模型超时属正常，保留原状，不误杀。
4. **404/410 才剔除**：只有明确"模型没了"才删。
5. **先备份**：写清单前备份，随时可回滚。
6. **不碰 key**：清单里不含凭证；key 通过环境变量/本地文件单独注入。

用法
----
    python3 model_sync.py --config config.json --dry-run    # 只拉清单+过滤
    python3 model_sync.py --config config.json              # 完整同步
    python3 model_sync.py --config config.json --no-restart # 同步但不重启
    python3 model_sync.py --config config.json --scheduled  # 定时模式：当天成功过跳过

纯标准库（Python 3.9+）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

VERSION = "1.0.0"

DEFAULTS = {
    "bridge": {
        "catalog_url": "http://127.0.0.1:8082/v1/models",
        "chat_url": "http://127.0.0.1:8082/v1/chat/completions",
        "auth_header": "Authorization: Bearer local",   # 占位；按需改
    },
    "models": {
        "list_path": "~/.dsh/cloud-models.json",        # 模型清单（本脚本维护）
        "id_prefix": "nvidia_nim/",                     # 从目录 id 截取规范 id 的起点；留空不截取
        "model_template": {                             # 新模型对象的默认字段
            "name": "",
            "contextWindow": 200000,
            "reasoningEfforts": {
                "off": 0, "minimal": 1024, "low": 2048,
                "medium": 4096, "high": 8192, "xhigh": 16384, "max": 32768,
            },
        },
        "keep_unverified": True,                        # 超时/未知是否保留（宁留勿删）
    },
    "filter": {
        "exclude_keywords": [
            "embed", "rerank", "guard", "safety", "pii", "translat",
            "calibrat", "moderation", "vision", "gliner", "ocr",
        ],
        "max_models": 40,               # 一轮最多探活多少个（速率保护）
    },
    "probe": {
        "interval_sec": 1.5,
        "timeout_sec": 45,
        "max_tokens": 1,
        "circuit_break_on_429": True,
    },
    "post_sync": {
        "gen_patch_command": "",        # 如 "python3 ~/.dsh/gen_patch.py --config ..."；留空跳过
        "restart_command": "",          # 如 "systemctl --user restart dsh-web"；留空不重启
    },
    "schedule": {
        "success_marker": "~/.dsh/.model-sync-success-date",
    },
    "target": {                          # 与 DSH Universal Installer 同构
        "mode": "local", "host": "", "user": "", "port": 22,
        "ssh_key": "", "ssh_options": "",
    },
}

# ---------------------------------------------------------------------------
# 执行器（本机 / 局域网 SSH / 远程 SSH 统一抽象）
# ---------------------------------------------------------------------------

class Runner:
    name = "base"
    def run(self, cmd: str, timeout: int = 120) -> tuple[bool, str, str]:
        raise NotImplementedError
    def write(self, path: str, content: str) -> None:
        raise NotImplementedError
    def read(self, path: str) -> str:
        raise NotImplementedError
    def exists(self, path: str) -> bool:
        ok, out, _ = self.run(f"test -e {shlex.quote(path)} && echo yes || echo no")
        return out.strip() == "yes"


class LocalRunner(Runner):
    name = "local"
    def run(self, cmd, timeout=120):
        try:
            p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)
            return p.returncode == 0, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return False, "", "timeout"
    def write(self, path, content):
        p = Path(os.path.expanduser(path)); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    def read(self, path):
        return Path(os.path.expanduser(path)).read_text(encoding="utf-8")


class SSHRunner(Runner):
    name = "ssh"
    def __init__(self, t):
        self.host, self.user = t["host"].strip(), t["user"].strip()
        if not self.host:
            raise ValueError("mode=ssh 时 target.host 必填")
        self.base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                     "-p", str(t.get("port", 22))]
        if t.get("ssh_key"):
            self.base += ["-i", os.path.expanduser(t["ssh_key"])]
        if t.get("ssh_options"):
            self.base += shlex.split(t["ssh_options"])
        dest = f"{self.user}@{self.host}" if self.user else self.host
        self.base.append(dest)
    def run(self, cmd, timeout=120):
        try:
            p = subprocess.run(self.base + ["bash", "-s"], input=cmd,
                               capture_output=True, text=True, timeout=timeout)
            return p.returncode == 0, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return False, "", "timeout"
    def write(self, path, content):
        b64 = base64.b64encode(content.encode()).decode()
        self.run(f"mkdir -p $(dirname {shlex.quote(path)}); printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(path)}")
    def read(self, path):
        ok, out, _ = self.run(f"cat {shlex.quote(path)}")
        return out if ok else ""


def build_runner(cfg):
    return LocalRunner() if cfg["target"]["mode"] == "local" else SSHRunner(cfg["target"])


# ---------------------------------------------------------------------------
# 配置 / 工具
# ---------------------------------------------------------------------------

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


def auth_headers(cfg):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = cfg["bridge"]["auth_header"]
    if auth:
        parts = auth.split(":", 1)
        if len(parts) == 2:
            headers[parts[0].strip()] = parts[1].strip()
    return headers


def fetch_catalog(cfg) -> list[str]:
    req = urllib.request.Request(cfg["bridge"]["catalog_url"], headers=auth_headers(cfg))
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [it["id"] for it in data.get("data", []) if isinstance(it, dict) and it.get("id")]


def extract_model_id(raw_id: str, prefix: str) -> str:
    if prefix and prefix in raw_id:
        return raw_id[raw_id.find(prefix):]
    return raw_id


def is_chat_model(model_id: str, cfg) -> bool:
    low = model_id.lower()
    return not any(k in low for k in cfg["filter"]["exclude_keywords"])


def probe_model(model_id: str, cfg) -> str:
    """返回 ok / dead / timeout / rate_limited / error。只发 1 次，不重试。"""
    payload = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": cfg["probe"]["max_tokens"],
    }).encode("utf-8")
    req = urllib.request.Request(cfg["bridge"]["chat_url"], data=payload,
                                 headers=auth_headers(cfg), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg["probe"]["timeout_sec"]):
            return "ok"
    except urllib.error.HTTPError as e:
        if e.code == 429: return "rate_limited"
        if e.code in (404, 410): return "dead"
        return "error"
    except Exception:
        return "timeout"


def dedup(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def load_list(rc, path) -> list[dict]:
    if not rc.exists(path):
        return []
    try:
        data = json.loads(rc.read(path))
        return data.get("models", []) if isinstance(data, dict) else data
    except Exception:
        return []


def sync(cfg, dry_run=False, no_restart=False, scheduled=False) -> int:
    rc = build_runner(cfg)
    print(f"=== Free Model Bridge v{VERSION} ===")
    print(f"目标执行器 : {rc.name}")

    marker = cfg["schedule"]["success_marker"]
    if scheduled and rc.exists(marker):
        try:
            if rc.read(marker).strip() == date.today().isoformat():
                print(f"[跳过] 今天({date.today()})已成功同步过，本次定时触发不重复执行。")
                return 0
        except Exception:
            pass

    # 1) 拉目录 + 过滤
    print("[1/6] 拉模型目录…")
    try:
        raw = fetch_catalog(cfg)
    except Exception as e:
        print(f"[失败] 拉目录失败: {e}", file=sys.stderr)
        return 1
    ids = dedup(extract_model_id(x, cfg["models"]["id_prefix"]) for x in raw)
    ids = [x for x in ids if is_chat_model(x, cfg)]
    print(f"      目录 {len(raw)} 项 → 过滤后 {len(ids)} 个对话模型")

    if dry_run:
        print("\n[DRY-RUN] 过滤后的候选模型：")
        for i in ids: print(f"  - {i}")
        print("\n不探活、不写清单。去掉 --dry-run 执行完整同步。")
        return 0

    # 2) 读现有清单
    list_path = cfg["models"]["list_path"]
    existing = load_list(rc, list_path)
    existing_ids = {m.get("id") for m in existing if isinstance(m, dict)}
    print(f"[2/6] 现有清单 {len(existing)} 个模型")

    # 3) 限速探活（只探候选；清单里已验证过的先不重复探，除非不在候选里）
    print("[3/6] 串行探活（限速保护，429 熔断）…")
    confirmed, dead = set(), set()
    limit = min(len(ids), cfg["filter"]["max_models"])
    circuit = False
    for idx, mid in enumerate(ids[:limit]):
        if circuit: break
        verdict = probe_model(mid, cfg)
        if verdict == "ok": confirmed.add(mid)
        elif verdict == "dead": dead.add(mid)
        elif verdict == "rate_limited":
            print(f"      ⚠ 命中 429，熔断本轮（已确认 {len(confirmed)} 个）")
            circuit = True
            break
        # timeout/error：不纳入 confirmed，也不删
        if idx < limit - 1:
            time.sleep(cfg["probe"]["interval_sec"])
    print(f"      探活完成：确认可用 {len(confirmed)} / 明确失效 {len(dead)}" + ("（已熔断）" if circuit else ""))

    # 4) 合并清单：剔除失效，补入新确认，其余保留
    print("[4/6] 合并模型清单…")
    tmpl = cfg["models"]["model_template"]
    merged = [m for m in existing if isinstance(m, dict) and m.get("id") not in dead]
    merged_ids = {m["id"] for m in merged}
    added = 0
    for mid in sorted(confirmed):
        if mid not in merged_ids:
            entry = dict(tmpl)
            entry["id"] = mid
            entry["name"] = mid
            merged.append(entry)
            merged_ids.add(mid)
            added += 1
    removed = len(existing) - len([m for m in existing if isinstance(m, dict) and m.get("id") not in dead])
    print(f"      补入 {added} / 剔除 {removed} / 最终 {len(merged)} 个")

    # 5) 写回清单（先备份）
    print("[5/6] 写回模型清单…")
    if rc.exists(list_path):
        rc.run(f"cp {shlex.quote(list_path)} {shlex.quote(list_path + '.bak-' + date.today().isoformat())}")
    rc.write(list_path, json.dumps({"models": merged, "updated": date.today().isoformat()},
                                   ensure_ascii=False, indent=2) + "\n")
    print(f"      已写入 {list_path}")

    # 6) 后处理：重生成 patch + 重启
    print("[6/6] 后处理…")
    gp = cfg["post_sync"]["gen_patch_command"]
    if gp:
        ok, _, err = rc.run(gp, timeout=180)
        print("      重生成 patch: " + ("完成" if ok else f"失败 {err[:150]}"))
    if not no_restart and cfg["post_sync"]["restart_command"]:
        ok, _, err = rc.run(cfg["post_sync"]["restart_command"], timeout=120)
        print("      重启服务: " + ("完成" if ok else f"失败 {err[:150]}"))

    if scheduled:
        rc.write(marker, date.today().isoformat() + "\n")
    print("\n同步完成 ✓")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Free Model Bridge — 免费模型清单自动同步")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--scheduled", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args()
    try:
        return sync(load_config(args.config), args.dry_run, args.no_restart, args.scheduled)
    except Exception as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
