# 小喵创作室完整运营后台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前单页审核界面升级为粉蓝赛博猫娘风格的六页本机运营后台，同时保持人工优先、凭证隔离、幂等发布和紧急停止等安全约束。

**Architecture:** 继续使用 FastAPI、Jinja 和原生 JavaScript。服务器渲染页面通过独立 `DashboardService` 读取 SQLAlchemy 记录，写操作保留在动作路由中；共享模板负责导航和全局安全状态，页面模板只消费 Pydantic 视图模型。

**Tech Stack:** Python 3.11–3.12、FastAPI、Jinja2、SQLAlchemy 2.x、Pydantic 2.x、原生 CSS/JavaScript、Pytest、Ruff。

## Global Constraints

- 默认运行模式必须保持 `manual_only`，默认自动回复白名单为空。
- 管理后台只绑定 `127.0.0.1`；本次不增加登录或公网部署。
- 所有页面数字必须来自 SQLite；无数据时显示零值或空状态，不放演示数字。
- B站和模型凭证不得进入 HTML、JavaScript、数据库业务字段、日志或错误消息。
- 审核中心不提供批量批准；`visibility_unknown` 不提供直接重发。
- 动态和日报仍需人工批准；所有外部写入继续经过 `PublishJobRecord` 和 `Publisher`。
- 不增加 React、Vue、第三方图表库或外部字体。
- 所有代码修改使用 TDD：先看到新测试失败，再写最小实现，再运行完整相关测试。
- 使用项目虚拟环境中的 Python。
- 使用系统中已安装的 Git。

---

## File Structure

```text
src/cyber_catgirl/
├── main.py                         # 应用装配与静态资源
├── services/
│   └── dashboard.py                # 后台只读查询与设置校验
└── web/
    ├── routes.py                   # 兼容入口，组合页面与动作路由
    ├── pages.py                    # 六个 GET 页面
    ├── actions.py                  # 审核、计划、设置和 kill switch 写操作
    ├── view_models.py              # 模板视图模型与筛选类型
    ├── templates/
    │   ├── base.html
    │   ├── dashboard.html
    │   ├── reviews.html
    │   ├── content.html
    │   ├── analytics.html
    │   ├── logs.html
    │   ├── settings.html
    │   └── components/
    │       ├── empty_state.html
    │       └── status_badge.html
    └── static/
        ├── app.css
        ├── app.js
        └── catgirl-mascot.png
tests/
├── test_dashboard_service.py
├── test_admin_pages.py
├── test_review_actions.py
├── test_content_admin.py
├── test_analytics_admin.py
├── test_logs_settings_admin.py
└── test_admin_visual_contract.py
```

---

### Task 1: 后台查询服务与六页路由骨架

**Files:**
- Create: `src/cyber_catgirl/services/dashboard.py`
- Create: `src/cyber_catgirl/web/view_models.py`
- Create: `src/cyber_catgirl/web/pages.py`
- Modify: `src/cyber_catgirl/web/routes.py`
- Modify: `src/cyber_catgirl/main.py`
- Create: `tests/test_dashboard_service.py`
- Create: `tests/test_admin_pages.py`

**Interfaces:**
- Produces: `DashboardService.overview() -> DashboardOverview`
- Produces: `DashboardService.pending_reviews(filters: ReviewFilters) -> list[ReviewItem]`
- Produces: `DashboardService.content_plans() -> list[ContentPlanItem]`
- Produces: `DashboardService.analytics(days: int) -> AnalyticsView`
- Produces: `DashboardService.logs(filters: LogFilters) -> list[LogItem]`
- Produces: `build_page_router(session_factory, state) -> APIRouter`
- Preserves: `cyber_catgirl.web.routes.build_router(session_factory, state) -> APIRouter`

- [ ] **Step 1: Write failing overview and page-route tests**

