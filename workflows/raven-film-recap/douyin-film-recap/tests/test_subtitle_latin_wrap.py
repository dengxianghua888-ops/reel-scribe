import re

import pytest

from douyin_film_recap.subtitles import _split_text


@pytest.mark.parametrize(
    "text",
    [
        "Why don't you just admit that you're freaked out by my robot hand?",
        "I'm not freaked out by- it's...",
        "...alright! Fine!",
        "I'm freaked out! I have nightmares that I'm being chased...",
        "汤姆说 don't stop。不要停。",
        "Café déjà vu is not proof.",
        "friendship. Ends.",
    ],
)
@pytest.mark.parametrize("limit", [10, 16, 24])
def test_fitting_latin_tokens_never_split(text, limit):
    lines = _split_text(text, limit)
    assert all(len(x) <= limit for x in lines)
    assert re.sub(r"\s+", "", "".join(lines)) == re.sub(r"\s+", "", text)
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*", text)
    for word in words:
        if len(word) <= limit:
            assert any(word in line for line in lines)


def test_spaces_after_punctuation_not_deleted():
    assert _split_text("Fine! I'm ready.", 40) == ["Fine! I'm ready."]


def test_long_unbreakable_token_uses_hard_limit():
    text = "supercalifragilisticexpialidocious"
    lines = _split_text(text, 10)
    assert "".join(lines) == text and all(len(x) <= 10 for x in lines)


def test_chinese_existing_punctuation_policy():
    assert _split_text("甲乙丙丁。继续", 4) == ["甲乙丙", "丁。继续"]
