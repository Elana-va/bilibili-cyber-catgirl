# B站评论监控与 AI 回复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为已连接的 B站主账号增加视频/动态评论发现、30 天/500 条历史回溯、60 秒持续监控、DeepSeek 回复草稿、人工审核以及默认关闭的受控自动回复通道。

**Architecture:** 在现有 FastAPI 单进程内运行 APScheduler，所有内容目标、采集游标、事件、草稿与发送任务均持久化到 SQLite。B站连接器只处理平台数据读写，应用服务负责调度、去重、生成、安全、审核和审计；真实写入需要运行模式、评论自动回复开关和连接器写入闸门同时开启。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2、Alembic、APScheduler 3、Pydantic 2、bilibili-api-python、httpx、Jinja2、原生 JavaScript、pytest、pytest-asyncio、Ruff。

## Global Constraints

- 当前默认保持 `run_mode=manual_only`、`comment_auto_reply_enabled=false`、B站 `write_enabled=false`。
- 监控调度周期为 60 秒；内容发现刷新周期为 10 分钟。
- 历史回溯只处理最近 30 天内容，顶级评论与楼中楼合计最多 500 条，按评论时间从新到旧。
- 每周期最多 3 页评论/楼中楼、20 个模型任务，DeepSeek 并发最多 2。
- 自动回复不要求用户白名单；限额为同一用户每日 10 条、账号每小时 60 条、账号每日 300 条，发送间隔 8～20 秒。
- 自动发送只允许低风险、有效 `REPLY`、无需人工复核且不超过 180 字的回复。
- Cookie、账号 UID、API Key、密文路径、上游认证头和内部堆栈不得进入模型上下文、API 响应或审计详情。
- 使用测试驱动开发；每个任务先观察目标测试失败，再实现最小功能并单独提交。
- 不实现微信连接器、MCP 工具层、分布式消息队列或多 Worker。

---

## File Map

### 新建

- `alembic.ini`：Alembic 项目配置。
- `migrations/env.py`：加载 SQLAlchemy 元数据和数据库 URL。
- `migrations/script.py.mako`：迁移文件模板。
- `migrations/versions/20260715_01_baseline.py`：当前数据库结构基线。
- `migrations/versions/20260715_02_comment_monitoring.py`：评论监控增量结构。
- `src/cyber_catgirl/services/migrations.py`：首次部署识别、基线标记和升级入口。
- `src/cyber_catgirl/services/priority.py`：确定性审核优先级规则。
- `src/cyber_catgirl/services/content_discovery.py`：主账号内容发现与目标落库。
- `src/cyber_catgirl/services/comment_monitor.py`：评论分页、楼中楼、回溯预算、游标与事件入库。
- `src/cyber_catgirl/services/monitor_runtime.py`：单周期编排、重试与状态汇总。
- `src/cyber_catgirl/services/runtime_settings.py`：读取和保存经过白名单约束的持久化运行设置。
- `src/cyber_catgirl/web/comment_monitor.py`：监控、草稿重生成和自动回复设置 API。
- `src/cyber_catgirl/web/templates/comment_monitor.html`：监控工作台页面。
- `src/cyber_catgirl/web/static/comment-monitor.js`：监控页面交互。
- `tests/test_migrations.py`
- `tests/test_priority.py`
- `tests/test_bilibili_comment_reader.py`
- `tests/test_content_discovery.py`
- `tests/test_comment_monitor.py`
- `tests/test_monitor_runtime.py`
- `tests/test_comment_monitor_api.py`
- `tests/test_comment_monitor_page.py`
- `tests/test_comment_monitor_e2e.py`

### 修改

- `src/cyber_catgirl/models.py`：监控目标、检查点和任务状态字段。
- `src/cyber_catgirl/db.py`：文件数据库启动迁移，内存测试保留 `create_all`。
- `src/cyber_catgirl/schemas.py`：评论楼层关系与平台目标类型。
- `src/cyber_catgirl/config.py`：监控与自动回复可调参数。
- `src/cyber_catgirl/connectors/base.py`：内容发现、评论分页和精确回复接口。
- `src/cyber_catgirl/connectors/bilibili_api.py`：视频/动态发现、楼中楼读取与精确发送。
- `src/cyber_catgirl/services/replies.py`：忽略、失败重试、安全原因和自动任务。
- `src/cyber_catgirl/services/safety.py`：去白名单、双开关和新限速。
- `src/cyber_catgirl/agent/prompts.py`：评论长度、人设和内部信息边界。
- `src/cyber_catgirl/agent/service.py`：最小化模型载荷并显式上报生成失败。
- `src/cyber_catgirl/services/publishing.py`：根评论/父评论发送、重试状态和错误码。
- `src/cyber_catgirl/services/scheduler.py`：60 秒监控和 10 分钟发现作业。
- `src/cyber_catgirl/services/dashboard.py`：审核卡来源、上下文和优先排序。
- `src/cyber_catgirl/web/routes.py`：注册监控 API 与运行时依赖。
- `src/cyber_catgirl/web/pages.py`：监控页面路由和审核来源数据。
- `src/cyber_catgirl/web/actions.py`：人工批准写入闸门与新设置模型。
- `src/cyber_catgirl/web/view_models.py`：监控与审核展示模型。
- `src/cyber_catgirl/web/templates/base.html`：增加评论监控导航。
- `src/cyber_catgirl/web/templates/reviews.html`：展示原评论、来源和楼层上下文。
- `src/cyber_catgirl/web/templates/settings.html`：自动回复配置卡。
- `src/cyber_catgirl/web/static/app.css`：监控与审核卡响应式样式。
- `src/cyber_catgirl/web/static/app.js`：重生成和写入未授权提示。
- `src/cyber_catgirl/main.py`：组装服务并管理调度器生命周期。
- `README.md`、`docs/operations.md`：运行、回溯、故障与开启写入说明。

---

### Task 1: 建立可升级数据库结构

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260715_01_baseline.py`
- Create: `migrations/versions/20260715_02_comment_monitoring.py`
- Create: `src/cyber_catgirl/services/migrations.py`
- Modify: `src/cyber_catgirl/models.py`
- Modify: `src/cyber_catgirl/db.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: `upgrade_database(database_url: str) -> None`。
- Produces: `MonitoredContentRecord`、`MonitorCheckpointRecord` 以及扩展后的 `EventRecord`、`DraftRecord`、`PublishJobRecord`。
- Consumes: SQLAlchemy `Base.metadata` 和项目根目录下的 Alembic 配置。