```python
# tests/test_dashboard_service.py
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.services.dashboard import DashboardService


def test_overview_counts_database_records():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions() as session:
        session.add(EventRecord(event_id="comment_1", event_type="new_comment"))
        session.add(DraftRecord(draft_type="reply", content="你好喵", risk_level="low", review_status="pending"))
        session.add(PublishJobRecord(idempotency_key="reply:1", status="failed"))
        session.commit()

    view = DashboardService(sessions).overview()

    assert view.new_comments == 1
    assert view.pending_reviews == 1
    assert view.failed_jobs == 1
```

```python
# tests/test_admin_pages.py
from fastapi.testclient import TestClient
from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app


def test_all_admin_pages_are_registered():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    client = TestClient(create_app(Settings(), session_factory=sessions))
    for path in ["/", "/reviews", "/content", "/analytics", "/logs", "/settings"]:
        response = client.get(path)
        assert response.status_code == 200, path
```

- [ ] **Step 2: Run tests and confirm the missing service/routes fail**

Run:

```powershell
& $PY -m pytest tests/test_dashboard_service.py tests/test_admin_pages.py -v
```

Expected: collection fails because `cyber_catgirl.services.dashboard` is missing, then page tests return 404 until routes are registered.

- [ ] **Step 3: Add exact view-model contracts**

```python
# src/cyber_catgirl/web/view_models.py
from datetime import date, datetime
from pydantic import BaseModel, Field


class DashboardOverview(BaseModel):
    new_comments: int = 0
    replied_today: int = 0
    pending_reviews: int = 0
    failed_jobs: int = 0
    recent_reviews: list["ReviewItem"] = Field(default_factory=list)
    recent_activity: list["LogItem"] = Field(default_factory=list)


class ReviewFilters(BaseModel):
    draft_type: str | None = None
    risk_level: str | None = None
    query: str = ""


class ReviewItem(BaseModel):
    id: int
    draft_type: str
    content: str
    risk_level: str
    review_status: str
    created_at: datetime


class ContentPlanItem(BaseModel):
    id: int
    schedule_key: str
    prompt: str
    category: str
    run_at: datetime
    enabled: bool


class AnalyticsPoint(BaseModel):
    metric_date: date
    unique_users: int
    comment_count: int
    replied_count: int
    review_count: int
    failed_count: int


class AnalyticsView(BaseModel):
    days: int
    points: list[AnalyticsPoint]


class LogFilters(BaseModel):
    status: str | None = None
    action: str | None = None


class LogItem(BaseModel):
    kind: str
    title: str
    status: str
    detail: str
    created_at: datetime
```

- [ ] **Step 4: Implement `DashboardService` queries**

Implement `overview()` with SQLAlchemy `func.count()`, `pending_reviews()` ordered newest first, `content_plans()` ordered by `run_at`, `analytics()` restricted to 7 or 14 days, and `logs()` merging publish jobs and audit rows after JSON parsing. Never pass `details_json` directly to templates.

- [ ] **Step 5: Register six temporary server-rendered page routes**

Create `build_page_router()` with GET routes for all six paths. Each route calls one `DashboardService` method and returns a minimal `HTMLResponse` until Task 2 installs templates. Keep `build_router()` as the compatibility aggregator that includes page and action routers.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
& $PY -m pytest tests/test_dashboard_service.py tests/test_admin_pages.py tests/test_admin.py -v
& $PY -m ruff check src tests
```

Expected: all selected tests pass and Ruff reports no errors.

Commit: `feat: add admin dashboard query layer`.

---

### Task 2: 共享应用外壳、粉蓝视觉系统与猫娘资产

**Files:**
- Create: `src/cyber_catgirl/web/templates/base.html`
- Create: `src/cyber_catgirl/web/templates/dashboard.html`
- Create: `src/cyber_catgirl/web/templates/components/empty_state.html`
- Create: `src/cyber_catgirl/web/templates/components/status_badge.html`
- Replace: `src/cyber_catgirl/web/static/app.css`
- Replace: `src/cyber_catgirl/web/static/app.js`
- Create: `src/cyber_catgirl/web/static/catgirl-mascot.png`
- Modify: `src/cyber_catgirl/web/pages.py`
- Create: `tests/test_admin_visual_contract.py`

**Interfaces:**
- Consumes: `DashboardOverview` and `RuntimeState`
- Produces: shared Jinja macros and DOM hooks `data-action`, `data-confirm`, `data-toast-region`

- [ ] **Step 1: Write failing visual-contract tests**

```python
def test_dashboard_has_navigation_safety_controls_and_real_counts(client, sessions):
    response = client.get("/")
    assert 'aria-label="主导航"' in response.text
    assert 'data-action="kill-switch"' in response.text
    assert 'href="/reviews"' in response.text
    assert 'data-metric="pending-reviews"' in response.text
    assert "catgirl-mascot.png" in response.text


