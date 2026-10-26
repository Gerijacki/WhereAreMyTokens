# One dashboard for several machines

Run the server once, for example on a homelab box, and an agent on every computer where you use Claude Code. Each
agent reads that machine's transcripts and pushes them to the server, which deduplicates by message id, so all your
usage ends up in one dashboard. You can still look at each computer on its own with the device filter.

The examples use [Tailscale](https://tailscale.com), so the dashboard is reachable from your laptop anywhere without
exposing it to the internet. A LAN address or a domain behind a reverse proxy works the same way.

## 1. The server

```bash
git clone https://github.com/Gerijacki/WhereAreMyTokens.git && cd WhereAreMyTokens
cat > .env <<'EOF'
POSTGRES_PASSWORD=change-me
# The server has no Claude Code transcripts of its own: only agents send data.
WAMT_INGEST_ENABLED=false
EOF
docker compose up -d
```

Open `http://<homelab>:8787` (with Tailscale MagicDNS, the machine name, or its `100.x.y.z` address). Anyone on your
tailnet can reach it, so set a password in *Settings → Security* if that tailnet is shared.

If the server is also one of the computers you use Claude Code on, leave `WAMT_INGEST_ENABLED` unset: it reads its
own transcripts (as the device `local`) and you need agents only on the other machines.

## 2. A token per computer

In *Settings → Devices*, add one device per computer, for example `laptop` and `desktop`. Each token is shown once.
From a shell on the server, `docker compose exec wamt wamt device add laptop` does the same.

The device name is what the dashboard shows and filters by. To retire a computer, revoke its token: its data stays.

## 3. The agent on each computer

### Linux, as a systemd user service

```bash
uv tool install "git+https://github.com/Gerijacki/WhereAreMyTokens.git#subdirectory=backend"
mkdir -p ~/.config/wamt ~/.config/systemd/user
printf 'WAMT_SERVER=http://homelab:8787\nWAMT_TOKEN=wamt_xxx\n' > ~/.config/wamt/agent.env
chmod 600 ~/.config/wamt/agent.env
curl -fsSL https://raw.githubusercontent.com/Gerijacki/WhereAreMyTokens/main/deploy/wamt-agent.service \
  -o ~/.config/systemd/user/wamt-agent.service
systemctl --user enable --now wamt-agent
journalctl --user -u wamt-agent -f      # "Sent N records to …"
```

To keep the agent running while you're logged out, run `loginctl enable-linger $USER`. To update it, run
`uv tool upgrade wamt && systemctl --user restart wamt-agent`.

### Any OS, with Docker

```bash
WAMT_SERVER=http://100.x.y.z:8787 WAMT_TOKEN=wamt_xxx docker compose -f docker-compose.agent.yml up -d
```

Use the Tailscale IP here: containers don't always resolve MagicDNS names.

### By hand

```bash
wamt agent --server http://homelab:8787 --token wamt_xxx           # add --no-prompts to send no prompt text
```

## What the agent sends, and when it can't

- **What it sends:** usage numbers, tool names and targets, and redacted prompt text (`--no-prompts` replaces the
  text with a placeholder). It never sends file contents, tool output or model responses.
- **The first run:** it sends all the history that is still on disk. Re-sending is harmless, because the server
  counts every API response once.
- **When the server can't be reached** (the laptop is away from home, or the homelab is down), new records wait in a
  local queue, in `~/.config/wamt/spool` (or `/state/spool` with Docker). The queue is sent in order once the server
  is reachable again. It doesn't depend on the transcripts, so nothing is lost when Claude Code deletes old
  sessions, which it does after 30 days by default (`cleanupPeriodDays`).

## Troubleshooting

- **Nothing arrives.** Check `journalctl --user -u wamt-agent` (or `docker compose -f docker-compose.agent.yml logs`).
  "Cannot reach server … N batches queued" means it's waiting for the network: try
  `curl http://homelab:8787/api/health` from that computer. *Settings → Devices* shows when each device was last seen.
- **The agent stopped with "Server rejected the device token".** The token was revoked or mistyped. Create a new
  device, put its token in `agent.env` and restart the agent. The queue is kept, and is sent under the new device once the agent restarts.
- **Renaming a computer.** Sessions keep the device name they arrived with. Create a device with the new name and
  revoke the old one; new sessions use the new name.
- **Starting the agent over.** Delete `~/.config/wamt/agent-state.json` and it sends every transcript still on
  disk again. That's safe: the server ignores what it already has.
- **Where the data lives.** On the server, in the PostgreSQL volume (`wamt-db`). Back it up with
  `docker compose exec db pg_dump -U wamt wamt > wamt.sql`: once Claude Code has deleted old transcripts, it's the
  only copy. Agents keep only their offsets and the queue.

## Moving from a local install

If a computer already ran its own WAMT, its agent re-sends every transcript still on disk, so there's nothing to
migrate. The exception is sessions Claude Code has already deleted: they are only in that computer's old database.
