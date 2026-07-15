async function monitorRequest(url, method = "POST", body = null) {
  const response = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    showToast(payload.detail || "操作未完成，请检查监控状态。", true);
    return null;
  }
  return payload;
}

document.querySelector('[data-action="sync-comments"]')?.addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  const payload = await monitorRequest("/api/comment-monitor/sync");
  if (payload) showToast("同步任务已进入本地队列");
  window.setTimeout(() => { event.currentTarget.disabled = false; }, 1200);
});

document.querySelector('[data-action="start-monitor"]')?.addEventListener("click", async () => {
  if (await monitorRequest("/api/comment-monitor/start")) {
    showToast("评论监控已开启");
    window.setTimeout(() => window.location.reload(), 300);
  }
});

document.querySelector('[data-action="stop-monitor"]')?.addEventListener("click", () => {
  confirmAction("暂停后将保留已导入评论和同步游标，重新开启时会从原位置继续。", async () => {
    if (await monitorRequest("/api/comment-monitor/stop")) {
      showToast("评论监控已暂停");
      window.setTimeout(() => window.location.reload(), 300);
    }
  });
});

document.querySelectorAll("[data-regenerate]").forEach((button) => {
  button.addEventListener("click", () => {
    confirmAction("重新生成会替换当前回复草稿，不会直接发送。", async () => {
      const payload = await monitorRequest(`/api/reply-drafts/${button.dataset.regenerate}/regenerate`);
      if (payload) {
        showToast("回复草稿已重新生成");
        window.setTimeout(() => window.location.reload(), 300);
      }
    });
  });
});

async function refreshMonitorStatus() {
  if (!document.querySelector("[data-monitor-state]")) return;
  const response = await fetch("/api/comment-monitor/status");
  if (!response.ok) return;
  const status = await response.json();
  document.querySelectorAll("[data-monitor-value]").forEach((element) => {
    const key = element.dataset.monitorValue;
    if (Object.hasOwn(status, key)) element.textContent = status[key];
  });
  const label = document.querySelector("[data-monitor-label]");
  if (label) label.textContent = status.enabled ? "监控中" : "已暂停";
  const progress = document.querySelector("[data-backfill-progress]");
  if (progress) progress.value = status.backfill_imported;
}

if (document.querySelector("[data-monitor-state]")) {
  window.setInterval(refreshMonitorStatus, 15000);
}

document.querySelector("[data-auto-reply-form]")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  const payload = {
    enabled: form.elements.enabled.checked,
    user_daily_limit: Number(data.user_daily_limit),
    account_hourly_limit: Number(data.account_hourly_limit),
    account_daily_limit: Number(data.account_daily_limit),
    min_delay_seconds: Number(data.min_delay_seconds),
    max_delay_seconds: Number(data.max_delay_seconds),
  };
  if (await monitorRequest("/api/auto-reply/settings", "PATCH", payload)) {
    showToast("自动回复设置已保存");
    window.setTimeout(() => window.location.reload(), 300);
  }
});