def test_html_has_no_inline_credential_values(client, monkeypatch):
    monkeypatch.setenv("BILI_SESSDATA", "secret-cookie-value")
    assert "secret-cookie-value" not in client.get("/").text
```

- [ ] **Step 2: Run the tests and confirm missing DOM contracts fail**

Run: `& $PY -m pytest tests/test_admin_visual_contract.py -v`

Expected: assertions fail because the shared shell and metric hooks are absent.

- [ ] **Step 3: Generate the mascot asset**

Use the `imagegen` skill with this exact brief: “transparent-background half-body anime cyber catgirl mascot, original adult character, pastel Bilibili pink and sky blue palette, short gradient hair, small futuristic headset and cat ears, friendly focused expression, clean cel shading, no text, no logos, no watermark, centered composition, dashboard UI asset.” Save the selected PNG as `src/cyber_catgirl/web/static/catgirl-mascot.png`.

- [ ] **Step 4: Build the shared template shell**

`base.html` must contain skip navigation, the six navigation links, current-page state, global run-mode badge, credential-free connector badge, a persistent emergency-stop button, `main` content block, application dialog, and `aria-live` Toast region.

- [ ] **Step 5: Implement the approved dashboard design**

Use the exact palette from the design spec. Render zero values when no records exist, show the mascot only in the hero, and use the empty-state component when there are no recent reviews or activities.

- [ ] **Step 6: Implement global JavaScript interactions**

Replace browser `alert` and `confirm` with one accessible `<dialog>`. `app.js` must expose `requestAction(url, options)`, keep edited text until success, render API error `detail` into Toast, and reload only after successful state-changing actions.

- [ ] **Step 7: Run tests, open desktop/mobile views, and commit**

Run:

```powershell
& $PY -m pytest tests/test_admin_visual_contract.py tests/test_admin_pages.py tests/test_admin.py -v
& $PY -m ruff check src tests
```

Expected: visual contracts and existing admin behavior pass.

Commit: `feat: add neko studio dashboard shell`.

---

### Task 3: 审核中心与安全动作路由

**Files:**
- Create: `src/cyber_catgirl/web/actions.py`
- Create: `src/cyber_catgirl/web/templates/reviews.html`
- Modify: `src/cyber_catgirl/web/pages.py`
- Modify: `src/cyber_catgirl/web/routes.py`
- Create: `tests/test_review_actions.py`

**Interfaces:**
- Consumes: `DashboardService.pending_reviews(ReviewFilters)`
- Produces: `POST /api/drafts/{id}/approve`, `/edit-and-approve`, `/reject`
- Produces: `GET /reviews?draft_type=&risk_level=&query=`

- [ ] **Step 1: Write failing filter and safety tests**

```python
def test_reviews_filter_by_risk_and_type(client, seeded_drafts):
    response = client.get("/reviews?draft_type=reply&risk_level=low")
    assert "低风险回复" in response.text
    assert "中风险日报" not in response.text


def test_reviews_never_offer_retry_for_visibility_unknown(client, visibility_unknown_job):
    response = client.get("/reviews")
    assert "人工核验" in response.text
    assert 'data-action="retry"' not in response.text


