const dialog = document.querySelector("#confirm-dialog");
const dialogMessage = document.querySelector("#confirm-message");
const dialogSubmit = document.querySelector("#confirm-submit");
const toastRegion = document.querySelector("[data-toast-region]");

function showToast(message, isError = false) {
  const toast = document.createElement("div");
  toast.className = `toast${isError ? " is-error" : ""}`;
  toast.textContent = message;
  toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 4500);
}

async function requestAction(url, { body, success = "操作成功" } = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    showToast(payload.detail || "操作失败，请检查系统状态", true);
    return false;
  }
  showToast(success);
  window.setTimeout(() => window.location.reload(), 350);
  return true;
}

function confirmAction(message, action) {
  dialogMessage.textContent = message;
  dialog.showModal();
  dialogSubmit.onclick = async (event) => {
    event.preventDefault();
    dialog.close();
    await action();
  };
}

document.querySelectorAll('[data-action="kill-switch"]').forEach((button) => {
  button.addEventListener("click", () => {
    const enabled = button.dataset.enabled === "true";
    const message = enabled
      ? "开启后，所有待发布任务会被取消，系统停止外部写入。"
      : "恢复后仍保持当前运行模式，请确认异常已经排除。";
    confirmAction(message, () =>
      requestAction("/api/system/kill-switch", {
        body: { enabled },
        success: enabled ? "紧急停止已开启" : "紧急停止已关闭",
      }),
    );
  });
});

document.querySelectorAll("[data-approve]").forEach((button) => {
  button.addEventListener("click", () => confirmAction("批准后会创建一条发布任务。", () => requestAction(`/api/drafts/${button.dataset.approve}/approve`, { success: "草稿已批准" }))));
});

document.querySelectorAll("[data-reject]").forEach((button) => {
  button.addEventListener("click", () => confirmAction("拒绝后不会创建发布任务。", () => requestAction(`/api/drafts/${button.dataset.reject}/reject`, { success: "草稿已拒绝" }))));
});

document.querySelectorAll("[data-edit-approve]").forEach((button) => {
  button.addEventListener("click", () => {
    const draftId = button.dataset.editApprove;
    const editor = document.querySelector(`[data-draft-content="${draftId}"]`);
    confirmAction("确认内容无误后，将创建一条发布任务。", () =>
      requestAction(`/api/drafts/${draftId}/edit-and-approve`, {
        body: { content: editor.value },
        success: "草稿已编辑并批准",
      }),
    );
  });
});