- [ ] **Step 1: 写出迁移失败测试**

```python
def alembic_config(url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def execute(url: str, sql: str) -> None:
    with create_engine(url).begin() as connection:
        connection.execute(text(sql))


def scalar(url: str, sql: str):
    with create_engine(url).connect() as connection:
        return connection.scalar(text(sql))


def table_exists(url: str, name: str) -> bool:
    return name in inspect(create_engine(url)).get_table_names()


def column_exists(url: str, table: str, name: str) -> bool:
    return name in {column["name"] for column in inspect(create_engine(url)).get_columns(table)}


def create_legacy_schema(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("create table events (id integer primary key, event_id varchar(128) unique not null, event_type varchar(64) not null, payload_json text not null default '{}', status varchar(32) not null default 'new', created_at datetime)"))
        connection.execute(text("create table drafts (id integer primary key, content_key varchar(128) unique, event_id integer, draft_type varchar(32) not null, content text not null, risk_level varchar(16) not null, review_status varchar(32) not null default 'pending', agent_version varchar(64) not null default 'catgirl-v1', stats_snapshot_json text not null default '{}', created_at datetime)"))
        connection.execute(text("create table publish_jobs (id integer primary key, draft_id integer, idempotency_key varchar(192) unique not null, status varchar(32) not null, platform_id varchar(128), attempts integer not null default 0, created_at datetime)"))


def stamp_baseline(url: str) -> None:
    config = alembic_config(url)
    command.stamp(config, "20260715_01")


def test_upgrade_from_baseline_preserves_existing_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    create_legacy_schema(url)
    stamp_baseline(url)
    execute(url, "insert into events (event_id, event_type, payload_json, status) values ('comment_1', 'new_comment', '{}', 'new')")

    upgrade_database(url)

    assert scalar(url, "select event_id from events") == "comment_1"
    assert table_exists(url, "monitored_contents")
    assert column_exists(url, "events", "priority")


def test_unversioned_legacy_database_is_stamped_then_upgraded(tmp_path):
    url = f"sqlite:///{tmp_path / 'unversioned.db'}"
    create_legacy_schema(url)

    upgrade_database(url)

    assert scalar(url, "select version_num from alembic_version") == "20260715_02"


def test_file_database_is_backed_up_before_schema_upgrade(tmp_path):
    path = tmp_path / "live.db"
    create_legacy_schema(f"sqlite:///{path}")
    upgrade_database(f"sqlite:///{path}")
    assert list((tmp_path / "backups").glob("live-*.db"))
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_migrations.py -v`
Expected: FAIL，提示 `cyber_catgirl.services.migrations` 或迁移 revision 不存在。

- [ ] **Step 3: 增加模型和两段迁移**

在 `models.py` 中定义以下核心字段：

```python
class MonitoredContentRecord(Base):
    __tablename__ = "monitored_contents"
    __table_args__ = (UniqueConstraint("platform_content_id", name="uq_content_platform_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_content_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment_oid: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MonitorCheckpointRecord(Base):
    __tablename__ = "monitor_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    checkpoint_key: Mapped[str] = mapped_column(String(192), unique=True, nullable=False)
    cursor_value: Mapped[str | None] = mapped_column(String(512))
    state_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
```

迁移 `20260715_01` 是无操作基线，用于标记当前已部署结构。迁移 `20260715_02` 创建两张表，并为既有表增加：

```python
op.add_column("events", sa.Column("priority", sa.String(16), nullable=False, server_default="normal"))
op.add_column("events", sa.Column("monitored_content_id", sa.Integer(), nullable=True))
op.add_column("events", sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"))
op.add_column("events", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
op.add_column("events", sa.Column("last_error_code", sa.String(64), nullable=True))
op.add_column("drafts", sa.Column("safety_reasons_json", sa.Text(), nullable=False, server_default="[]"))
op.add_column("drafts", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
op.add_column("publish_jobs", sa.Column("source", sa.String(16), nullable=False, server_default="manual"))
op.add_column("publish_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
op.add_column("publish_jobs", sa.Column("last_error_code", sa.String(64), nullable=True))
op.add_column("publish_jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
```

- [ ] **Step 4: 实现升级入口与内存数据库兼容**

```python
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade_database(database_url: str) -> None:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    if not tables:
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return
    if tables and "alembic_version" not in tables:
        command.stamp(config, "20260715_01")
    current = current_revision(engine)
    head = ScriptDirectory.from_config(config).get_current_head()
    if current == head:
        return
    backup_sqlite_database(database_url)
    command.upgrade(config, "head")
```

`create_session_factory()` 对 `:memory:` 使用 `Base.metadata.create_all()`；文件数据库先调用 `upgrade_database()`，再建立 sessionmaker。

`backup_sqlite_database()` 只接受解析后确认为普通 SQLite 文件的绝对路径，备份到同级 `backups/<stem>-YYYYMMDD-HHMMSS.db`；内存数据库和非 SQLite URL 跳过文件复制。

- [ ] **Step 5: 运行迁移测试与模型回归测试**

Run: `pytest tests/test_migrations.py tests/test_schemas.py -v`
Expected: PASS；旧事件保留，新表和新增列存在。

- [ ] **Step 6: 提交**

```bash
git add alembic.ini migrations src/cyber_catgirl/models.py src/cyber_catgirl/db.py src/cyber_catgirl/services/migrations.py tests/test_migrations.py
git commit -m "feat: add durable comment monitoring schema"
```

---

### Task 2: 定义评论目标、楼层关系和优先级

**Files:**
- Modify: `src/cyber_catgirl/schemas.py`
- Create: `src/cyber_catgirl/services/priority.py`
- Test: `tests/test_priority.py`
- Modify Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `PlatformContentTarget`、扩展后的 `InteractionEvent.root_comment_id`。
- Produces: `classify_review_priority(content: str, account_name: str) -> str`，只返回 `priority` 或 `normal`。

- [ ] **Step 1: 写出目标和优先级测试**

