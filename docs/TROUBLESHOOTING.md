# 排障速查

| 症状 | 原因 | 处理 |
|---|---|---|
| 探活大量 429 | 网关限流 | 增大 `probe.interval_sec`；减小 `filter.max_models`；本轮熔断属正常，下次再跑 |
| 模型都被判 timeout | 慢推理模型 / 超时太短 | 增大 `probe.timeout_sec`；这些模型不会删（宁留勿删） |
| 下拉里还有报 404 的僵尸项 | 该模型探活时恰好没返回 404 | 再跑一轮；或手工从 `cloud-models.json` 删除 |
| 新模型没出现 | 目录里被过滤掉了 / 探活没通过 | 用 `--dry-run` 看过滤结果；检查 `exclude_keywords` 是否误伤 |
| 生成 patch 后本地模型消失了 | 用了只写单一 provider 的工具 | 用本项目的 `gen_patch.py`，它合并本地+云端两个 provider |
| 切换模型报 headroom / compaction 错 | 云端模型 contextWindow 太小 | `model_template.contextWindow` 设 ≥200000 |
| 改了配置不生效 | 改错文件 / 没重启 | `dsh --profile web --dump-config` 看真实生效值；重启服务 |
| --scheduled 总是跳过 | 成功标记是今天的 | 手动跑时不带 `--scheduled`（强制同步），或删标记文件 |
| SSH 目标连不上 | BatchMode 无密钥 | 先配免密：`ssh -o BatchMode=yes user@host echo ok` |
| 参数不认（reasoningEfforts 等） | 模型对象字段缺失 | 用 `model_template` 补全字段 |

## 调试建议

```bash
# 1. 只看过滤结果（不发请求）
python3 scripts/model_sync.py --config config.json --dry-run

# 2. 看生成的模型清单
cat ~/.dsh/cloud-models.json

# 3. 预览 patch
python3 scripts/gen_patch.py --config config.json --dry-run

# 4. 看 DSH 生效配置
dsh --profile web --dump-config
```

## 熔断后怎么办

429 熔断是**保护机制**，不是故障。本轮保留已确认的模型，等限流窗口过去（通常几十秒到几分钟）再跑一次即可。不要写脚本自动重试——那正是刷爆额度的原因。
