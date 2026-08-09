# Hermes Zalo Company Assistant Design

Date: 2026-08-09

Status: Approved in the design conversation; awaiting review of this written specification.

## 1. Summary

This project creates a private company fork of cuongdev/hermes-zalo-plugin at version 1.0.9. It keeps the proven Zalo login, reconnect, inbound listening, and outbound delivery paths built on RFS-ADRENO/zca-js 2.1.2, while replacing the broad Zalo automation surface with a narrowly scoped company-assistant gateway.

One company-owned Zalo account connects employees to one Hermes Agent running continuously on a Linux VPS. Employees are identified by Zalo ID. Direct messages are isolated per employee, approved company groups use group-scoped sessions, and all sessions share the company memory. Tool calls are controlled by a company policy hook. Read-only and ordinary work may execute immediately; externally visible or mutating work requires approval from a configured administrator.

The fork remains a standalone Hermes plugin and does not modify Hermes core.

## 2. Source Baselines

- Zalo plugin baseline: cuongdev/hermes-zalo-plugin tag v1.0.9, commit b30cf000e62a02f5da304d17556e28ddcb2d4ca2.
- Zalo library baseline: RFS-ADRENO/zca-js tag v2.1.2, commit e6d6074feffb941db2c1e45fe0dc2f946952a0e3.
- Hermes compatibility baseline: Hermes Agent v0.19.0 with platform plugins, pre_tool_call approval directives, gateway approval queues, and the optional send_exec_approval adapter surface. Later Hermes versions are supported only after the same compatibility suite passes.
- Deployment target: Ubuntu 22.04 or 24.04, Node.js 22 LTS, Python 3.11, and systemd.

## 3. Goals

The first production-ready release must:

1. Connect one company-owned personal Zalo account to one Hermes Agent.
2. Accept direct messages only from configured employee Zalo IDs.
3. Accept group messages only when both the group and sender are allowlisted and the assistant is mentioned.
4. Keep every employee direct-message session separate.
5. Keep each approved group in its own shared group session, isolated from all direct-message sessions.
6. Allow all sessions to read a shared company memory.
7. Let employees propose shared-memory changes, but apply them only after administrator approval.
8. Allow ordinary tools to run immediately and require administrator approval for sensitive tools.
9. Send approval requests privately to every administrator and accept the first valid decision.
10. Preserve an auditable chain from requester through approval to outcome.
11. Recover safely from Zalo disconnects, Hermes restarts, and VPS restarts without replaying tool side effects.
12. Remove credential export, arbitrary API passthrough, and unrelated Zalo administration capabilities.

## 4. Non-goals

The first release will not:

- Publish a public npm package.
- Support multiple Zalo accounts or multiple companies.
- Support Zalo Official Accounts.
- Expose all zca-js APIs to Hermes.
- Modify Hermes core.
- Automatically learn shared memory from ordinary conversations.
- Offer permanent or session-wide approval bypasses through Zalo.
- Guarantee exactly-once behavior for third-party systems that provide no idempotency mechanism; instead, the plugin never automatically retries a tool whose external outcome is uncertain.

## 5. Architecture

The solution has five bounded components.

### 5.1 Zalo Transport

The Node.js transport owns only Zalo connectivity:

- QR login and credential recovery.
- Cookie-first login after a successful QR login.
- WebSocket listening and bounded reconnect.
- Message normalization.
- Text, typing, and attachment delivery.
- Self-message filtering.

It does not make authorization, session, memory, or Hermes tool-policy decisions.

### 5.2 Hermes Zalo Adapter

The Python platform adapter:

- Consumes normalized inbound events from the loopback bridge.
- Converts events to Hermes MessageEvent values.
- Selects the direct-message or group session.
- Sends Hermes responses back through the bridge.
- Implements the platform-specific approval prompt surface.
- Intercepts administrator approval commands before they enter an agent session.

### 5.3 Identity and Session Router

The router validates sender and thread identity before invoking Hermes.

- Direct-message key: one stable session per employee Zalo ID.
- Group key: one stable session per approved group ID.
- Direct and group sessions never share conversation history.
- All sessions use the same configured Hermes profile and shared memory.
- Group messages are ignored unless the sender is allowlisted, the group is allowlisted, and the assistant is mentioned.

### 5.4 Company Policy

The policy component receives the originating identity and session context for each Hermes tool call. It returns exactly one directive:

- allow: execute immediately.
- approve: block until an administrator decides.
- block: refuse the action and return a policy explanation.

The policy is deterministic and config-driven. The model cannot grant itself additional privileges.

### 5.5 Approval Broker and State Store

The broker maps a one-time approval code to the original Hermes approval queue and session. It sends a redacted request to all administrator direct-message chats. The first valid decision is committed atomically and resolves the original blocked tool call.

