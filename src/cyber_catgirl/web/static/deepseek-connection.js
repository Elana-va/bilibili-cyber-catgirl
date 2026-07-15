(() => {
  const root = document.querySelector("[data-deepseek-root]");
  if (!root) return;

  const form = root.querySelector("[data-deepseek-form]");
  const keyInput = root.querySelector("[data-deepseek-key]");
  const modelInput = root.querySelector("[data-deepseek-model]");
  const statusBadge = root.querySelector("[data-deepseek-status]");
  const connectedPanel = root.querySelector("[data-deepseek-connected]");
  const modelText = root.querySelector("[data-deepseek-current-model]");
  const verifiedAt = root.querySelector("[data-deepseek-verified-at]");
  const verifyButton = root.querySelector("[data-deepseek-verify]");
  const disconnectButton = root.querySelector("[data-deepseek-disconnect]");
  const errors = {
    invalid_api_key: "API Key 无效，请检查后重试。",
    insufficient_balance: "DeepSeek 账户余额不足。",
    rate_limited: "验证过于频繁，请稍后重试。",
    selected_model_unavailable: "所选模型当前不可用。",
    environment_credential_managed: "该密钥由启动环境管理，请停止服务后移除环境变量。",
    secure_storage_unavailable: "当前系统无法使用 Windows 安全存储。",
    credential_unreadable: "本机保存的 DeepSeek 凭证无法解密。",
    deepseek_unavailable: "当前无法连接 DeepSeek，请稍后重试。",
  };

  async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = typeof payload.detail === "string" ? payload.detail : "deepseek_unavailable";
      throw new Error(errors[code] || "操作失败，请重试。");
    }
    return payload;
  }

  function render(view) {
    const configured = Boolean(view.configured);
    form.hidden = configured && view.source === "local_encrypted";
    connectedPanel.hidden = !configured;
    statusBadge.textContent = configured ? (view.verified ? "已连接" : "待验证") : "未连接";
    statusBadge.className = `state-badge state-${view.verified ? "active" : "disabled"}`;
    modelText.textContent = view.model || "—";
    verifiedAt.textContent = view.verified_at
      ? new Date(view.verified_at).toLocaleString("zh-CN")
      : "尚未验证";
    disconnectButton.hidden = view.source === "environment";
  }

  async function refresh() {
    try {
      render(await readJson(await fetch("/api/deepseek/connection")));
    } catch (error) {
      showToast(error.message, true);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const apiKey = keyInput.value;
    try {
      const response = await fetch("/api/deepseek/connection", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({api_key: apiKey, model: modelInput.value}),
      });
      render(await readJson(response));
      showToast("DeepSeek 已安全连接");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      keyInput.value = "";
    }
  });

  verifyButton.addEventListener("click", async () => {
    try {
      render(await readJson(await fetch("/api/deepseek/verify", {method: "POST"})));
      showToast("DeepSeek 连接验证通过");
    } catch (error) {
      await refresh();
      showToast(error.message, true);
    }
  });

  disconnectButton.addEventListener("click", () => {
    confirmAction("断开后将删除这台电脑保存的 DeepSeek API Key。确认继续吗？", async () => {
      try {
        render(await readJson(await fetch("/api/deepseek/disconnect", {method: "POST"})));
        showToast("DeepSeek 已断开");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });

  refresh();
})();