def test_kill_switch_blocks_edit_and_approve(client, pending_draft):
    client.post("/api/system/kill-switch", json={"enabled": True})
    response = client.post(
        f"/api/drafts/{pending_draft.id}/edit-and-approve",
        json={"content": "编辑后的内容"},
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Run tests and confirm filters/template fail**

Run: `& $PY -m pytest tests/test_review_actions.py -v`

Expected: review page content and action-router assertions fail.

- [ ] **Step 3: Move existing write handlers into `actions.py` without changing paths**

Extract the current kill-switch, run-mode, approve, edit-and-approve and reject logic. Keep duplicate approval returning 409 and pending jobs cancelled when kill switch is enabled.

- [ ] **Step 4: Build the review page**

Render filter controls, risk badges, source metadata, editable draft content, individual approve/reject buttons and pagination-ready list markup. For empty results, show “没有符合筛选条件的草稿” plus a clear-filters link.

- [ ] **Step 5: Run relevant tests and commit**

Run:

```powershell
& $PY -m pytest tests/test_review_actions.py tests/test_admin.py tests/test_replies.py tests/test_publishing.py -v
```

Expected: all tests pass.

Commit: `feat: add safe review center`.

---

### Task 4: 内容计划管理

**Files:**
- Modify: `src/cyber_catgirl/web/actions.py`
- Create: `src/cyber_catgirl/web/templates/content.html`
- Modify: `src/cyber_catgirl/web/pages.py`
- Create: `tests/test_content_admin.py`

**Interfaces:**
- Produces: `POST /api/content-plans`
- Produces: `POST /api/content-plans/{id}`
- Produces: `POST /api/content-plans/{id}/enabled`
- Consumes: `ScheduledContentRecord`, `ContentService`, `SchedulePolicy`

- [ ] **Step 1: Write failing create/edit/disable tests**

```python
def test_create_plan_stores_schedule_without_publish_job(client, sessions):
    response = client.post("/api/content-plans", json={
        "schedule_key": "evening-hello",
        "prompt": "写一条晚间问候",
        "category": "normal",
        "run_at": "2026-07-16T20:00:00+08:00",
    })
    assert response.status_code == 201
    with sessions() as session:
        assert session.query(ScheduledContentRecord).count() == 1
        assert session.query(PublishJobRecord).count() == 0


def test_disable_plan_keeps_record_but_marks_inactive(client, plan, sessions):
    assert client.post(f"/api/content-plans/{plan.id}/enabled", json={"enabled": False}).status_code == 200
    with sessions() as session:
        assert session.get(ScheduledContentRecord, plan.id).enabled is False
```

- [ ] **Step 2: Run tests and confirm endpoints return 404**

Run: `& $PY -m pytest tests/test_content_admin.py -v`

Expected: content-plan endpoints are missing.

- [ ] **Step 3: Add validated request models and write handlers**

Use Pydantic fields: `schedule_key` 3–128 characters, `prompt` 1–2000, `category` in `normal|daily_report`, timezone-aware `run_at`, and boolean `enabled`. Reject duplicate keys with 409 and naive datetimes with 422.

- [ ] **Step 4: Build list/calendar page**

Render month grouping, next-run time, category, enabled state and create/edit dialog. The UI must state that saving a plan “只安排草稿生成，不会直接发布”。

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
& $PY -m pytest tests/test_content_admin.py tests/test_content.py -v
& $PY -m ruff check src tests
```

Expected: admin and domain content tests pass.

Commit: `feat: manage scheduled content plans`.

---

### Task 5: 互动数据趋势页

**Files:**
- Modify: `src/cyber_catgirl/services/dashboard.py`
- Create: `src/cyber_catgirl/web/templates/analytics.html`
- Modify: `src/cyber_catgirl/web/pages.py`
- Create: `tests/test_analytics_admin.py`

**Interfaces:**
- Consumes: `DailyMetricRecord`
- Produces: `DashboardService.analytics(days: Literal[7, 14]) -> AnalyticsView`
- Produces: inline SVG chart points computed server-side from real metrics

- [ ] **Step 1: Write failing trend and missing-date tests**

```python
def test_analytics_uses_database_metrics(client, seeded_metrics):
    response = client.get("/analytics?days=7")
    assert "55" in response.text
    assert "data-series=\"comment_count\"" in response.text


def test_analytics_missing_day_is_marked_without_interpolation(service):
    view = service.analytics(days=7)
    missing = next(point for point in view.points if point.metric_date.isoformat() == "2026-07-13")
    assert missing.has_data is False
    assert missing.comment_count == 0
```

- [ ] **Step 2: Run tests and confirm `has_data` contract is absent**

Run: `& $PY -m pytest tests/test_analytics_admin.py -v`

Expected: model validation or assertion fails because missing dates are not represented.

- [ ] **Step 3: Implement continuous date buckets**

Extend `AnalyticsPoint` with `has_data: bool`. For each requested calendar day, use the stored row or create a zero-valued view point with `has_data=False`; do not insert missing points into the database.

- [ ] **Step 4: Render accessible local charts**

Use an inline SVG polyline for each selected metric and include a table with the same numbers for screen readers. Provide 7-day and 14-day links; reject other values by normalizing to 7.

- [ ] **Step 5: Run tests and commit**

Run: `& $PY -m pytest tests/test_analytics_admin.py -v`

Expected: trend and missing-date tests pass.

Commit: `feat: add grounded interaction analytics`.

---

### Task 6: 运行日志与安全设置

**Files:**
- Modify: `src/cyber_catgirl/services/dashboard.py`
- Modify: `src/cyber_catgirl/web/actions.py`
- Create: `src/cyber_catgirl/web/templates/logs.html`
- Create: `src/cyber_catgirl/web/templates/settings.html`
- Modify: `src/cyber_catgirl/web/pages.py`
- Modify: `src/cyber_catgirl/config.py`
- Create: `tests/test_logs_settings_admin.py`

**Interfaces:**
- Produces: `GET /logs?status=&action=`
- Produces: `POST /api/system/settings`
- Produces: `CredentialStatus(bilibili: bool, llm: bool)` with booleans only
- Preserves: `POST /api/system/run-mode` and `/api/system/kill-switch`

- [ ] **Step 1: Write failing redaction and settings tests**

```python
def test_logs_never_render_nested_credentials(client, audit_with_secret):
    response = client.get("/logs")
    assert "secret-cookie" not in response.text
    assert "[REDACTED]" in response.text


def test_empty_allowlist_cannot_enable_limited_auto(client):
    response = client.post("/api/system/settings", json={
        "run_mode": "limited_auto",
        "auto_reply_allowlist": [],
        "poll_seconds": 60,
    })
    assert response.status_code == 422


def test_settings_show_presence_not_credential_value(client, monkeypatch):
    monkeypatch.setenv("BILI_SESSDATA", "secret-cookie")
    monkeypatch.setenv("BILI_JCT", "secret-csrf")
    response = client.get("/settings")
    assert "已配置" in response.text
    assert "secret-cookie" not in response.text
    assert "secret-csrf" not in response.text
```

- [ ] **Step 2: Run tests and confirm page/API behavior fails**

Run: `& $PY -m pytest tests/test_logs_settings_admin.py -v`

Expected: settings endpoint and pages are incomplete.

- [ ] **Step 3: Implement log normalization and filtering**

Use `AuditService` redaction recursively before constructing each `LogItem`. Display `platform_id` and idempotency keys, but never display environment variables. Mark `visibility_unknown` with the fixed instruction “平台可能已写入，请到 B站人工核验；系统不会自动重发”。

- [ ] **Step 4: Implement settings validation**

Add a request model with `run_mode`, `auto_reply_allowlist: list[str]` and `poll_seconds >= 30`. Normalize IDs by stripping whitespace and deduplicating. Refuse `limited_auto` when the normalized set is empty. Persist non-secret values to `SystemSettingRecord` and update runtime state only after the transaction commits.

- [ ] **Step 5: Render settings and logs pages**

Settings must show boolean credential presence, current mode, allowlist and polling interval. Logs must provide filters, empty state, status badges, timestamps and expandable already-redacted details.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
& $PY -m pytest tests/test_logs_settings_admin.py tests/test_ingestion.py tests/test_admin.py -v
& $PY -m ruff check src tests
```

Expected: security settings, redaction and existing admin tests pass.

Commit: `feat: add secure operations logs and settings`.

---

### Task 7: 响应式、无障碍、视觉 QA 与交付文档

**Files:**
- Modify: `src/cyber_catgirl/web/static/app.css`
- Modify: `src/cyber_catgirl/web/static/app.js`
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `tests/test_admin_visual_contract.py`

**Interfaces:**
- Produces: stable desktop, narrow desktop and mobile layouts
- Produces: keyboard-operable dialogs, visible focus, reduced-motion behavior

- [ ] **Step 1: Add failing accessibility contract tests**

```python
def test_every_page_has_skip_link_landmark_and_dialog(client):
    for path in ["/", "/reviews", "/content", "/analytics", "/logs", "/settings"]:
        html = client.get(path).text
        assert 'href="#main-content"' in html
        assert 'id="main-content"' in html
        assert '<dialog' in html
        assert 'aria-live="polite"' in html


def test_styles_include_mobile_and_reduced_motion_contracts():
    css = Path("src/cyber_catgirl/web/static/app.css").read_text("utf-8")
    assert "@media (max-width: 720px)" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ":focus-visible" in css
```

- [ ] **Step 2: Run tests and confirm missing CSS contracts fail**

Run: `& $PY -m pytest tests/test_admin_visual_contract.py -v`

Expected: mobile or reduced-motion assertions fail until final polish is present.

- [ ] **Step 3: Finish responsive and accessibility behavior**

At `720px`, turn the sidebar into a bottom navigation, move low-frequency links into “更多”, stack metric cards two per row, and render review/log rows as cards. Ensure every interactive element has a visible `:focus-visible` outline. Disable hero and dialog motion under reduced-motion preference.

- [ ] **Step 4: Perform visual browser checks**

Start Uvicorn on `127.0.0.1:8765`. Capture and inspect the six pages at 1440×900, the workbench at 1024×768, and the workbench plus review center at 390×844. Verify no horizontal overflow, clipped dialog, hidden emergency control, illegible status badge or mascot/text collision.

- [ ] **Step 5: Update operating documentation**

Add the six page URLs, settings safety rules, mobile behavior and emergency-stop workflow to `README.md` and `docs/operations.md`. State explicitly that the dashboard does not start the live B站 worker by itself.

- [ ] **Step 6: Run final verification**

Run:

```powershell
& $PY -m pytest -q
& $PY -m ruff check src tests
```

Then start Uvicorn and verify `/api/health` returns `{"status":"ok","run_mode":"manual_only","kill_switch":false}` in a clean environment.

Expected: all tests pass, Ruff reports no errors, every page returns 200, and the service remains in manual mode.

- [ ] **Step 7: Commit the completed redesign**

Commit: `docs: finalize neko studio admin redesign`.

---

## Plan Self-Review

- Spec coverage: all six pages, the approved visual direction, mascot asset, real-data rule, responsive behavior, settings validation, redaction, kill switch and visual QA have an owning task.
- Type consistency: Tasks 1, 5 and 6 share the same `DashboardOverview`, `ReviewFilters`, `AnalyticsView`, `AnalyticsPoint`, `LogFilters` and `LogItem` contracts.
- Compatibility: existing API paths remain registered through `build_router`; existing tests continue to run in each affected task.
- Scope: no live B站 worker, credentials, external publishing, authentication framework or JavaScript build chain is added.
