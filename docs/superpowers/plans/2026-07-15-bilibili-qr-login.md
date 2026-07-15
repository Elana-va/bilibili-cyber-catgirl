# B站本机扫码连接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有管理台中增加 B 站主账号本机扫码登录、Windows DPAPI 加密持久化、账号只读验证和安全断开功能。

**Architecture:** 将敏感凭证存储、SDK 扫码状态机、账号只读验证和 Web API 分成四个独立单元。FastAPI 只返回二维码和公开账号身份，凭证明文只在后端内存中短暂存在；扫码成功不会改变 `manual_only`、紧急停止或启动任何写入执行器。

**Tech Stack:** Python 3.11/3.12、FastAPI、Jinja2、原生 JavaScript、`bilibili-api-python 17.4.x`、Windows DPAPI（标准库 `ctypes`）、pytest、Ruff、Node `--check`。

## Global Constraints

- 不接收账号、密码、短信验证码或手工 Cookie。
- 凭证不得进入 HTML、JSON、SQLite、模型上下文、日志、Git 或测试快照。
- 密文固定保存到 `data/secrets/bilibili-credential.bin`，非 Windows 不得降级成明文。
- 二维码会话有效期固定为 180 秒，浏览器每 2 秒轮询一次。
- 同一时刻只允许一个进行中的扫码会话，新会话使旧会话失效。
- 扫码成功不得修改 `manual_only`、紧急停止或白名单。
- 本迭代不新增常驻轮询和发布执行器，不执行真实回复或动态发布。
- 真实账号验收只执行身份与评论只读探针。

## File Structure

- `src/cyber_catgirl/security/credential_store.py`：凭证类型、Windows DPAPI 和原子密文存储。
- `src/cyber_catgirl/connectors/bilibili_login.py`：SDK 二维码适配器与单会话登录状态机。
- `src/cyber_catgirl/services/bilibili_account.py`：凭证来源、账号身份只读探针和公开视图。
- `src/cyber_catgirl/web/bilibili_auth.py`：本机认证 API。
- `src/cyber_catgirl/web/static/bilibili-login.js`：二维码创建、轮询、状态渲染和断开。
- `tests/test_credential_store.py`、`tests/test_bilibili_login.py`、`tests/test_bilibili_account.py`、`tests/test_bilibili_auth_api.py`：对应的契约测试。

---

### Task 1: Windows DPAPI 凭证存储

**Files:**
- Create: `src/cyber_catgirl/security/__init__.py`
- Create: `src/cyber_catgirl/security/credential_store.py`
- Modify: `.gitignore`
- Test: `tests/test_credential_store.py`

**Interfaces:**
- Produces: `BilibiliCredentialData(sessdata, bili_jct, dedeuserid=None, ac_time_value=None, buvid3=None)`。
- Produces: `DataProtector.protect(bytes) -> bytes` 和 `DataProtector.unprotect(bytes) -> bytes`。
- Produces: `CredentialStore(path, protector)` with `configured()`, `save(data)`, `load()`, `delete()`。
- Produces: `DpapiProtector`、`SecureStorageUnavailable`、`CredentialUnreadable`。

- [ ] **Step 1: 写入失败测试**

```python
class PrefixProtector:
    def protect(self, value: bytes) -> bytes:
        return b"encrypted:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"encrypted:"):
            raise ValueError("invalid ciphertext")
        return value.removeprefix(b"encrypted:")[::-1]


def test_store_round_trip_never_writes_plaintext(tmp_path):
    path = tmp_path / "secrets" / "bilibili-credential.bin"
    store = CredentialStore(path, PrefixProtector())
    secret = BilibiliCredentialData(sessdata="sess-secret", bili_jct="csrf-secret")
    store.save(secret)
    assert store.configured() is True
    assert b"sess-secret" not in path.read_bytes()
    assert store.load() == secret


def test_store_overwrites_atomically_and_deletes(tmp_path):
    path = tmp_path / "bilibili-credential.bin"
    store = CredentialStore(path, PrefixProtector())
    store.save(BilibiliCredentialData("old", "old-csrf"))
    store.save(BilibiliCredentialData("new", "new-csrf"))
    assert store.load().sessdata == "new"
    assert not path.with_suffix(".tmp").exists()
    store.delete()
    assert store.configured() is False


def test_store_maps_corrupt_ciphertext_to_domain_error(tmp_path):
    path = tmp_path / "bilibili-credential.bin"
    path.write_bytes(b"not-encrypted")
    with pytest.raises(CredentialUnreadable):
        CredentialStore(path, PrefixProtector()).load()
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_credential_store.py -v`  
Expected: FAIL with `ModuleNotFoundError: cyber_catgirl.security`。