```python
@pytest.mark.parametrize("content", ["这是怎么接入的？", "请问模型是什么", "@听晴sil 在吗"])
def test_questions_and_mentions_are_priority(content):
    assert classify_review_priority(content, "听晴sil") == "priority"


def test_plain_reaction_is_normal():
    assert classify_review_priority("好可爱喵", "听晴sil") == "normal"


def test_nested_event_keeps_root_and_parent_ids():
    event = InteractionEvent(**event_payload(root_comment_id="100", parent_comment_id="101"))
    assert event.root_comment_id == "100"
    assert event.parent_comment_id == "101"
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_priority.py tests/test_schemas.py -v`
Expected: FAIL，缺少分类器和 `root_comment_id`。

- [ ] **Step 3: 实现最小领域类型和确定性规则**

```python
class PlatformContentTarget(BaseModel):
    platform_content_id: str = Field(min_length=1, max_length=128)
    display_type: Literal["video", "dynamic_text", "dynamic_draw"]
    comment_oid: str = Field(min_length=1, max_length=128)
    resource_type: Literal["video", "article", "dynamic", "dynamic_draw"]
    title: str = Field(default="", max_length=256)
    published_at: datetime


QUESTION_MARKERS = ("?", "？", "请问", "怎么", "为什么", "能否", "可以吗", "是什么")


def classify_review_priority(content: str, account_name: str) -> str:
    compact = content.casefold().replace(" ", "")
    account = account_name.casefold().replace(" ", "")
    if any(marker in compact for marker in QUESTION_MARKERS):
        return "priority"
    if account and (f"@{account}" in compact or account in compact):
        return "priority"
    return "normal"
```

为 `InteractionEvent` 增加 `root_comment_id: str | None`，保持旧 JSON 可解析。

- [ ] **Step 4: 运行测试和格式检查**

Run: `pytest tests/test_priority.py tests/test_schemas.py -v && ruff check src/cyber_catgirl/schemas.py src/cyber_catgirl/services/priority.py tests/test_priority.py`
Expected: PASS，Ruff 无输出。

- [ ] **Step 5: 提交**

```bash
git add src/cyber_catgirl/schemas.py src/cyber_catgirl/services/priority.py tests/test_priority.py tests/test_schemas.py
git commit -m "feat: model comment threads and review priority"
```

---

### Task 3: 扩展 B站读取连接器

**Files:**
- Modify: `src/cyber_catgirl/connectors/base.py`
- Modify: `src/cyber_catgirl/connectors/bilibili_api.py`
- Modify: `src/cyber_catgirl/connectors/fake.py`
- Create Test: `tests/test_bilibili_comment_reader.py`
- Modify Test: `tests/test_bilibili_adapter.py`

**Interfaces:**
- Produces: `discover_contents(account_id: str, cursor: str | None) -> tuple[list[PlatformContentTarget], str | None]`。
- Produces: `fetch_comment_page(target: PlatformContentTarget, cursor: str | None) -> CommentPage`。
- Produces: `fetch_subcomment_page(target, root_comment_id, cursor) -> CommentPage`。
- Produces: `reply_to_comment(comment_oid, resource_type, root_comment_id, parent_comment_id, text) -> str`。

- [ ] **Step 1: 写出 SDK 标准化测试**

```python
async def test_discovers_video_and_dynamic_comment_targets():
    connector = BilibiliApiConnector(credential=object(), sdk=DiscoverySdk())
    targets, cursor = await connector.discover_contents("1801157579", None)
    assert [(t.display_type, t.resource_type) for t in targets] == [
        ("video", "video"),
        ("dynamic_draw", "article"),
    ]


async def test_nested_reply_preserves_root_and_direct_parent():
    page = await connector.fetch_subcomment_page(target, "100", None)
    assert page.events[0].root_comment_id == "100"
    assert page.events[0].parent_comment_id == "101"


async def test_writer_passes_root_and_parent_to_sdk():
    await connector.reply_to_comment("42", "video", "100", "101", "收到喵")
    assert sdk.sent == {"oid": 42, "root": 100, "parent": 101, "text": "收到喵"}
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_bilibili_comment_reader.py tests/test_bilibili_adapter.py -v`
Expected: FAIL，连接器构造函数和新方法尚不存在。

- [ ] **Step 3: 增加连接器协议和分页结果**

```python
@dataclass(frozen=True)
class CommentPage:
    events: list[InteractionEvent]
    next_cursor: str | None
    root_ids_with_replies: tuple[str, ...] = ()


class BilibiliPort(Protocol):
    async def discover_contents(self, account_id: str, cursor: str | None) -> tuple[list[PlatformContentTarget], str | None]: ...
    async def fetch_comment_page(self, target: PlatformContentTarget, cursor: str | None) -> CommentPage: ...
    async def fetch_subcomment_page(self, target: PlatformContentTarget, root_comment_id: str, cursor: str | None) -> CommentPage: ...
    async def reply_to_comment(self, comment_oid: str, resource_type: str, root_comment_id: str, parent_comment_id: str | None, text: str) -> str: ...
```

- [ ] **Step 4: 实现视频、动态与楼中楼 SDK facade**

连接 `User.get_videos()`、`User.get_dynamics_new()`、`Dynamic.get_info()`、`comment.get_comments()` 和 `Comment.get_sub_comments()`；从动态 `basic.comment_type` 与 `rid_str` 得到评论资源类型和 `oid`。标准化规则：顶级评论 `root_comment_id=rpid`、`parent_comment_id=None`；楼中楼读取响应中的 `root` 与 `parent`。

发送调用必须显式传入：

```python
return await comment.send_comment(
    text=text,
    oid=int(comment_oid),
    type_=self._resource_type(resource_type),
    root=int(root_comment_id),
    parent=int(parent_comment_id) if parent_comment_id else None,
    credential=credential,
)
```

- [ ] **Step 5: 运行连接器测试**

Run: `pytest tests/test_bilibili_comment_reader.py tests/test_bilibili_adapter.py -v`
Expected: PASS；动态资源映射、嵌套关系和发送参数正确。

- [ ] **Step 6: 提交**

```bash
git add src/cyber_catgirl/connectors tests/test_bilibili_comment_reader.py tests/test_bilibili_adapter.py
git commit -m "feat: discover Bilibili content and nested comments"
```

---

### Task 4: 持久化账号内容发现

**Files:**
- Create: `src/cyber_catgirl/services/content_discovery.py`
- Test: `tests/test_content_discovery.py`

**Interfaces:**
- Consumes: `BilibiliPort.discover_contents()`、`MonitoredContentRecord` 和检查点表。
- Produces: `ContentDiscoveryService.run_once(now: datetime) -> DiscoveryResult`。

