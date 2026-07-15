QUESTION_MARKERS = (
    "?",
    "？",
    "请问",
    "怎么",
    "为什么",
    "能否",
    "可以吗",
    "是什么",
)


def classify_review_priority(content: str, account_name: str) -> str:
    compact = content.casefold().replace(" ", "")
    account = account_name.casefold().replace(" ", "")
    if any(marker in compact for marker in QUESTION_MARKERS):
        return "priority"
    if account and (f"@{account}" in compact or account in compact):
        return "priority"
    return "normal"