Durable state is kept in a plugin-owned SQLite database under the active HERMES_HOME. It stores approval metadata, message deduplication keys, delivery records, and audit events. Zalo credentials remain in a separate file and never enter the database or audit log.

## 6. End-to-end Data Flow

### 6.1 Direct message

1. zca-js receives a message and the transport assigns a normalized event ID.
2. The adapter rejects self-messages and previously processed event IDs.
3. The router checks the employee allowlist.
4. An unauthorized sender is rejected before any model or tool call.
5. An authorized sender is routed to that employee's direct-message session.
6. Hermes answers or requests tools.
7. Company Policy allows, approves, or blocks each tool request.
8. The final response is delivered to the same direct-message chat.

### 6.2 Group message

1. The router validates group ID, sender ID, and assistant mention.
2. A failed check is ignored without invoking Hermes.
3. A valid message enters the group-scoped session.
4. Sensitive full outputs and generated files are sent privately to the requester; the group receives only a concise completion or failure status.

### 6.3 Sensitive tool call

1. Company Policy returns approve for the tool name and arguments.
2. Hermes creates a blocking approval entry for the origin session.
3. Approval Broker creates a six-character uppercase one-time code.
4. Every administrator receives the same redacted approval request by direct message.
5. An administrator replies Duyệt CODE or Từ chối CODE followed by an optional reason.
6. The adapter verifies that the decision came from an administrator direct message.
7. The state store atomically accepts the first valid decision.
8. Approval Broker resolves the original Hermes session queue.
9. The tool executes once when approved or returns a denial reason when rejected.
10. The requester receives the outcome in the original chat.

## 7. Identity and Channel Policy

Configuration defines three identity sets:

- allowed_users: employees who may invoke Hermes.
- admin_users: users who may approve requests. Every administrator must also be in allowed_users.
- allowed_groups: company groups in which the assistant may operate.

Startup fails closed when admin_users is empty, when an administrator is absent from allowed_users, or when the bridge token is missing.

Unauthorized direct-message senders receive a fixed access-denied response with no internal IDs or policy details. Unauthorized group messages are ignored to avoid noisy public responses.

Administrator commands are accepted only in direct messages. Group messages cannot approve, deny, change policy, or mutate memory directly.

## 8. Session and Memory Policy

### 8.1 Sessions

- Direct sessions are isolated by employee Zalo ID.
- Approved groups share only the history visible in that group.
- A group session cannot retrieve any direct-message conversation history.
- A direct session cannot retrieve group chat history unless the shared company memory independently contains the same fact.
- One agent turn runs at a time per session. Different sessions may run concurrently.

### 8.2 Shared memory reads

All authorized sessions may retrieve shared company memory. Retrieval does not grant write permission.

### 8.3 Shared memory proposals

An employee may propose add, update, or delete operations. The proposal must include:

- Proposer Zalo ID and display name.
- Origin chat and session.
- Operation type.
- Existing content for updates or deletions.
- Proposed content.
- Human-readable reason.

The proposal is routed through Approval Broker. No shared-memory mutation occurs before approval.

Attempts to mutate memory indirectly through file tools, terminal commands, execute-code tools, or internal system tools are classified as the same sensitive memory operation and require approval.

When approved, the audit record stores the proposer, approver, old value, new value, timestamps, and outcome. When denied or expired, memory is unchanged.

Ordinary conversation content is never written to shared memory automatically.

## 9. Tool Policy

Tool policy uses tool name, structured arguments, originating role, and protected-resource rules.

### 9.1 Immediate operations

These may run immediately when they are demonstrably read-only:

- Reading files inside configured company workspace roots.
- Listing and searching files.
- Reading shared memory.
- Read-only database or internal-system queries explicitly marked read-only.
- Web search, retrieval, summarization, analysis, and drafting.
- Producing response text without external delivery.

### 9.2 Approval-required operations

These always require a one-time administrator decision:

- Sending email or messages to any external system.
- Creating, editing, moving, or deleting files.
- Uploading or sending a local file through Zalo.
- Mutating databases or internal systems.
- Changing access, credentials, permissions, services, deployments, or scheduled jobs.
- Financial, purchasing, HR, or account-management actions.
- Adding, updating, or deleting shared memory.
- Terminal or execute-code operations that Hermes security guards identify as mutating or dangerous.
- Any plugin or MCP tool configured as mutating.

### 9.3 Hard-blocked operations

These cannot be approved through Zalo:

- Exporting Zalo cookies, context, tokens, API keys, or passwords.
- Disabling allowlists, approval policy, audit, or bridge authentication.
- Enabling Hermes yolo mode or permanent/session-wide approval from Zalo.
- Calling arbitrary zca-js methods.
- Modifying the policy database or approval records outside the broker.