- [ ] **Step 1: 写出 30 天过滤、upsert 和游标测试**

```python
async def test_discovery_keeps_recent_targets_and_updates_existing(sessions):
    service = ContentDiscoveryService(sessions, FakeDiscoveryPort([...]), account_id="1801157579")
    result = await service.run_once(datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert result.inserted == 2
    assert result.skipped_old == 1
    assert load_checkpoint(sessions, "content-discovery") == "next-1"

    await service.run_once(datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert count_rows(sessions, MonitoredContentRecord) == 2
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_content_discovery.py -v`
Expected: FAIL，`ContentDiscoveryService` 不存在。

- [ ] **Step 3: 实现单页发现和事务性检查点**

```python
@dataclass(frozen=True)
class DiscoveryResult:
    inserted: int
    updated: int
    skipped_old: int
    next_cursor: str | None


async def run_once(self, now: datetime) -> DiscoveryResult:
    cursor = self.checkpoints.get("content-discovery")
    targets, next_cursor = await self.connector.discover_contents(self.account_id, cursor)
    cutoff = now - timedelta(days=30)
    with self.session_factory.begin() as session:
        for target in targets:
            if target.published_at < cutoff:
                skipped_old += 1
                continue
            self._upsert_target(session, target, now)
        self.checkpoints.set_in_session(session, "content-discovery", next_cursor)
    return DiscoveryResult(inserted, updated, skipped_old, next_cursor)
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_content_discovery.py -v`
Expected: PASS，重复发现不会创建重复目标。

- [ ] **Step 5: 提交**

```bash
git add src/cyber_catgirl/services/content_discovery.py tests/test_content_discovery.py
git commit -m "feat: persist monitored Bilibili content"
```

---

### Task 5: 实现评论、楼中楼和历史回溯监控

**Files:**
- Create: `src/cyber_catgirl/services/comment_monitor.py`
- Modify: `src/cyber_catgirl/services/ingestion.py`
- Test: `tests/test_comment_monitor.py`
- Modify Test: `tests/test_ingestion.py`

**Interfaces:**
- Consumes: `MonitoredContentRecord`、检查点、`BilibiliPort` 和账号 UID/名称。
- Produces: `CommentMonitorService.poll_once(now: datetime, page_budget: int = 3) -> MonitorPollResult`。

- [ ] **Step 1: 写出去重、自回复过滤、楼中楼和 500 条边界测试**

```python
async def test_poll_stores_top_level_and_nested_events_without_self_replies(sessions):
    result = await service.poll_once(NOW, page_budget=3)
    assert result.inserted == 2
    assert result.self_filtered == 1
    assert event(sessions, "comment_201").priority == "priority"
    nested = load_interaction(sessions, "comment_202")
    assert (nested.root_comment_id, nested.parent_comment_id) == ("201", "201")


async def test_backfill_never_imports_more_than_500_comments(sessions):
    seed_setting(sessions, "comment_backfill_imported", "499")
    result = await service.poll_once(NOW, page_budget=3)
    assert result.inserted == 1
    assert setting(sessions, "comment_backfill_imported") == "500"


async def test_platform_rate_limit_defers_target_without_losing_cursor(sessions):
    connector.error = PlatformRateLimited("limited")
    result = await service.poll_once(NOW, page_budget=3)
    target = load_target(sessions)
    assert result.error_code == "bilibili_rate_limited"
    assert target.next_poll_at == NOW + timedelta(minutes=5)
    assert load_checkpoint(sessions, "comments:target-1") == "original-cursor"
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_comment_monitor.py tests/test_ingestion.py -v`
Expected: FAIL，监控服务和持久化分页游标不存在。

- [ ] **Step 3: 实现公平目标选择和共享页预算**

```python
def _eligible_targets(session, now: datetime):
    return session.scalars(
        select(MonitoredContentRecord)
        .where(MonitoredContentRecord.active.is_(True))
        .where(or_(MonitoredContentRecord.next_poll_at.is_(None), MonitoredContentRecord.next_poll_at <= now))
        .order_by(MonitoredContentRecord.last_polled_at.asc().nullsfirst(), MonitoredContentRecord.published_at.desc())
    ).all()
```

每消费一页立即在同一事务中保存事件和对应检查点。实时游标优先；历史游标只在剩余页预算和 500 条额度均大于零时继续。唯一约束冲突计入 `duplicates`，不回滚同页的其他事件。

读取侧 `PlatformRateLimited` 按目标累计失败次数使用 5/15/60 分钟退避，不推进游标；`PlatformRiskControl` 或凭证失效暂停全局监控并记录稳定错误码；单个内容不存在或评论关闭时设置该目标 `active=false`，不影响其他目标。

- [ ] **Step 4: 实现事件标准化入库**

```python
def _store_event(self, session, event: InteractionEvent) -> str:
    if event.actor_id == self.account_id:
        return "self_filtered"
    row = EventRecord(
        event_id=event.event_id,
        event_type=event.event_type,
        payload_json=event.model_dump_json(),
        monitored_content_id=self.current_target_id,
        priority=classify_review_priority(event.content, self.account_name),
        status="new",
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return "duplicate"
    return "inserted"
```

每条事件使用 savepoint，避免单个重复记录回滚整页事务。

- [ ] **Step 5: 运行监控测试**

Run: `pytest tests/test_comment_monitor.py tests/test_ingestion.py -v`
Expected: PASS；页预算不超过 3，历史计数不超过 500。

- [ ] **Step 6: 提交**

```bash
git add src/cyber_catgirl/services/comment_monitor.py src/cyber_catgirl/services/ingestion.py tests/test_comment_monitor.py tests/test_ingestion.py
git commit -m "feat: monitor Bilibili comments with durable cursors"
```

---

### Task 6: 完善草稿生成状态和宽松自动回复安全策略

**Files:**
- Modify: `src/cyber_catgirl/config.py`
- Modify: `src/cyber_catgirl/agent/prompts.py`
- Modify: `src/cyber_catgirl/agent/service.py`
- Modify: `src/cyber_catgirl/services/replies.py`
- Modify: `src/cyber_catgirl/services/safety.py`
- Modify Test: `tests/test_config.py`
- Modify Test: `tests/test_agent.py`
- Modify Test: `tests/test_replies.py`
- Modify Test: `tests/test_safety.py`

