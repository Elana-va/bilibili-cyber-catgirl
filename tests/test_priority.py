import pytest

from cyber_catgirl.services.priority import classify_review_priority


@pytest.mark.parametrize(
    "content",
    [
        "这是怎么接入的？",
        "请问模型是什么",
        "为什么会这样",
        "@听晴sil 在吗",
        "听晴sil能回复一下吗",
    ],
)
def test_questions_and_mentions_are_priority(content):
    assert classify_review_priority(content, "听晴sil") == "priority"


def test_plain_reaction_is_normal():
    assert classify_review_priority("好可爱喵", "听晴sil") == "normal"


def test_empty_account_name_does_not_mark_every_comment_priority():
    assert classify_review_priority("普通互动", "") == "normal"
