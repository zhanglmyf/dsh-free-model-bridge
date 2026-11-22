# 工作原理

## 为什么需要这个项目

DSH 通过 provider patch 认识"有哪些模型可用"。当你把免费云端模型接进来后，会遇到三个问题：

1. 上游网关的模型目录会变（下架、改名、上新），但 DSH patch 是**静态手写**的，不会自动同步
2. 模型下架后，下拉里留着点了报 404 的**僵尸项**
3. 新上线的好模型**不会自动出现**

本项目把"维护模型清单"这件事自动化。

## 数据流

```
网关 /v1/models ──> 过滤 ──> 限速探活 ──> cloud-models.json
                                              │
                          ollama list ─────────┤
                                              ↓
                                       gen_patch.py
                                              ↓
                                   fcc-merged.patch.yml
                                              ↓
                                     DSH（一个下拉看全部）
```

## 六个步骤

### 1. 拉目录
从 `bridge.catalog_url`（OpenAI 兼容端点）拿模型 id 列表。

### 2. 过滤
按 `filter.exclude_keywords` 排除非对话模型：embedding、rerank、guard、safety、翻译、审核、视觉等。按 `models.id_prefix` 从 wire id 里截取规范 id，并去重。

### 3. 限速探活（核心）
- **串行**，每个模型之间 `sleep(probe.interval_sec)`（默认 1.5s）
- 每模型只发 **1 次** `max_tokens=1` 的最小请求
- **命中 429 立即熔断**：停止本轮，不重试（这是防止"刷爆免费额度"的关键）
- 404/410 → 判定失效；超时 → 保留（慢模型不该被误杀）

### 4. 合并清单
- 明确失效 → 剔除
- 新确认可用 → 补入（按 `model_template` 生成模型对象）
- 超时/未知 → 原样保留

### 5. 生成 patch
`gen_patch.py` 读本地模型（`ollama list`）+ 云模型清单，生成**一个包含两个 provider 的 patch**。这很关键——很多网关生成的 patch 会整体替换 `providers` 对象，把本地 provider 冲掉。

### 6. 定时维护
`--scheduled` 模式配合 systemd timer / cron / launchd / Windows 任务，并带"当天成功过就跳过"的守卫，避免一天内重复探活浪费额度。

## 关于额度（重要认知）

- 多数免费层是**速率限制**（RPM），不按 token 计费——不存在"用光一整天的池子"，撞限就是 429，等一会儿恢复
- 具体数值以你所用服务的官方文档为准，不要相信过时博客里的"每月 N credits"说法
- 本工具的限速设计让你**几乎不可能**自己打爆限流