**Interfaces:**
- Produces: `ReplyService.process_event(event_id: str) -> DraftRecord | None`，`IGNORE` 返回 `None`。
- Produces: `SafetyPolicy` 与 `SafetyCounters`，包含用户/小时/每日计数。
- Consumes: `comment_auto_reply_enabled` 和 `write_enabled` 两个独立闸门。

- [ ] **Step 1: 写出状态转换和安全闸门测试**

```python
async def test_ignore_marks_event_without_creating_draft():
    agent.decision = decision(action="ignore", content="")
    assert await service.process_event("comment_1") is None
    assert load_event().status == "ignored"


async def test_model_failure_is_retryable_without_empty_draft():
    agent.error = TimeoutError()
    with pytest.raises(ReplyGenerationError):
        await service.process_event("comment_1")
    assert load_event().status == "generation_failed"
    assert load_event().processing_attempts == 1
    assert count_drafts() == 0


async def test_model_payload_excludes_private_platform_identifiers():
    await agent.decide(event(actor_id="secret-mid", target_id="secret-oid"), memory())
    serialized = json.dumps(llm.messages, ensure_ascii=False)
    assert "公开评论" in serialized
    assert "secret-mid" not in serialized
    assert "secret-oid" not in serialized


def test_low_risk_auto_reply_does_not_require_allowlist():
    verdict = engine(auto_enabled=True, write_enabled=True).evaluate(event(), reply(), counters())
    assert verdict.allow_auto_publish is True


async def test_auto_approved_job_uses_source_and_random_delay():
    service = reply_service(auto_enabled=True, write_enabled=True, now=NOW, delay=lambda low, high: 12)
    draft = await service.process_event("comment_1")
    job = load_job_for_draft(draft.id)
    assert job.source == "auto"
    assert job.next_attempt_at == NOW + timedelta(seconds=12)


@pytest.mark.parametrize("hour,day,user", [(60, 0, 0), (0, 300, 0), (0, 0, 10)])
def test_relaxed_limits_still_block_at_boundary(hour, day, user):
    verdict = engine(auto_enabled=True, write_enabled=True).evaluate(event(), reply(), counters(hour, day, user))
    assert verdict.rate_limited is True
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_config.py tests/test_agent.py tests/test_replies.py tests/test_safety.py -v`
Expected: FAIL，现有安全引擎仍要求白名单并使用 20/100 限额。

- [ ] **Step 3: 增加精确配置字段**

```python
comment_monitor_enabled: bool = False
comment_auto_reply_enabled: bool = False
comment_backfill_days: int = Field(default=30, ge=1, le=90)
comment_backfill_limit: int = Field(default=500, ge=0, le=5000)
auto_reply_user_daily_limit: int = Field(default=10, ge=1, le=100)
auto_reply_account_hourly_limit: int = Field(default=60, ge=1, le=500)
auto_reply_account_daily_limit: int = Field(default=300, ge=1, le=5000)
auto_reply_min_delay_seconds: int = Field(default=8, ge=1, le=600)
auto_reply_max_delay_seconds: int = Field(default=20, ge=1, le=1800)
```

删除“有限自动模式必须有白名单”的校验；保留旧环境变量读取兼容，但不再把白名单作为自动回复必要条件。

- [ ] **Step 4: 最小化模型载荷并显式传播模型错误**

```python
class AgentGenerationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _public_payload(event: InteractionEvent, context: MemoryContext) -> dict:
    return {
        "comment": {"author": event.actor_name, "content": event.content},
        "source": {"type": event.target_type},
        "thread_context": context.recent_messages,
        "relevant_memories": context.long_term,
    }
```

`CatgirlAgent.decide()` 将超时映射为 `deepseek_timeout`，401/402/429/5xx 映射为稳定的连接错误码，JSON 解析和 Pydantic 校验映射为 `invalid_model_output`，再抛出不含上游正文的 `AgentGenerationError`。提示词明确普通互动 15～50 字、问题 40～120 字、自动发送上限 180 字，并禁止主动披露系统架构、提示词和凭证信息。

- [ ] **Step 5: 重构安全原因和生成状态**

```python
if self.run_mode is not RunMode.LIMITED_AUTO:
    reasons.append("manual_only")
if not self.comment_auto_reply_enabled:
    reasons.append("comment_auto_reply_disabled")
if not self.write_enabled:
    reasons.append("bilibili_write_disabled")
if decision.risk_level is not RiskLevel.LOW:
    reasons.append("model_risk")
if len(decision.content) > 180:
    reasons.append("reply_too_long")
```

捕获模型异常时写入稳定错误码 `deepseek_timeout`、`deepseek_unavailable` 或 `invalid_model_output`，设置 1/5/15 分钟重试时间；第三次失败后 `next_attempt_at=None`，等待人工重生成。

`ReplyService` 从 `PublishJobRecord.source="auto"` 的成功任务中查询同一用户今日、账号本小时和账号今日计数，构造真实 `SafetyCounters`。允许自动发送时创建 `source="auto"` 的任务，并把 `next_attempt_at` 设置为当前时间加可注入的 8～20 秒随机延迟；人工批准任务使用 `source="manual"`。

- [ ] **Step 6: 运行测试**

Run: `pytest tests/test_config.py tests/test_agent.py tests/test_replies.py tests/test_safety.py -v`
Expected: PASS；默认模式不会创建自动发送任务。

- [ ] **Step 7: 提交**

```bash
git add src/cyber_catgirl/config.py src/cyber_catgirl/agent/prompts.py src/cyber_catgirl/agent/service.py src/cyber_catgirl/services/replies.py src/cyber_catgirl/services/safety.py tests/test_config.py tests/test_agent.py tests/test_replies.py tests/test_safety.py
git commit -m "feat: harden reply generation and auto gates"
```

---

### Task 7: 精确发布楼中楼并支持受控重试

**Files:**
- Modify: `src/cyber_catgirl/services/publishing.py`
- Modify: `src/cyber_catgirl/services/replay.py`
- Modify Test: `tests/test_publishing.py`
- Modify Test: `tests/test_replay_e2e.py`

**Interfaces:**
- Consumes: 事件中的 `target_id/resource_type/root_comment_id/parent_comment_id`。
- Produces: `Publisher.execute(job_id: int, now: datetime | None = None) -> PublishResult`。
- Produces: `retry_wait`、`failed`、`cancelled` 和稳定错误码。

