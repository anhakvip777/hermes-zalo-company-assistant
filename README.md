# Hermes Zalo Company Assistant

**English** · [Tiếng Việt](./README.vi.md)

This plugin connects one company Zalo account to Hermes Agent through
`zca-js@2.1.2`. It is based on `cuongdev/hermes-zalo-plugin@1.0.9` and keeps the
full operational Zalo API surface for a small trusted team.

Default operating model:

- One company, one Zalo account, one Hermes Agent, and one VPS.
- Every ID in `allowed_users` can use normal Hermes tools and operational Zalo
  methods immediately, without per-action approval.
- Administrators additionally manage members, shared memory, history, QR login,
  and services.
- Every message in `allowed_groups` is stored, even without a bot mention.
- In groups, only an allowed member mentioning the bot starts a Hermes turn.
- Each member's direct messages use an isolated session and history.

> `zca-js` uses an unofficial personal-account API. Zalo may challenge,
> rate-limit, or lock automated accounts. Use a dedicated company bot account.

## Requirements

- Node.js 22+
- Python 3.11+
- Hermes Agent 0.19.0 at commit
  `eb52760564dbba2e5971fa54bd67384e281cd3b8`, exposing
  `PlatformEntry.env_enablement_fn` and `MessageEvent.channel_context`.
- `aiohttp` and `PyYAML`
- Ubuntu 22.04/24.04 with systemd is recommended for VPS deployment

## Quick start

```bash
npm install
python -m pip install -r requirements-runtime.txt
node install.mjs
```

The installer creates a private `~/.hermes-zalo/company.env`, generates a
bridge token of at least 32 bytes when needed, drives QR login, and installs the
bridge service.

Manual bridge setup:

```bash
export ZALO_PLUGIN_HOST=127.0.0.1
export ZALO_PLUGIN_PORT=8787
export ZALO_PLUGIN_TOKEN="$(openssl rand -hex 32)"
export ZALO_DATA_DIR="$HOME/.hermes-zalo"

node login.mjs
node server.js
```

Every bridge route requires `Authorization: Bearer <token>` or the internal
compatibility header `x-bridge-token`. Query-string tokens are rejected. The
bridge only binds to `127.0.0.1`.

## Hermes configuration

```yaml
approvals:
  mode: off

gateway:
  group_sessions_per_user: false
  platforms:
    zalo:
      enabled: true
      extra:
        bridge_url: http://127.0.0.1:8787
        allowed_users: ["member-zalo-id", "admin-zalo-id"]
        admin_users: ["admin-zalo-id"]
        allowed_groups: ["company-group-id"]
        group_mode: mention
        history_context_messages: 100
        media_max_bytes: 20971520
        history_retention: "90"
```

Keep `ZALO_PLUGIN_TOKEN` in the environment of both the bridge and Hermes
gateway, not in YAML. Configuration is fail-closed: user, admin, and group lists
must be non-empty; administrators must be allowed users; group mode is
`mention`.

`approvals.mode: off` is only suitable for an isolated Zalo profile running as
a dedicated OS user with no access to personal profiles or data. Do not use it
for a shared Hermes profile. It bypasses approvals throughout the target
profile; the Admin Guard still prevents non-admin shared-memory writes.

This is an internal trusted-team bot, not a public bot. Broad allowlist access,
prompt injection, compromised member accounts, model misunderstanding, and
hard-to-reverse actions are explicitly accepted residual risks. Use a dedicated
bot Zalo account, never a primary personal account.

Allowed users may search and read shared history from every group in
`allowed_groups`, including while asking from a DM or another allowed group.
They cannot read another member's DM, export/delete company history, change
retention, or perform admin configuration, service, or shared-memory operations.

## Admin Web

The terminal-style Admin Web is responsive, supports system/light/dark themes,
and has a collapsible sidebar. The browser persists only two versioned UI
preferences; passwords, sessions, CSRF values, and company data are never stored
in `localStorage`. Use a currently supported Chrome, Edge, Firefox, or Safari.
The redesign does not change APIs, the database, or permissions. Missing
`admin_web` assets fail startup; reinstall the complete package.

