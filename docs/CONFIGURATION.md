# 配置参考

`config.json`（从 `config.example.json` 复制）。所有值为默认占位，按需修改。

## bridge

| 字段 | 默认 | 说明 |
|---|---|---|
| `catalog_url` | `http://127.0.0.1:8082/v1/models` | 模型目录端点（OpenAI 兼容） |
| `chat_url` | `http://127.0.0.1:8082/v1/chat/completions` | 探活用的对话端点 |
| `auth_header` | `Authorization: Bearer local` | 认证头，形如 `Header: value`；留空免认证 |

> 从目标机视角理解这些地址。远程模式下 `127.0.0.1` 指目标机自身。

## models

| 字段 | 说明 |
|---|---|
| `list_path` | 模型清单 JSON 的存放路径 |
| `id_prefix` | 从目录 id 截取规范 id 的起点；如 `nvidia_nim/` |
| `keep_unverified` | 超时/未知模型是否保留（默认 true，宁留勿删） |
| `model_template` | 新模型对象的默认字段（contextWindow、reasoningEfforts 等） |

## filter

| 字段 | 说明 |
|---|---|
| `exclude_keywords` | id 含这些词的模型被排除（非对话类） |
| `max_models` | 一轮最多探活数（默认 40，速率保护） |

## probe

| 字段 | 默认 | 说明 |
|---|---|---|
| `interval_sec` | 1.5 | 模型间最小间隔（秒） |
| `timeout_sec` | 45 | 单模型超时 |
| `max_tokens` | 1 | 探活请求的最大输出 |
| `circuit_break_on_429` | true | 命中 429 熔断本轮 |

## post_sync

| 字段 | 说明 |
|---|---|
| `gen_patch_command` | 同步后重生成 patch 的命令；留空跳过 |
| `restart_command` | 同步后重启 DSH 的命令；留空跳过 |

串联示例：
```json
"post_sync": {
  "gen_patch_command": "python3 ~/.dsh/scripts/gen_patch.py --config ~/.dsh/config.json",
  "restart_command": "systemctl --user restart dsh-web"
}
```

## schedule

| 字段 | 说明 |
|---|---|
| `success_marker` | 当天成功标记文件，`--scheduled` 模式用 |

## target

同 DSH Universal Installer：`mode`（local/ssh）、`host`、`user`、`port`、`ssh_key`、`ssh_options`。