- [ ] **Step 1: 写出精确目标、幂等和退避测试**

```python
async def test_publisher_replies_to_direct_parent_with_root_context():
    result = await publisher.execute(job_id)
    assert connector.reply_args == ("42", "video", "100", "101", "回复喵")
    assert result.status == "succeeded"


async def test_rate_limit_moves_job_to_retry_wait():
    connector.error = PlatformRateLimited("limited")
    result = await publisher.execute(job_id, now=NOW)
    assert result.status == "retry_wait"
    assert load_job().last_error_code == "bilibili_rate_limited"
    assert load_job().next_attempt_at == NOW + timedelta(minutes=5)


async def test_terminal_or_completed_job_never_sends_twice():
    await publisher.execute(job_id)
    await publisher.execute(job_id)
    assert connector.reply_calls == 1
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_publishing.py tests/test_replay_e2e.py -v`
Expected: FAIL，Publisher 仍使用单一 `comment_id` 并直接把所有异常设为 failed。

- [ ] **Step 3: 实现平台错误映射和 5/15/60 分钟退避**

```python
RATE_LIMIT_BACKOFF = (timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60))


def retry_at(now: datetime, attempts: int) -> datetime:
    index = min(max(attempts - 1, 0), len(RATE_LIMIT_BACKOFF) - 1)
    return now + RATE_LIMIT_BACKOFF[index]
```

`PlatformRiskControl` 设置任务 `cancelled` 并调用全局写入暂停回调；`CredentialsUnavailable` 设置 `failed/bilibili_credentials_missing`；限流和临时不可用设置 `retry_wait`。

- [ ] **Step 4: 使用精确楼层参数发送并保存完成时间**

```python
platform_id = await self.connector.reply_to_comment(
    event.target_id,
    event.target_type,
    event.root_comment_id or event.event_id.removeprefix("comment_"),
    event.parent_comment_id,
    content,
)
```

可见性验证成功后写入 `completed_at`；`platform_id` 已存在但可见性未知时不再次发送。

- [ ] **Step 5: 运行发布测试**

Run: `pytest tests/test_publishing.py tests/test_replay_e2e.py -v`
Expected: PASS；重复执行没有第二次平台调用。

- [ ] **Step 6: 提交**

```bash
git add src/cyber_catgirl/services/publishing.py src/cyber_catgirl/services/replay.py tests/test_publishing.py tests/test_replay_e2e.py
git commit -m "feat: publish threaded replies with durable retry"
```

---

### Task 8: 编排单周期任务并接入 FastAPI 生命周期

**Files:**
- Create: `src/cyber_catgirl/services/monitor_runtime.py`
- Create: `src/cyber_catgirl/services/runtime_settings.py`
- Modify: `src/cyber_catgirl/services/scheduler.py`
- Modify: `src/cyber_catgirl/main.py`
- Test: `tests/test_monitor_runtime.py`
- Modify Test: `tests/test_admin.py`

**Interfaces:**
- Produces: `MonitorRuntime.run_cycle(now: datetime | None = None, force: bool = False) -> MonitorCycleResult` 和 `request_manual_cycle() -> bool`。
- Produces: `build_scheduler(runtime, settings) -> AsyncIOScheduler`。
- `create_app()` 接受可注入的 `monitor_runtime` 和 `scheduler_factory`。

- [ ] **Step 1: 写出预算、并发和生命周期测试**

```python
async def test_cycle_prioritizes_new_events_and_caps_generation_at_twenty():
    result = await runtime.run_cycle()
    assert result.pages_read <= 3
    assert result.generation_started == 20
    assert agent.max_observed_concurrency <= 2


async def test_cycle_executes_only_due_publish_jobs():
    seed_job(status="pending", next_attempt_at=NOW - timedelta(seconds=1))
    seed_job(status="retry_wait", next_attempt_at=NOW + timedelta(minutes=5))
    result = await runtime.run_cycle(now=NOW)
    assert result.publish_started == 1
    assert publisher.executed_job_ids == [1]


def test_app_lifespan_starts_and_stops_scheduler():
    scheduler = RecordingScheduler()
    app = create_app(Settings(), scheduler_factory=lambda _: scheduler)
    with TestClient(app):
        assert scheduler.started is True
    assert scheduler.stopped is True


def test_persisted_monitor_setting_is_loaded_on_restart(sessions):
    save_setting(sessions, "comment_monitor_enabled", "true")
    app = create_app(Settings(comment_monitor_enabled=False), session_factory=sessions)
    assert app.state.runtime.settings.comment_monitor_enabled is True
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_monitor_runtime.py tests/test_admin.py -v`
Expected: FAIL，运行时和 lifespan 注入点不存在。

- [ ] **Step 3: 实现单周期编排**

```python
async def run_cycle(self, now: datetime | None = None, force: bool = False) -> MonitorCycleResult:
    now = now or utc_now()
    if not force and not self.settings.comment_monitor_enabled:
        return MonitorCycleResult.disabled()
    poll = await self.comment_monitor.poll_once(now, page_budget=3)
    event_ids = self.pending_events(limit=20, newest_first=True)
    semaphore = asyncio.Semaphore(2)
    async def generate(event_id: str):
        async with semaphore:
            return await self.reply_service.process_event(event_id)
    results = await asyncio.gather(*(generate(event_id) for event_id in event_ids), return_exceptions=True)
    due_job_ids = self.due_publish_jobs(now=now, limit=5)
    publish_results = [await self.publisher.execute(job_id) for job_id in due_job_ids]
    return MonitorCycleResult.from_results(poll, results, publish_results)


def request_manual_cycle(self) -> bool:
    if self._manual_pending or self._cycle_lock.locked():
        return False
    self._manual_pending = True
    async def execute_manual() -> None:
        try:
            await self.run_cycle(force=True)
        finally:
            self._manual_pending = False
    asyncio.create_task(execute_manual())
    return True
```

- [ ] **Step 4: 注册作业和 lifespan**

```python
scheduler.add_job(runtime.run_cycle, IntervalTrigger(seconds=settings.poll_seconds), id="comment-monitor", max_instances=1, coalesce=True, replace_existing=True)
scheduler.add_job(runtime.discover_contents, IntervalTrigger(minutes=10), id="content-discovery", max_instances=1, coalesce=True, replace_existing=True)
```

