# 贡献指南

## 贡献方式

- **报告问题**：GitHub Issues，附网关类型、DSH 版本、`--dry-run` 输出。
- **提交代码**：Fork → 分支 → PR，一个 PR 一件事。

## 开发约定

1. **纯标准库**：脚本不引入第三方依赖。
2. **限速铁律不改**：并发探测 / 429 重试 / 超时删除 —— 这三条永远不要改，它们是防刷爆额度的底线。
3. **脱敏**：提交前跑 `python3 scripts/healthcheck.py`，无真实端点 / 密钥 / 私人路径。
4. **本地+云端合并**：改 patch 生成逻辑时，确保两个 provider 都在，不要退化成单一 provider。
5. **幂等**：写清单和 patch 前备份。

## 本地检查

```bash
python3 -m py_compile scripts/*.py
python3 scripts/healthcheck.py
```