- [ ] **Step 3: 实现最小存储**

```python
@dataclass(frozen=True)
class BilibiliCredentialData:
    sessdata: str
    bili_jct: str
    dedeuserid: str | None = None
    ac_time_value: str | None = None
    buvid3: str | None = None


class CredentialStore:
    def __init__(self, path: Path, protector: DataProtector):
        self.path = path
        self.protector = protector

    def configured(self) -> bool:
        return self.path.is_file()

    def save(self, data: BilibiliCredentialData) -> None:
        plaintext = json.dumps(asdict(data), ensure_ascii=False).encode("utf-8")
        ciphertext = self.protector.protect(plaintext)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(ciphertext)
        temporary.replace(self.path)

    def load(self) -> BilibiliCredentialData | None:
        if not self.configured():
            return None
        try:
            payload = json.loads(self.protector.unprotect(self.path.read_bytes()))
            return BilibiliCredentialData(**payload)
        except Exception as exc:
            raise CredentialUnreadable("B站凭证无法解密") from exc

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
```

`DpapiProtector` 用 `ctypes.windll.crypt32.CryptProtectData` 和 `CryptUnprotectData`；通过 `kernel32.LocalFree` 释放输出缓冲区。`sys.platform != "win32"` 时抛出 `SecureStorageUnavailable`，不写明文。

- [ ] **Step 4: 忽略密文并验证绿灯**

在 `.gitignore` 增加 `data/secrets/`。

Run: `python -m pytest tests/test_credential_store.py -v`  
Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add .gitignore src/cyber_catgirl/security tests/test_credential_store.py
git commit -m "feat: protect bilibili credentials with dpapi"
```

---

### Task 2: 二维码 SDK 适配器与登录状态机

**Files:**
- Create: `src/cyber_catgirl/connectors/bilibili_login.py`
- Test: `tests/test_bilibili_login.py`

**Interfaces:**
- Consumes: `CredentialStore.save(BilibiliCredentialData)`。
- Produces: `LoginPhase`、`LoginSessionView`、`BilibiliLoginManager.create_session()`、`check_session()`、`cancel_all()`。
- Produces: `SdkQrLogin` protocol and `BilibiliQrSdkAdapter`。

- [ ] **Step 1: 写入状态机失败测试**

```python
@pytest.mark.asyncio
async def test_manager_returns_qr_once_and_saves_on_success():
    sdk = FakeQrSdk([LoginPhase.WAITING, LoginPhase.SCANNED, LoginPhase.CONNECTED])
    store = MemoryCredentialStore()
    manager = BilibiliLoginManager(store, lambda: sdk, clock=FrozenClock(1000))
    created = await manager.create_session()
    waiting = await manager.check_session(created.session_id)
    scanned = await manager.check_session(created.session_id)
    connected = await manager.check_session(created.session_id)
    assert created.qr_data_url.startswith("data:image/png;base64,")
    assert waiting.qr_data_url is None
    assert scanned.phase is LoginPhase.SCANNED
    assert connected.phase is LoginPhase.CONNECTED
    assert store.saved.sessdata == "sess-secret"


@pytest.mark.asyncio
async def test_new_session_invalidates_old_session():
    manager = BilibiliLoginManager(MemoryCredentialStore(), FakeSdkFactory())
    old = await manager.create_session()
    new = await manager.create_session()
    with pytest.raises(LoginSessionNotFound):
        await manager.check_session(old.session_id)
    assert new.session_id != old.session_id


@pytest.mark.asyncio
async def test_expired_session_is_removed_without_saving():
    clock = FrozenClock(1000)
    manager = BilibiliLoginManager(MemoryCredentialStore(), FakeSdkFactory(), clock=clock)
    created = await manager.create_session()
    clock.value = 1181
    assert (await manager.check_session(created.session_id)).phase is LoginPhase.EXPIRED
    with pytest.raises(LoginSessionNotFound):
        await manager.check_session(created.session_id)
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_bilibili_login.py -v`  
Expected: FAIL because `bilibili_login` symbols do not exist。

- [ ] **Step 3: 实现状态机**

```python
class LoginPhase(StrEnum):
    WAITING = "waiting"
    SCANNED = "scanned"
    CONNECTED = "connected"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class LoginSessionView:
    session_id: str
    phase: LoginPhase
    qr_data_url: str | None = None
    expires_in: int = 0