### 9.4 Administrator-originated sensitive work

Administrator requests are subject to the same two-step confirmation. A requesting administrator may approve their own request, but the request still gets a code and a complete audit trail.

## 10. Approval Protocol

- Code format: six uppercase base32 characters excluding visually ambiguous characters.
- Lifetime: 300 seconds from creation.
- Scope: exactly one tool call or one memory mutation.
- Delivery: private message to every configured administrator.
- Decision rule: first valid atomic decision wins.
- Allowed decisions: Duyệt CODE and Từ chối CODE with an optional reason.
- No group decisions, no non-admin decisions, no reused codes, and no permanent approval mode.
- Invalid decision attempts are rate-limited and audited.
- A decision after resolution receives an already-processed response.
- Timeout is a denial.
- Process restart is a denial for every still-pending approval.
- Raw secrets are redacted before the approval message is built.

An approval message includes requester, origin, tool or memory operation, redacted target and arguments, expected effect, creation time, expiry time, and code.

## 11. Bridge API Surface

The bridge binds only to 127.0.0.1 and requires a strong shared token on every route, including health probes.

Allowed routes are restricted to:

- Health and connection state.
- Authenticated Server-Sent Events for normalized inbound events.
- Send text.
- Send typing state.
- Send an attachment supplied as authenticated multipart content.
- QR relogin and QR retrieval from localhost.

The fork removes:

- Generic method passthrough.
- Cookie or context export.
- Friend request management.
- Group creation, membership, deputy, rename, leave, and poll management.
- Contact enumeration not required by setup.
- Remote shutdown.
- Arbitrary local filesystem path uploads.

The Python adapter reads an approved file and uploads its bytes over the authenticated loopback connection. The Node process never accepts a caller-provided local path.

## 12. Configuration and Secrets

Behavioral settings live in the active Hermes config.yaml, not environment variables. They include identity sets, group mode, tool classification overrides, workspace roots, rate limits, concurrency, and approval timeout.

Secrets live in the active Hermes .env or a systemd credential file. They include the bridge token and third-party credentials. Zalo session credentials are stored under a plugin-owned state directory with directory mode 0700 and file mode 0600.

Default runtime limits are:

- 10 accepted inbound messages per employee per minute.
- 60 accepted inbound messages globally per minute.
- 4 concurrently running Hermes sessions.
- 5 queued inbound messages per session.
- 300-second approval timeout.
- 3 outbound Zalo delivery attempts with bounded backoff.

The setup command may import old version-1.0.9 behavioral environment values once and write their equivalent config.yaml section. Runtime behavior then comes only from config.yaml. Secrets remain outside config.yaml.

## 13. Reliability and Failure Behavior

### 13.1 Zalo disconnect

The transport reconnects with bounded exponential backoff. A permanently dead or expired session stops command processing and sends a private alert to administrators. QR login must be completed locally on the VPS or through an authenticated SSH tunnel.

### 13.2 Hermes unavailable

The adapter returns a fixed maintenance response. It does not queue work that could execute unexpectedly after recovery.

### 13.3 Duplicate events

Inbound event IDs are persisted before agent dispatch. A duplicate cannot create a second agent turn. Self-sent messages are always filtered.

### 13.4 Delivery failure

Zalo response delivery may retry up to three times. Tool execution is never retried as a consequence of a delivery failure.

### 13.5 Approval interruption

Timeout, service restart, missing administrator routing, or broker failure all deny the operation. Pending work is never resumed automatically after restart.

### 13.6 Concurrency

The gateway serializes turns per session and permits bounded concurrency across sessions. Approval decisions use a database transaction so simultaneous administrator responses cannot both win.

## 14. Audit

Every accepted inbound message and every tool-policy decision gets a correlation ID. Audit records include:

- Requester identity and role.
- Origin platform, chat type, chat ID, and session key.
- Tool name or memory operation.
- Redacted arguments and expected effect.
- Policy directive.
- Approval code hash, approver, decision, and optional reason.
- Start, decision, completion, and delivery timestamps.
- Final status and redacted error.

The audit log never stores Zalo cookies, bridge tokens, API keys, passwords, or raw secret-bearing command strings. Audit records are append-only through the plugin interface. This is an application-level audit trail, not a tamper-proof ledger against a VPS administrator with filesystem access.

## 15. Deployment

The Linux VPS runs two systemd units:

1. hermes-zalo-company-bridge.service for the Node.js transport.
2. hermes-gateway.service for Hermes with the company Zalo platform enabled.

The bridge service starts first. Hermes depends on bridge health. Both services use a dedicated unprivileged Unix account, restricted filesystem access, restart-on-failure, and journal redaction.

