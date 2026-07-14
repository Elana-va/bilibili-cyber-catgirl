async function act(path) {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    const body = await response.json();
    window.alert(body.detail || "操作失败");
    return;
  }
  window.location.reload();
}

document.querySelectorAll("[data-approve]").forEach((button) => {
  button.addEventListener("click", () => {
    if (window.confirm("确认批准并创建发布任务？")) {
      act(`/api/drafts/${button.dataset.approve}/approve`);
    }
  });
});

document.querySelectorAll("[data-reject]").forEach((button) => {
  button.addEventListener("click", () => {
    if (window.confirm("确认拒绝此草稿？")) {
      act(`/api/drafts/${button.dataset.reject}/reject`);
    }
  });
});
