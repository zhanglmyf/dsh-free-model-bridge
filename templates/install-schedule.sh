#!/usr/bin/env bash
# 定时任务安装助手 — 按平台生成定时同步配置
# 用法: bash install-schedule.sh <platform> <script-path> <config-path>
#   platform: systemd | cron | launchd | windows
set -euo pipefail

PLATFORM="${1:-systemd}"
SCRIPT="${2:-$HOME/.dsh/scripts/model_sync.py}"
CONFIG="${3:-$HOME/.dsh/config.json}"

case "$PLATFORM" in
  systemd)
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/model-sync.service" <<EOF
[Unit]
Description=Free Model Bridge sync
After=network-online.target
[Service]
Type=oneshot
Environment=HOME=$HOME
ExecStart=/usr/bin/python3 "$SCRIPT" --config "$CONFIG" --scheduled
TimeoutStartSec=900
EOF
    cat > "$UNIT_DIR/model-sync.timer" <<'EOF'
[Unit]
Description=Periodic model sync
[Timer]
OnCalendar=Sat 07,09,11,13,15,17,19:00:00
Persistent=true
RandomizedDelaySec=120
[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now model-sync.timer
    loginctl enable-linger "$USER" 2>/dev/null || true
    echo "已安装 systemd user timer。暂停: systemctl --user stop model-sync.timer"
    ;;
  cron)
    (crontab -l 2>/dev/null; echo "0 7,9,11,13,15,17,19 * * 6 /usr/bin/python3 $SCRIPT --config $CONFIG --scheduled >> $HOME/.dsh/sync.log 2>&1") | crontab -
    echo "已安装 crontab（每周六 7-19 点每两小时）。查看: crontab -l"
    ;;
  launchd)
    PLIST="$HOME/Library/LaunchAgents/com.model-sync.plist"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.model-sync</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$SCRIPT</string><string>--config</string><string>$CONFIG</string><string>--scheduled</string></array>
  <key>StartCalendarInterval</key><array>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>7</integer></dict>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>13</integer></dict>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>19</integer></dict>
  </array>
</dict></plist>
EOF
    launchctl load "$PLIST"
    echo "已安装 launchd agent: $PLIST"
    ;;
  windows)
    echo "Windows 请用任务计划程序（taskschd.msc）新建任务："
    echo "  触发器: 每周六 07:00（可加多个时间）"
    echo "  操作: python.exe $SCRIPT --config $CONFIG --scheduled"
    echo "  或 PowerShell: Register-ScheduledJob -Name ModelSync -ScriptBlock { python '$SCRIPT' --config '$CONFIG' --scheduled } -Trigger (New-JobTrigger -Weekly -DaysOfWeek Saturday -At 7am)"
    ;;
  *)
    echo "未知平台: $PLATFORM（可选 systemd/cron/launchd/windows）" >&2
    exit 1
    ;;
esac
