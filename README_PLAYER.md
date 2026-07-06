# King Bug Castle — how to play

> **Note to developers**: This is the instruction manual included in the generated distribution zip (`make_share.sh`). If you are setting up the project from the git repository, see `server/README.md` instead.
A fan-made private-server build of King God Castle. Not affiliated with Awesomepiece.

You have: `apk/` (3 signed APKs), `server/` (the backend), `start_server.sh`.

## 1. Run the server (on a PC on your LAN)
```bash
./start_server.sh          # listens on 0.0.0.0:8080
```
Note the PC's LAN IP (e.g. `192.168.1.50`): `ip addr` / `ipconfig`.

## 2. Install the client (Android, root required)
```bash
adb install-multiple -r apk/base_signed.apk apk/split_base_assets_signed.apk apk/split_config_signed.apk
```

## 3. Point the game at your server
The client talks plain HTTP. Add to the device `/system/etc/hosts`
(needs root: `mount -o rw,remount /`), replacing `SERVER_IP` with your PC's LAN IP:
```
SERVER_IP axis-game.awesomepiece.com
SERVER_IP kgc-k8s-1.awesomepiece.com
SERVER_IP isekai-lobbyserver.awesomepiece.com
SERVER_IP castle-infra-server-65408603887.asia-northeast3.run.app
SERVER_IP kgc-cdn-1.awesomepiece.com
```
The client hits port 80. Either run the server on `:80` (edit `start_server.sh`
to `--port 80`, needs root) or redirect 80→8080 on the server
(`socat TCP-LISTEN:80,fork TCP:127.0.0.1:8080`).

## 4. Launch
Open **King Bug Castle**. It boots past login and talks to your server.
Edit `server/state/player.json` to change your save (gold, level, units…).
