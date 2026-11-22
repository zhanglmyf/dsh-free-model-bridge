# 三种部署方式

`target.mode` 决定模型清单写到哪里、探活从哪个网络发起。与 DSH Universal Installer 共用同一套执行器抽象。

## local（本机）

网关、DSH、模型清单都在本机。脚本直接 subprocess 执行。

```json
{ "target": { "mode": "local" } }
```

## ssh（局域网）

DSH 跑在 NAS / 内网服务器上。你在自己电脑上跑脚本，通过 SSH 维护目标机上的模型清单。

```json
{
  "target": {
    "mode": "ssh",
    "host": "192.168.x.x",
    "user": "your-user",
    "ssh_key": "~/.ssh/id_ed25519"
  }
}
```

注意：`catalog_url` / `chat_url` 是**从目标机视角**访问的。如果网关在目标机本机，`127.0.0.1` 正确；如果网关在别的机器，填目标机能访问到的地址。

## ssh（远程 + 跳板）

```json
{
  "target": {
    "mode": "ssh",
    "host": "server.example.com",
    "user": "your-user",
    "ssh_options": "-J jump.example.com"
  }
}
```

## 定时任务要装在哪

定时同步任务应该装在**目标机**上（模型清单所在处）：

| 目标 | 定时方案 |
|---|---|
| 本机 Linux | systemd user timer（`templates/model-sync.service/.timer`）|
| 本机 macOS | launchd agent |
| 本机 Windows | 任务计划程序 |
| 局域网/远程 Linux | 在目标机装 systemd timer，脚本路径指向目标机上的副本 |

`--scheduled` 守卫依赖成功标记文件 `schedule.success_marker`，它写在目标机上。

**桌面版补充**：官方桌面版（Windows / macOS）同样可以定时刷新清单——Windows 用任务计划程序跑 `python <项目路径>\scripts\model_sync.py --config <config路径> --scheduled`，macOS 用 launchd agent。定时脚本只负责刷新模型清单和 patch 文件，**不会自动重启桌面应用**；合并 patch 后需手动重启一次才生效。