```

内部保存单个 `_Session(session_id, sdk, created_at)`；ID 使用 `secrets.token_urlsafe(24)`。`create_session()` 返回二维码，后续状态响应不返回二维码。180 秒超时即删除。连接完成时先保存凭证再返回 connected；保存失败抛 `LoginPersistenceFailed`。

- [ ] **Step 4: 实现 SDK 状态映射**

```python
async def generate(self) -> bytes:
    await self.login.generate_qrcode()
    return self.login.get_qrcode_picture().content

async def check(self) -> LoginPhase:
    event = await self.login.check_state()
    return {
        QrCodeLoginEvents.SCAN: LoginPhase.WAITING,
        QrCodeLoginEvents.CONF: LoginPhase.SCANNED,
        QrCodeLoginEvents.DONE: LoginPhase.CONNECTED,
        QrCodeLoginEvents.TIMEOUT: LoginPhase.EXPIRED,
    }[event]
```

`credential_data()` 仅复制五个允许字段，禁止记录 `Credential` 的 repr。

- [ ] **Step 5: 验证绿灯并提交**

Run: `python -m pytest tests/test_bilibili_login.py -v`  
Expected: PASS。

```powershell
git add src/cyber_catgirl/connectors/bilibili_login.py tests/test_bilibili_login.py
git commit -m "feat: manage bilibili qr login sessions"
```

---

### Task 3: 账号只读验证服务

**Files:**
- Create: `src/cyber_catgirl/services/bilibili_account.py`
- Test: `tests/test_bilibili_account.py`

**Interfaces:**
- Consumes: `CredentialStore.load()`、`configured()`、`delete()`。
- Produces: `AccountIdentity`、`ConnectionView`、`BilibiliAccountService.connection_view()`、`configured()`、`disconnect()`。
- Produces: `load_credential_data(store, environ)`，加密存储优先，环境变量只读后备。

- [ ] **Step 1: 写入服务失败测试**

```python
@pytest.mark.asyncio
async def test_connection_view_exposes_only_public_identity():
    secret = BilibiliCredentialData("sess-secret", "csrf-secret")
    service = BilibiliAccountService(FakeStore(secret), FakeIdentityProbe())
    view = await service.connection_view()
    assert view == ConnectionView(True, "verified", AccountIdentity("123", "测试账号", None))
    assert "sess-secret" not in repr(view)


def test_environment_is_used_only_when_store_is_empty():
    data = load_credential_data(
        FakeStore(None),
        {"BILI_SESSDATA": "env-sess", "BILI_JCT": "env-csrf", "BILI_BUVID3": "env-buvid"},
    )
    assert data == BilibiliCredentialData("env-sess", "env-csrf", buvid3="env-buvid")


@pytest.mark.asyncio
async def test_probe_failure_returns_fixed_public_state():
    service = BilibiliAccountService(FakeStore(SECRET), FailingIdentityProbe("cookie=secret"))
    view = await service.connection_view()
    assert view.connected is False
    assert view.verification == "verification_failed"
    assert "secret" not in repr(view)
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_bilibili_account.py -v`  
Expected: FAIL with missing `BilibiliAccountService`。

- [ ] **Step 3: 实现公开视图和只读探针**

```python
@dataclass(frozen=True)
class AccountIdentity:
    uid: str
    name: str
    avatar_url: str | None


@dataclass(frozen=True)
class ConnectionView:
    connected: bool
    verification: str
    account: AccountIdentity | None = None