FastAPI lifespan 中先启动 scheduler，退出时调用 `shutdown(wait=False)`。测试注入时不得建立真实 B站或 DeepSeek 网络连接。

`runtime_settings.py` 只允许读取预定义键并使用 Pydantic 重新校验类型。支持键包括监控开关、运行模式、kill switch、回溯天数/上限、自动回复开关、三个限额和两个延迟值；未知键忽略，非法值保留环境变量或代码默认值并写入脱敏审计错误。

- [ ] **Step 5: 运行运行时测试**

Run: `pytest tests/test_monitor_runtime.py tests/test_admin.py -v`
Expected: PASS；调度器只启动和停止一次。

- [ ] **Step 6: 提交**

```bash
git add src/cyber_catgirl/services/monitor_runtime.py src/cyber_catgirl/services/runtime_settings.py src/cyber_catgirl/services/scheduler.py src/cyber_catgirl/main.py tests/test_monitor_runtime.py tests/test_admin.py
git commit -m "feat: schedule durable comment monitoring"
```

---

### Task 9: 增加监控、重生成和自动回复 API

**Files:**
- Create: `src/cyber_catgirl/web/comment_monitor.py`
- Modify: `src/cyber_catgirl/web/routes.py`
- Modify: `src/cyber_catgirl/web/actions.py`
- Create Test: `tests/test_comment_monitor_api.py`
- Modify Test: `tests/test_review_actions.py`

**Interfaces:**
- Produces: 设计规格中的 `/api/comment-monitor/*`、`/api/reply-drafts/*`、`/api/auto-reply/settings`。
- Consumes: `MonitorRuntime`、`ReplyService`、`SystemSettingRecord` 和 `AuditService`。
- 保留现有 `/api/drafts/*` 作为兼容别名，并让新旧路由调用同一服务函数，避免后台旧 JavaScript 失效。

- [ ] **Step 1: 写出 API 状态、开关和写入授权测试**

```python
def test_start_monitor_persists_enabled_and_audits():
    response = client.post("/api/comment-monitor/start")
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert setting("comment_monitor_enabled") == "true"
    assert audit_action() == "comment_monitor_started"


def test_auto_reply_settings_default_to_disabled():
    payload = client.get("/api/auto-reply/settings").json()
    assert payload["enabled"] is False
    assert payload["hourly_limit"] == 60
    assert "write_enabled" in payload


def test_approve_draft_refuses_when_bilibili_write_is_disabled():
    response = client.post(f"/api/drafts/{draft_id}/approve")
    assert response.status_code == 409
    assert response.json()["detail"] == "B站真实写入未授权"


def test_reject_and_settings_changes_are_audited():
    client.post(f"/api/reply-drafts/{draft_id}/reject")
    client.patch("/api/auto-reply/settings", json=disabled_auto_settings())
    assert audit_actions()[-2:] == ["reply_draft_rejected", "auto_reply_settings_changed"]
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_comment_monitor_api.py tests/test_review_actions.py -v`
Expected: FAIL，新路由不存在且当前批准操作总会创建发送任务。

- [ ] **Step 3: 实现请求模型和设置校验**

```python
class AutoReplySettingsRequest(BaseModel):
    enabled: bool
    user_daily_limit: int = Field(ge=1, le=100)
    account_hourly_limit: int = Field(ge=1, le=500)
    account_daily_limit: int = Field(ge=1, le=5000)
    min_delay_seconds: int = Field(ge=1, le=600)
    max_delay_seconds: int = Field(ge=1, le=1800)

    @model_validator(mode="after")
    def delay_order(self):
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("最大延迟必须大于或等于最小延迟")
        return self
```

开启自动回复时，如果运行模式不是 `limited_auto` 或真实写入未授权，返回 409，不保存半开启状态。

- [ ] **Step 4: 实现监控、立即同步、重生成和审核 API**

`POST /api/comment-monitor/sync` 只排入一次 `run_cycle(force=True)` 本地任务并返回 `202`，避免 HTTP 请求长时间阻塞。重生成只允许 `pending` 或 `generation_failed` 来源事件；批准时先检查 kill switch 和真实写入授权，再创建唯一发布任务。

监控启停、立即同步、草稿生成/重生成、编辑、批准、拒绝、自动回复设置变化和每次平台发送结果都调用 `AuditService.record()`；审计详情只写实体 ID、稳定状态和错误码。

```python
@router.post("/api/comment-monitor/sync", status_code=202)
async def sync_now() -> dict:
    accepted = runtime.request_manual_cycle()
    if not accepted:
        raise HTTPException(409, "同步任务正在运行")
    return {"status": "accepted"}
```

- [ ] **Step 5: 运行 API 测试**

Run: `pytest tests/test_comment_monitor_api.py tests/test_review_actions.py tests/test_admin.py -v`
Expected: PASS；默认关闭状态不会创建真实发送任务。

- [ ] **Step 6: 提交**

```bash
git add src/cyber_catgirl/web/comment_monitor.py src/cyber_catgirl/web/routes.py src/cyber_catgirl/web/actions.py tests/test_comment_monitor_api.py tests/test_review_actions.py tests/test_admin.py
git commit -m "feat: expose comment monitoring controls"
```

---

### Task 10: 建设监控工作台和富上下文审核卡

**Files:**
- Modify: `src/cyber_catgirl/services/dashboard.py`
- Modify: `src/cyber_catgirl/web/view_models.py`
- Modify: `src/cyber_catgirl/web/pages.py`
- Create: `src/cyber_catgirl/web/templates/comment_monitor.html`
- Modify: `src/cyber_catgirl/web/templates/base.html`
- Modify: `src/cyber_catgirl/web/templates/reviews.html`
- Modify: `src/cyber_catgirl/web/templates/settings.html`
- Modify: `src/cyber_catgirl/web/static/app.css`
- Modify: `src/cyber_catgirl/web/static/app.js`
- Create: `src/cyber_catgirl/web/static/comment-monitor.js`
- Create Test: `tests/test_comment_monitor_page.py`
- Modify Test: `tests/test_admin_visual_contract.py`

**Interfaces:**
- Produces: `/comment-monitor` 页面和扩展后的 `ReviewItem`。
- Consumes: 监控状态 API、事件 JSON 和已有设计系统变量。

- [ ] **Step 1: 写出页面契约测试**