Installation order:

1. Install Node.js 22, Python 3.11, and Hermes v0.19.0 or newer.
2. Install fork dependencies from the lockfile.
3. Install and enable the standalone Hermes platform plugin.
4. Create config and secret files with restricted permissions.
5. Run QR login.
6. Run configuration validation and security smoke checks.
7. Start both services manually and run acceptance tests.
8. Enable systemd autostart only after acceptance passes.

## 16. Testing Strategy

### 16.1 Node unit tests

- Login state and credential permissions.
- Normalization for direct messages, groups, mentions, attachments, and self-messages.
- Reconnect scheduling.
- Inbound and outbound deduplication behavior.
- Required bridge authentication.
- Absence of removed routes.
- Multipart attachment handling without arbitrary paths.

### 16.2 Python unit tests

- Identity and group allowlists.
- Direct and group session keys.
- Mention gating.
- Tool allow, approve, and block decisions.
- Indirect memory mutation detection.
- Approval code parsing, expiry, single use, and first-decision-wins behavior.
- Redaction and audit records.

### 16.3 Integration tests

Tests use a fake Zalo transport, the real plugin loader, and a temporary HERMES_HOME. They prove:

- Unauthorized traffic never reaches an agent.
- Authorized direct and group messages enter the correct session.
- Read-only tools execute immediately.
- Sensitive tools block and resume only after an administrator decision.
- Employee memory proposals change memory only after approval.
- Sensitive group outputs are delivered privately.
- Restarts and timeouts deny pending operations.

### 16.4 Concurrency and failure tests

- Multiple employees run without session cross-talk.
- Two administrators decide simultaneously and only one wins.
- Duplicate Zalo events create one turn.
- A Zalo delivery failure does not rerun a tool.
- Cookie expiry alerts administrators and stops command processing.

### 16.5 Security and packaging tests

- Production dependency audit and signature verification.
- Secret-pattern scan.
- Syntax and import checks for JavaScript and Python.
- npm package dry-run inspection.
- File permission checks.
- Loopback bind and token enforcement.
- Tests that forbidden routes return not found.
- Linux systemd install, restart, and fresh-boot smoke tests.

## 17. Acceptance Criteria

The release is ready only when all of the following are demonstrated:

1. A non-allowlisted Zalo ID cannot invoke Hermes or any tool.
2. An authorized direct message receives a response in the correct private session.
3. An approved group responds only to an allowlisted sender who mentions the assistant.
4. Direct history never appears in a group session or another employee's direct session.
5. Shared memory is readable everywhere but mutates only after administrator approval.
6. Read-only tools run immediately.
7. Sensitive tools remain blocked until one administrator approves.
8. Denial, timeout, and restart never execute the pending operation.
9. Two concurrent administrator decisions produce one final verdict.
10. Generic API passthrough, credential export, and unrelated Zalo administration routes are absent.
11. Cookie and bridge secrets are absent from HTTP responses, approval prompts, and logs.
12. Duplicate inbound events create one agent turn and one tool-call sequence.
13. Failed Zalo delivery never reruns an already completed tool.
14. Every accepted operation has a complete, redacted audit chain.
15. Both systemd services recover after a VPS reboot and require no QR scan while the saved session remains valid.

## 18. Residual Risks

- zca-js uses an unofficial personal-account Zalo API. Zalo may challenge, restrict, or lock the company account. The company must use a dedicated account, conservative rates, and a documented QR recovery procedure.
- Zalo ID proves control of a Zalo account, not the physical identity of the employee. A compromised allowlisted account inherits that employee's access until an administrator removes it from configuration.
- All employees share the same read visibility within configured company workspace roots and shared memory. Department-level document permissions are outside the first release.
- A malicious document or message may attempt prompt injection. Deterministic policy hooks and approval gates remain authoritative, but administrators must still inspect sensitive requests before approving them.
- Third-party email and internal systems may not provide idempotency. When the outcome is uncertain, the assistant reports the uncertainty and does not retry automatically.
- The application-level audit database can be altered by a privileged VPS operator. External log shipping or cryptographic audit sealing is outside the first release.

## 19. Design Decisions

- Use the version-1.0.9 plugin fork instead of rewriting the bridge or modifying Hermes core.
- Operate one company Zalo account on one Linux VPS.
- Restrict access to configured employees and approved groups.
- Use direct sessions per employee and shared sessions per group.
- Share company memory across sessions.
- Route employee memory proposals to administrators for approval.
- Use role-aware one-time approval for sensitive tools.
- Send approval requests privately to all administrators; first decision wins.
- Keep the fork private and company-specific.
- Preserve a minimal Zalo transport surface and remove unrelated automation APIs.