```

真实探针调用 `bilibili_api.user.get_self_info(credential)`，只提取 `mid`、`uname`、`face`。SDK 异常统一变成 `verification_failed`，不传播异常文本。`disconnect()` 删除密文；失败抛 `CredentialDeleteFailed`。

- [ ] **Step 4: 验证绿灯并提交**

Run: `python -m pytest tests/test_bilibili_account.py -v`  
Expected: PASS。

```powershell
git add src/cyber_catgirl/services/bilibili_account.py tests/test_bilibili_account.py
git commit -m "feat: verify connected bilibili account safely"
```

---

### Task 4: 本机认证 API 与应用装配

**Files:**
- Create: `src/cyber_catgirl/web/bilibili_auth.py`
- Modify: `src/cyber_catgirl/web/routes.py`
- Modify: `src/cyber_catgirl/web/pages.py`
- Modify: `src/cyber_catgirl/main.py`
- Test: `tests/test_bilibili_auth_api.py`

**Interfaces:**
- Consumes: Tasks 2–3 的 manager/service。
- Produces: `build_bilibili_auth_router(login_manager, account_service)`。
- Changes: `RuntimeState(settings, login_manager, account_service)`。
- Changes: `create_app(..., credential_store=None, login_manager=None, account_service=None)` for tests。

- [ ] **Step 1: 写入 API 失败测试**

```python
def test_qr_creation_and_status_never_return_credentials(client):
    created = client.post("/api/bilibili/login/qr")
    assert created.status_code == 201
    payload = created.json()
    assert payload["phase"] == "waiting"
    assert payload["qr_data_url"].startswith("data:image/png;base64,")
    assert "sess-secret" not in created.text
    status = client.get(f"/api/bilibili/login/qr/{payload['session_id']}")
    assert status.status_code == 200
    assert status.json()["qr_data_url"] is None
    assert "sess-secret" not in status.text


def test_connection_response_contains_only_public_identity(client):
    assert client.get("/api/bilibili/connection").json() == {
        "connected": True,
        "verification": "verified",
        "account": {"uid": "123", "name": "测试账号", "avatar_url": None},
    }


def test_login_does_not_change_runtime_safety_state(client):
    before = client.get("/api/health").json()
    client.post("/api/bilibili/login/qr")
    assert client.get("/api/health").json() == before