```python
def test_monitor_page_shows_status_metrics_and_controls():
    response = client.get("/comment-monitor")
    assert response.status_code == 200
    assert 'data-monitor-state' in response.text
    assert 'data-action="sync-comments"' in response.text
    assert "历史回溯" in response.text


def test_review_card_shows_source_comment_and_priority():
    response = client.get("/reviews")
    assert "这是怎么接入的？" in response.text
    assert "测试视频" in response.text
    assert "优先" in response.text
    assert "B站真实写入未授权" in response.text
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest tests/test_comment_monitor_page.py tests/test_admin_visual_contract.py -v`
Expected: FAIL，页面路由、监控导航和来源上下文不存在。

- [ ] **Step 3: 扩展展示模型和查询**

```python
class ReviewItem(BaseModel):
    id: int
    draft_type: str
    content: str
    risk_level: str
    review_status: str
    priority: str = "normal"
    source_comment: str | None = None
    actor_name: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    thread_context: list[str] = Field(default_factory=list)
    safety_reasons: list[str] = Field(default_factory=list)
    publication_status: str | None = None
    created_at: datetime
```

Dashboard 查询联结 `DraftRecord -> EventRecord -> MonitoredContentRecord`，按 `priority` 降序、评论平台时间降序排列。

- [ ] **Step 4: 实现页面结构和交互**

监控页包含连接状态、最近/下次同步、回溯进度、内容数、新评论数、失败数、立即同步和暂停按钮。审核卡在编辑框上方显示原评论、作者、来源链接和楼层上下文。

```javascript
document.querySelector('[data-action="sync-comments"]')?.addEventListener("click", async () => {
  const response = await fetch("/api/comment-monitor/sync", {method: "POST"});
  const body = await response.json();
  showToast(response.ok ? "同步任务已开始" : body.detail, !response.ok);
});
```

CSS 使用现有 `--sakura`、`--line`、`--muted` 和 `.panel` 视觉系统；在 720px 以下把指标网格改为两列，审核操作按钮允许换行，不引入新的前端框架。

- [ ] **Step 5: 运行页面测试**

Run: `pytest tests/test_comment_monitor_page.py tests/test_admin_visual_contract.py tests/test_review_actions.py -v`
Expected: PASS；既有六个后台页面仍可访问，新页面移动端契约存在。

- [ ] **Step 6: 提交**

```bash
git add src/cyber_catgirl/services/dashboard.py src/cyber_catgirl/web tests/test_comment_monitor_page.py tests/test_admin_visual_contract.py tests/test_review_actions.py
git commit -m "feat: add comment monitoring console"
```

---

### Task 11: 端到端验证、运行文档和默认关闭检查

**Files:**
- Create: `tests/test_comment_monitor_e2e.py`
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: 前十个任务的公开服务和 API。
- Produces: 可重复的模拟端到端验收，以及本地运行与故障处理说明。

- [ ] **Step 1: 写出完整模拟闭环测试**

```python
async def test_discover_monitor_generate_review_without_real_write(tmp_path):
    app, fakes = build_test_app(tmp_path, monitor_enabled=True, write_enabled=False)
    await app.state.monitor_runtime.discover_contents()
    result = await app.state.monitor_runtime.run_cycle()

    assert result.inserted_comments == 2
    assert result.generated_drafts == 2
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(DraftRecord)) == 2
        assert session.scalar(select(func.count()).select_from(PublishJobRecord)) == 0
    assert fakes.bilibili.send_calls == 0


async def test_restart_resumes_cursor_without_duplicate_draft(tmp_path):
    await first_app.state.monitor_runtime.run_cycle()
    await second_app.state.monitor_runtime.run_cycle()
    assert count_events(second_app) == 2
    assert count_drafts(second_app) == 2
```

- [ ] **Step 2: 运行端到端测试并确认真实集成缺口**

Run: `pytest tests/test_comment_monitor_e2e.py -v`
Expected: 第一次运行在尚未正确组装的依赖处 FAIL；修正组装后 PASS。

- [ ] **Step 3: 补全依赖组装和默认关闭断言**

确认 `create_app()` 的生产依赖使用已加密 B站凭证和 DeepSeek 凭证，但应用启动本身不发起模型生成或 B站写操作。只有 `comment_monitor_enabled=true` 才执行读取；即使监控开启，只要写入闸门关闭，发送调用数必须为零。

- [ ] **Step 4: 更新运行与故障文档**

README 与运维文档明确记录：

```text
1. 启动服务并确认 B站、DeepSeek 均显示已连接。
2. 在评论监控页手动开启读取监控。
3. 系统按 60 秒周期分批回溯最近 30 天、最多 500 条评论。
4. 第一代只审核草稿；真实写入和自动回复默认关闭。
5. 出现 429 时按 5/15/60 分钟退避；出现风控或登录失效时暂停写入。
6. 开启真实写入前备份 data/cyber_catgirl.db，并再次确认主账号授权。
```

`.env.example` 增加非敏感默认配置，不放入 Cookie 或 API Key 示例值。

- [ ] **Step 5: 运行完整验证**

Run: `pytest -q`
Expected: 全部测试 PASS。

Run: `ruff check src tests`
Expected: `All checks passed!`

Run: `git diff --check`
Expected: 无输出。

- [ ] **Step 6: 本地人工验收**

Run: `python -m uvicorn cyber_catgirl.main:app --host 127.0.0.1 --port 8765`
Expected: 管理台可访问；评论监控页显示“自动回复关闭”和“真实写入未授权”；立即同步能够读取数据并生成待审核草稿，但不向 B站发送评论。

- [ ] **Step 7: 提交**

```bash
git add tests/test_comment_monitor_e2e.py README.md docs/operations.md .env.example
git commit -m "test: verify Bilibili comment monitoring workflow"
```

---

## Final Verification Gate

- [ ] `pytest -q` 全部通过。
- [ ] `ruff check src tests` 返回 `All checks passed!`。
- [ ] `git diff --check` 无输出。
- [ ] `git status --short` 只包含计划内变更，最终提交后为空。
- [ ] 真实 B站写入调用次数在默认配置下为 0。
- [ ] 历史回溯总数不超过 500，单周期页面读取不超过 3。
- [ ] 重启后事件、草稿和发送任务不重复。
- [ ] 管理台和日志中不存在 Cookie、DeepSeek API Key、密文路径或上游认证头。
- [ ] 用户单独确认真实写入前，不更改 `write_enabled=false`。