## Conversation behavior

For an allowed company group, the adapter deduplicates and stores every message
before checking mentions. A message without a mention remains in history but
does not start Hermes. A mention from an allowed user starts the shared group
session. A mention from an outsider is stored but does not start Hermes.

Only DMs from allowed users are stored and dispatched. Each Zalo ID gets a
separate DM session. Outbound content is stored only after the bridge returns a
clear provider message ID. A timeout returns `unknown` and is never retried
automatically.

## Hermes tools

`zalo` provides discovery and generic invocation:

```text
zalo(action="list", query="poll")
zalo(action="describe", method="createPoll")
zalo(action="call", method="createPoll", params={...})
zalo(action="call", method="customMethod", args=[...])
```

The catalog is generated from the installed `zca-js@2.1.2` declarations and
live API object. Credential-producing methods such as `getCookie`, `getContext`,
and `getQR` are hidden and denied through chat.

`zalo_history` supports `recent`, `search`, `get_message`, and
`get_attachment`. Members can read their own DM and allowlisted company groups;
admins can inspect all company history.

`zalo_admin` initially supports status, member/admin changes, shared-memory
changes, history export/delete, QR login, service lifecycle, and redacted logs.
Requester identity always comes from the bound Zalo turn, never model arguments.
Shared-memory actions use Hermes 0.19's native file layout and entry format at
`$HERMES_HOME/memories/MEMORY.md`.

## Storage and media

SQLite stores conversations, messages, events, attachment metadata, and tool
activity. Binary media lives on disk:

Retention defaults to 90 days and accepts `30`, `90`, `365`, or `forever`.
Startup purges expired history. Removing a group from the allowlist does not
delete old data. Keep SQLite, media, config, and backups owned by the dedicated
`hermes-zalo` user with directories `0700` and secrets `0600`.

```text
~/.hermes-zalo/history/conversations.sqlite3
~/.hermes-zalo/history/media/<dm|group>/<thread-id>/<YYYY-MM-DD>/
~/.hermes-zalo/exports/
```

Media up to 20 MiB is streamed to a private path and hashed with SHA-256.
Larger or over-cap streams retain metadata only. A download failure never rolls
back the message. Message and attachment dedupe survives restart.

## Bridge API

The 1.0.9 convenience routes remain available for send, attachment, sticker,
voice, typing, reaction, undo, friends, groups, polls, health, SSE, QR,
relogin, and shutdown.

Generic discovery and calls:

```text
GET  /api/methods
GET  /api/methods/:method
POST /api/:method       body: {"params": {...}} or {"args": [...]}
```

Responses and logs recursively redact cookies, tokens, passwords, API keys,
secrets, IMEI, and Authorization values.

## systemd deployment

Production templates are in `systemd/`:

```bash
sudo cp systemd/hermes-zalo-company.env.example /etc/hermes-zalo-company.env
sudo chmod 600 /etc/hermes-zalo-company.env
sudo cp systemd/hermes-zalo-company-bridge.service /etc/systemd/system/
sudo cp systemd/hermes-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-zalo-company-bridge hermes-gateway
```

Adjust users, `/opt` paths, and token values for the VPS. The bridge starts
before Hermes gateway, and both restart on failure.

## Migrating a 1.0.9 configuration

```bash
node scripts/migrate-v1.0.9-config.mjs \
  --config "$HERMES_HOME/config.yaml" \
  --env-file "$HERMES_HOME/.env"
```

The migration is idempotent and never copies bridge tokens or cookies into
YAML.

## Verification

```bash
npm test
python -m pip install -r requirements-test.txt
python -m pytest -q
npm audit --omit=dev
npm pack --dry-run
python scripts/acceptance.py --json
git diff --check
```

See `docs/operations/acceptance-checklist.md` for the operational checklist.

## License

MIT.