def test_disconnect_deletes_local_credential(client, fake_store):
    assert client.post("/api/bilibili/disconnect").json() == {"connected": False}
    assert fake_store.deleted is True
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_bilibili_auth_api.py -v`  
Expected: FAIL with HTTP 404 for `/api/bilibili/*`。

- [ ] **Step 3: 实现接口与固定错误码**

```python
@router.post("/api/bilibili/login/qr", status_code=201)
async def create_qr_login() -> dict:
    return asdict(await login_manager.create_session())

@router.get("/api/bilibili/login/qr/{session_id}")
async def check_qr_login(session_id: str) -> dict:
    return asdict(await login_manager.check_session(session_id))

@router.get("/api/bilibili/connection")
async def connection() -> dict:
    return asdict(await account_service.connection_view())

@router.post("/api/bilibili/disconnect")
async def disconnect() -> dict:
    login_manager.cancel_all()
    account_service.disconnect()
    return {"connected": False}
```

映射：`LoginSessionNotFound -> 404 login_session_not_found`、`SecureStorageUnavailable -> 501 secure_storage_unavailable`、`LoginPersistenceFailed -> 503 credential_persistence_failed`、未分类 SDK 异常 -> `503 platform_unavailable`。不得返回原始异常文本。

- [ ] **Step 4: 装配生产依赖**

```python
store = CredentialStore(Path("data/secrets/bilibili-credential.bin"), DpapiProtector())
login_manager = BilibiliLoginManager(store, BilibiliQrSdkAdapter)
account_service = BilibiliAccountService(store, BilibiliIdentityProbe())
```

`/settings` 只调用 `state.account_service.configured()`，不直接读取凭证值。测试注入 fake manager/service，避免 DPAPI 和网络。

- [ ] **Step 5: 回归并提交**

Run: `python -m pytest tests/test_bilibili_auth_api.py tests/test_admin_pages.py tests/test_logs_settings_admin.py -v`  
Expected: PASS。

```powershell
git add src/cyber_catgirl/main.py src/cyber_catgirl/web tests/test_bilibili_auth_api.py
git commit -m "feat: expose safe local bilibili auth api"
```

---

### Task 5: 设置页扫码交互

**Files:**
- Modify: `src/cyber_catgirl/web/templates/base.html`
- Modify: `src/cyber_catgirl/web/templates/settings.html`
- Modify: `src/cyber_catgirl/web/static/app.css`
- Create: `src/cyber_catgirl/web/static/bilibili-login.js`
- Modify: `tests/test_admin_visual_contract.py`
- Modify: `tests/test_bilibili_auth_api.py`

**Interfaces:**
- Consumes: Task 4 的四个接口。
- Produces: `[data-bilibili-connect]`、`#bilibili-login-dialog`、`[data-bilibili-account]`、`[data-bilibili-disconnect]`。

- [ ] **Step 1: 写入页面与脚本失败测试**

```python
def test_settings_contains_accessible_bilibili_login_dialog(client):
    html = client.get("/settings").text
    assert "data-bilibili-connect" in html
    assert 'id="bilibili-login-dialog"' in html
    assert 'aria-labelledby="bilibili-login-title"' in html
    assert "/static/bilibili-login.js" in html


def test_javascript_files_have_valid_syntax():
    for script in ["app.js", "bilibili-login.js"]:
        result = subprocess.run([NODE, "--check", STATIC / script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_admin_visual_contract.py tests/test_bilibili_auth_api.py -v`  
Expected: FAIL because dialog and script do not exist。

- [ ] **Step 3: 实现扫码对话框与连接卡片**

对话框包含二维码 `<img alt="B站登录二维码">`、倒计时、状态、取消和重新生成按钮。连接后只显示头像、昵称、UID、“只读验证通过”和断开按钮。不显示 Cookie 字段、长度或摘要。`base.html` 加载：

```html
<script src="{{ url_for('static', path='/bilibili-login.js') }}" defer></script>
```

- [ ] **Step 4: 实现 2 秒轮询和断开**

```javascript
const POLL_INTERVAL_MS = 2000;

async function startBilibiliLogin() {
  const response = await fetch("/api/bilibili/login/qr", { method: "POST" });
  const session = await readJson(response);
  renderQr(session.qr_data_url, session.expires_in);
  schedulePoll(session.session_id);
}

async function pollBilibiliLogin(sessionId) {
  const response = await fetch(`/api/bilibili/login/qr/${encodeURIComponent(sessionId)}`);
  const state = await readJson(response);
  renderPhase(state.phase);
  if (["waiting", "scanned"].includes(state.phase)) schedulePoll(sessionId);
  if (state.phase === "connected") await refreshConnection();
}
```

关闭对话框清除 `setTimeout`。断开使用现有确认对话框。未知服务端文本不得直接展示，只按固定错误码映射中文提示。

- [ ] **Step 5: 响应式样式与绿灯**

二维码桌面 240×240，移动最大 `min(240px, 70vw)`；对话框无横向滚动；账号头像 40×40 圆形；断开按钮使用危险色描边。

Run: `python -m pytest tests/test_admin_visual_contract.py tests/test_bilibili_auth_api.py -v`  
Expected: PASS。

Run: `node --check src/cyber_catgirl/web/static/app.js` and `node --check src/cyber_catgirl/web/static/bilibili-login.js`  
Expected: exit 0 with no syntax errors。

- [ ] **Step 6: 提交**

```powershell
git add src/cyber_catgirl/web/templates src/cyber_catgirl/web/static tests
git commit -m "feat: add bilibili qr login experience"
```

---

### Task 6: 文档、全量验证与真实只读验收

**Files:**
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `docs/connector-research.md`
- Test: all tests

**Interfaces:**
- Consumes: Tasks 1–5 完整流程。
- Produces: 操作手册、凭证轮换与断开步骤、只读验收证据。

- [ ] **Step 1: 更新操作文档**

文档写明：打开 `/settings`、扫码确认、核对昵称/UID、连接不会启动自动写入、断开会删除密文、怀疑泄露时同时在 B 站安全中心撤销会话。

- [ ] **Step 2: 完整自动化验证**

```powershell
python -m pytest -q
python -m ruff check src tests
node --check src/cyber_catgirl/web/static/app.js
node --check src/cyber_catgirl/web/static/bilibili-login.js
git diff --check
```

Expected: all tests pass; Ruff clean; JavaScript syntax clean; no whitespace errors。

- [ ] **Step 3: 凭证泄露扫描**

```powershell
rg -n --hidden --glob '!.git/**' --glob '!data/secrets/**' --glob '!artifacts/**' '(SESSDATA|bili_jct|BILI_JCT)=[^\s]+' .
```

Expected: no populated assignments。

- [ ] **Step 4: 浏览器模拟验收**

用 fake SDK 服务验证桌面 1440×900、移动 390×844 的生成二维码、已扫描、已连接、失败、断开五种状态；无横向溢出和控制台错误。

- [ ] **Step 5: 用户本机扫码和真实只读验收**

只执行生成二维码、手机确认、读取昵称/UID、重启服务后恢复身份、现有 `connector_probe --read-only`。不得输出二维码、响应体或 `data/secrets` 文件，不执行回复或动态发布。

- [ ] **Step 6: 提交文档并最终复验**

```powershell
git add README.md docs
git commit -m "docs: document secure bilibili account connection"
```

再次运行 Step 2，并确认 `git status --short` 为空。

