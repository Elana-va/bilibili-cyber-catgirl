# Development History: From an Account Screenshot to a Controlled AI Character System

<p align="center"><a href="development-history.md">简体中文</a> · <strong>English</strong></p>

This document reconstructs how Bilibili Cyber Catgirl was actually built. The project did not emerge from a single complete blueprint; its architecture formed through repeated questions, live verification, and progressively tighter boundaries.

## Origin: How Can an Account Be Operated by a Model?

The project began with a screenshot of a Bilibili account. A catgirl persona appeared to publish posts, read comments, and interact continuously as if an LLM were operating it.

The first question was straightforward: how does a system like this work? Breaking it down revealed at least five layers: a language model for understanding and generation, persona instructions for consistent voice, a platform connector for reads and writes, scheduling and persistence for continuous operation, and human/safety controls to protect a real account.

We rejected the demo-oriented pattern of giving a model a collection of unrestricted account tools. It is quick to demonstrate but difficult to prove safe against duplicate replies, accidental publishing, prompt injection, and partial failures.

## The First Product Decision: Build the Bilibili Loop First

We considered WeChat, Douyin, and Xiaohongshu, then chose to mature one Bilibili workflow before moving reusable layers elsewhere. The target account, public content, and comment interaction were concrete enough to validate an end-to-end loop:

```text
Discover content → read comments → understand context → generate in-character text
→ assess risk → human review → guarded publish → audit the result
```

The first-generation boundary followed naturally: no live-stream control, direct messages, multi-account control, bot farms, or verification bypass.

## 2026-07-14: Safety Before Features

The repository was initialized on July 14. The earliest decisions were not visual design or catgirl dialogue. They were three system rules: human review by default, traceability for important actions, and an emergency stop at any time.

Those rules still define the current implementation. Automation is not a default behavior; it is a capability that several independent conditions must explicitly release.

## 2026-07-15: From Domain Skeleton to a Complete Console

July 15 was the main construction day, producing 55 small commits. Each capability began with a boundary and tests, then joined the larger workflow.

### 1. Domain model and persistence

The first implementation defined events, drafts, publish jobs, messages, memories, audit logs, and daily metrics. SQLAlchemy, Alembic, and SQLite made them durable.

Two problems drove the schema: rereading a comment must not create another draft, and restarting the service must not lose pagination or pending work. Platform event IDs, checkpoints, and publish idempotency keys therefore received explicit uniqueness constraints.

**Code evidence:** `src/cyber_catgirl/models.py`, `src/cyber_catgirl/services/ingestion.py`, and `migrations/`.

**Test evidence:** `tests/test_ingestion.py`, `tests/test_migrations.py`, and `tests/test_publishing.py`.

### 2. The agent is not the publisher

DeepSeek-compatible structured output was introduced without allowing the model to call Bilibili tools. The agent returns a JSON-Schema-constrained decision; policy decides whether it is ignored, sent to human review, or considered for limited automation.

User-scoped history, low-sensitivity memory, sensitive-memory rejection, and prompt-injection handling were added alongside generation. The system may remember a content preference, but it should not retain a password, address, or payment detail.

**Code evidence:** `src/cyber_catgirl/agent/`, `src/cyber_catgirl/services/memory.py`, and `src/cyber_catgirl/services/safety.py`.

**Test evidence:** `tests/test_agent.py`, `tests/test_memory.py`, `tests/test_safety.py`.

### 3. Local review console and UI redesign

The earliest UI was a plain pending-draft list. Monitoring, content planning, analytics, and settings soon required a complete operations console: desktop side navigation, mobile bottom navigation, status cards, risk badges, consistent empty states, and seven pages for the dashboard, monitor, reviews, content, analytics, logs, and settings.

The objective was not merely to “look like an AI product.” An operator should immediately see whether the system is reading, whether writing is authorized, whether failures exist, and whether the next action can affect the real account.

**Code evidence:** `src/cyber_catgirl/web/`.

**Test evidence:** `tests/test_admin_pages.py`, `tests/test_admin_visual_contract.py`, and page-specific tests.

### 4. Bilibili QR login and credential protection

Account authorization uses mobile-app QR confirmation. Cookies do not enter source code, the browser UI, or SQLite. On Windows they are protected with DPAPI in a local file. A read-only identity probe then lets the operator verify the nickname and UID.

Successful login establishes identity only; it does not enable monitoring or writing.

**Code evidence:** `src/cyber_catgirl/connectors/bilibili_login.py`, `src/cyber_catgirl/security/credential_store.py`, and `src/cyber_catgirl/services/bilibili_account.py`.

**Test evidence:** `tests/test_bilibili_login.py`, `tests/test_bilibili_account.py`, and `tests/test_credential_store.py`.

### 5. Visual DeepSeek connection

The Settings page gained a DeepSeek connection card. The API key is checked against the model-list endpoint before encrypted storage. Upstream errors are sanitized so a rejected request cannot echo the key into the page or logs.

This stage also fixed form overlap, secret echo in validation errors, and model-response compatibility.

**Code evidence:** `src/cyber_catgirl/services/deepseek_connection.py`, `src/cyber_catgirl/web/deepseek_auth.py`, and `src/cyber_catgirl/security/credential_store.py`.

