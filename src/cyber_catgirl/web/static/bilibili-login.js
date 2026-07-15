(() => {
  const root = document.querySelector("[data-bilibili-root]");
  if (!root) return;

  const dialog = document.querySelector("#bilibili-login-dialog");
  const connectButton = root.querySelector("[data-bilibili-connect]");
  const disconnectButton = root.querySelector("[data-bilibili-disconnect]");
  const emptyState = root.querySelector("[data-bilibili-empty]");
  const accountState = root.querySelector("[data-bilibili-account]");
  const statusBadge = root.querySelector("[data-bilibili-status]");
  const accountName = root.querySelector("[data-bilibili-name]");
  const accountUid = root.querySelector("[data-bilibili-uid]");
  const avatar = root.querySelector("[data-bilibili-avatar]");
  const avatarFallback = root.querySelector("[data-bilibili-avatar-fallback]");
  const qrImage = dialog.querySelector("[data-bilibili-qr]");
  const qrPlaceholder = dialog.querySelector("[data-bilibili-qr-placeholder]");
  const phaseText = dialog.querySelector("[data-bilibili-phase]");
  const countdown = dialog.querySelector("[data-bilibili-countdown]");
  const retryButton = dialog.querySelector("[data-bilibili-retry]");
  const errorMessages = {
    secure_storage_unavailable: "当前系统无法使用 Windows 安全存储。",
    platform_unavailable: "B站暂时无法连接，请稍后重试。",
    credential_persistence_failed: "登录成功，但本机安全保存失败。",
    login_session_not_found: "二维码已经失效，请重新生成。",
    environment_credential_managed: "该连接由启动环境管理，请停止服务后移除环境变量。",
    credential_delete_failed: "本机凭证删除失败，请保持人工模式并重试。",
  };
  let pollTimer = null;
  let expiresAt = 0;

  async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = typeof payload.detail === "string" ? payload.detail : "platform_unavailable";
      const error = new Error(errorMessages[code] || "操作失败，请重试。");
      error.code = code;
      throw error;
    }
    return payload;
  }

  function setConnection(view) {
    const connected = Boolean(view.connected && view.account);
    emptyState.hidden = connected;
    accountState.hidden = !connected;
    statusBadge.textContent = connected ? "已连接" : "未连接";
    statusBadge.className = `state-badge state-${connected ? "active" : "disabled"}`;
    if (!connected) return;
    accountName.textContent = view.account.name;
    accountUid.textContent = `UID ${view.account.uid}`;
    if (view.account.avatar_url) {
      avatar.src = view.account.avatar_url;
      avatar.alt = `${view.account.name} 的头像`;
      avatar.hidden = false;
      avatarFallback.hidden = true;
    } else {
      avatar.hidden = true;
      avatarFallback.hidden = false;
    }
  }

  async function refreshConnection() {
    try {
      const response = await fetch("/api/bilibili/connection");
      setConnection(await readJson(response));
    } catch (error) {
      setConnection({ connected: false });
      showToast(error.message, true);
    }
  }

  function clearPolling() {
    if (pollTimer !== null) window.clearTimeout(pollTimer);
    pollTimer = null;
  }

  function renderPhase(phase) {
    const labels = {
      waiting: "等待手机扫码",
      scanned: "已扫码，请在手机端确认",
      connected: "连接成功",
      expired: "二维码已过期",
      failed: "连接失败",
    };
    phaseText.textContent = labels[phase] || "正在连接";
    const remaining = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
    countdown.textContent = phase === "connected" ? "身份验证中" : `有效期 ${remaining} 秒`;
    retryButton.hidden = !["expired", "failed"].includes(phase);
  }

  function schedulePoll(sessionId) {
    clearPolling();
    pollTimer = window.setTimeout(() => pollLogin(sessionId), 2000);
  }

  async function pollLogin(sessionId) {
    try {
      const response = await fetch(`/api/bilibili/login/qr/${encodeURIComponent(sessionId)}`);
      const state = await readJson(response);
      renderPhase(state.phase);
      if (["waiting", "scanned"].includes(state.phase)) {
        schedulePoll(sessionId);
      } else if (state.phase === "connected") {
        await refreshConnection();
        showToast("B站账号已安全连接");
        window.setTimeout(() => dialog.close(), 500);
      }
    } catch (error) {
      clearPolling();
      renderPhase("failed");
      showToast(error.message, true);
    }
  }

  async function startLogin() {
    clearPolling();
    retryButton.hidden = true;
    qrImage.hidden = true;
    qrPlaceholder.hidden = false;
    qrPlaceholder.textContent = "正在生成安全二维码…";
    phaseText.textContent = "准备连接";
    countdown.textContent = "有效期 180 秒";
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch("/api/bilibili/login/qr", { method: "POST" });
      const session = await readJson(response);
      qrImage.src = session.qr_data_url;
      qrImage.hidden = false;
      qrPlaceholder.hidden = true;
      expiresAt = Date.now() + session.expires_in * 1000;
      renderPhase(session.phase);
      schedulePoll(session.session_id);
    } catch (error) {
      qrPlaceholder.textContent = "二维码生成失败";
      renderPhase("failed");
      showToast(error.message, true);
    }
  }

  function disconnect() {
    confirmAction("断开后将删除这台电脑保存的 B站会话。确认继续吗？", async () => {
      try {
        const response = await fetch("/api/bilibili/disconnect", { method: "POST" });
        await readJson(response);
        setConnection({ connected: false });
        showToast("B站账号已断开");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  }

  connectButton.addEventListener("click", startLogin);
  retryButton.addEventListener("click", startLogin);
  disconnectButton.addEventListener("click", disconnect);
  dialog.addEventListener("close", clearPolling);
  refreshConnection();
})();
