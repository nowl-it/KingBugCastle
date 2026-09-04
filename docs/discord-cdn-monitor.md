# Discord CDN monitor

The bot posts to channel `1541439188686213221`. It checks the upstream CDN every 30 minutes
and posts only when it finds a new CDN folder, an in-place CDN republish, or a newer client APK.

## One-time host setup

Store the Discord bot token outside git, then enable the user service:

```bash
install -m 700 -d server/secrets
install -m 600 /dev/stdin server/secrets/discord_bot_token
# Paste the token, press Ctrl-D.

mkdir -p ~/.config/systemd/user
cp systemd/kgc-cdn-monitor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kgc-cdn-monitor.service
loginctl enable-linger "$USER"  # keep it alive after logout/reboot
```

The service immediately posts `KGC CDN monitor online`, then runs
`scripts/check_cdn_update.sh` every 30 minutes. Check it with:

```bash
systemctl --user status kgc-cdn-monitor.service
journalctl --user -u kgc-cdn-monitor.service -f
```

To test a configured bot manually:

```bash
server/discord_notify.sh "🧪 KGC Discord notifier test"
```