**Test evidence:** `tests/test_deepseek_connection.py`, `tests/test_deepseek_auth_api.py`, and `tests/test_deepseek_credential_store.py`.

### 6. Comment monitoring and historical backfill

Monitoring grew from reading a single video into discovering recent videos and dynamic posts, reading top-level and nested comments, paging through history, persisting cursors, resuming after restarts, and backing off from platform limits.

The user explicitly required replies to comments that existed before the system was started. Historical backfill therefore became a first-class capability, not an afterthought. First-generation backfilled replies still require human review.

**Code evidence:** `src/cyber_catgirl/services/content_discovery.py`, `src/cyber_catgirl/services/comment_monitor.py`, and `src/cyber_catgirl/services/monitor_runtime.py`.

**Test evidence:** `tests/test_content_discovery.py`, `tests/test_comment_monitor.py`, and `tests/test_monitor_runtime.py`.

### 7. Preserve a path to limited automation

The chosen policy was “human review as the mainstream path, with a limited-auto channel preserved.” That channel has allowlists, rate limits, randomized delays, risk checks, and a separate write switch, all disabled by default.

This lets a verified manual trial evolve without rewriting the agent, schema, or review system.

### 8. Reliability fixes after connecting a real account

Live integration exposed issues that mocks could not: identity response changes, comment-shape differences, overlapping scheduler runs, model-schema compatibility, platform risk control, and write recovery.

Fixes added current identity-response support, repaired live synchronization, serialized content discovery, stopped writes after risk-control signals, and repeated policy checks in the runtime. The lesson was clear: a disabled-looking button is not a security boundary; the service and publisher must enforce the rule themselves.

## 2026-07-16: From a Prompt to a Versioned Persona Contract

The original persona simply asked the model to “reply like a catgirl.” Live use produced drift: inconsistent forms of address, repetitive emoticons, identical tone across scenes, and cuteness that sometimes displaced relevance.

The persona was redefined to be warmer, livelier, playful, and cyber-themed; address users as “小伙伴” by default; occasionally use “主人” in appropriate scenes; use more emoticons; and include “喵” naturally.

These decisions became the versioned `catgirl-v2` contract with deterministic validation and recent-style history. A reply now has explainable pass/fail reasons rather than only a subjective resemblance to the character.

**Code evidence:** `src/cyber_catgirl/agent/persona.py`, `src/cyber_catgirl/agent/persona_validation.py`, `src/cyber_catgirl/agent/prompts.py`, and `src/cyber_catgirl/services/style_history.py`.

**Test evidence:** `tests/test_persona.py`, `tests/test_persona_validation.py`, and `tests/test_style_history.py`.

### Regenerating 49 historical drafts

After the persona upgrade, 49 existing comment drafts were regenerated. Three engineering problems surfaced:

1. A temporary Python runtime changed and left HTTP client dependencies unusable;
2. Occasional DeepSeek read timeouts became more likely under batch concurrency;
3. Thirteen first-pass outputs completed generation but failed the persona validator.

The database was backed up online, the service moved to its own `.venv`, and regeneration proceeded in small batches. Each timeout stopped the batch, restored the affected draft, and reduced concurrency. The 13 persona failures were retried by source event. All 49 eventually became `catgirl-v2` pending-review drafts, with zero publish jobs created.

This operational event validated the original architecture: backups, source-event links, review states, and write gates prevented a model failure from becoming an account incident.

## 2026-09-10: Preparing the First Open-source Release

Before publication, the complete Git history, working tree, ignore rules, and credential paths were reviewed:

- Databases, logs, cookies, API keys, and DPAPI ciphertext remain outside Git;
- 65 historical commits were scanned without finding a real credential;
- machine-specific absolute paths were removed from public documentation;
- the MIT License, security policy, contribution guide, architecture guide, and public-facing README were added;
- the small-step history was retained so readers can inspect how the system evolved.

Representative screenshots and a bilingual documentation entry were added after the initial publication.

## What We Learned

### The hard part is not making the character speak

One cute model response is easy. Remaining relevant, non-repetitive, recoverable, and unable to publish accidentally is systems engineering.

### A persona needs verification

A prompt alone cannot ensure long-term consistency. A stable character requires a versioned contract, deterministic checks, recent style history, and a failure route.

### A real account should deny writes by default

Authorization, run mode, and auto-reply must be independent. Even if the UI is wrong, the service must reject an unauthorized write.

### Batch work must expect partial failure

Model timeouts and platform limits are normal events. Safe batch operations need checkpoints, small batches, idempotency, and preservation of old results.

### Platform behavior belongs behind a connector

The agent, persona, safety, review, and audit layers can be reused. Login, comment formats, and publish APIs belong to each platform connector.

## Next Steps

The current priority is not broader automation. It is better observability, transaction-safe batch regeneration, and more resilient platform adaptation. New platforms should retain the same principles: replaceable connectors, generation that does not imply authorization, and human review by default.

See the [Chinese 14-day trial plan](14-day-trial.md) and [operations runbook](operations.md) for trial and recovery procedures.
