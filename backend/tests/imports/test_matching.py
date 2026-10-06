from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.dto.normalized import NormalizedPost, Platform, SourceType
from app.services.matching_service import TermCandidate, match_post, normalize_term


@pytest.mark.parametrize("value,key", [("ChatGPT", "chatgpt"), ("chatgpt", "chatgpt"),
    ("ＣｈａｔＧＰＴ", "chatgpt"), ("  #生成AI  ", "#生成ai"), ("#生成ai", "#生成ai"),
    ("ＡＩエージェント", "aiエージェント"), ("Ｓｔｒａße", "strasse")])
def test_normalization(value, key):
    assert normalize_term(value) == key


def matching(term="AI", key="ai", kind="KEYWORD", **post_values):
    candidate = TermCandidate(uuid4(), uuid4(), term, key, kind)
    post = NormalizedPost(SourceType.MARKET, Platform.X, "p", datetime.now(timezone.utc), **post_values)
    return candidate, match_post(post, [candidate])


@pytest.mark.parametrize("text,expected", [("AI", True), ("ai!", True), ("(ＡＩ)", True),
    ("AIエージェント", True), ("paid mail railway", False), ("AI_works", False),
    ("xAI", False), ("AI2", False), ("", False), ("生成AI", True)])
def test_ascii_boundary(text, expected):
    term, result = matching(text=text)
    assert (term.term_id in result.terms) == expected


@pytest.mark.parametrize("values,method", [(["#ChatGPT"], "EXACT"), (["#ＣｈａｔＧＰＴ"], "NORMALIZED"),
    (["#chatgpt", "#ChatGPT", "#ChatGPT"], "EXACT"), (["#Unknown"], None)])
def test_hashtags(values, method):
    term, result = matching("#ChatGPT", "#chatgpt", "HASHTAG", hashtags=values)
    assert result.terms.get(term.term_id) == method
    assert result.topics.get(term.topic_id) == ("HASHTAG" if method else None)


@pytest.mark.parametrize("keywords,method", [(["ChatGPT"], "EXACT"), (["ＣｈａｔＧＰＴ"], "NORMALIZED"),
    (["unknown"], None), (["chatgpt", "ChatGPT"], "EXACT")])
def test_explicit_keyword(keywords, method):
    term, result = matching("ChatGPT", "chatgpt", keywords=keywords)
    assert result.terms.get(term.term_id) == method


@pytest.mark.parametrize("term,key,text", [("生成AI", "生成ai", "新しい生成ＡＩ技術"),
    ("AIエージェント", "aiエージェント", "ＡＩエージェントを活用"), ("ChatGPT", "chatgpt", "Use ChatGPT today")])
def test_post_text(term, key, text):
    candidate, result = matching(term, key, text=text)
    assert result.terms[candidate.term_id] == "NORMALIZED"


def test_multiple_terms_and_topic_priority():
    topic = uuid4()
    terms = [TermCandidate(uuid4(), topic, "AI", "ai", "KEYWORD"),
             TermCandidate(uuid4(), topic, "#ChatGPT", "#chatgpt", "HASHTAG")]
    post = NormalizedPost(SourceType.MARKET, Platform.X, "p", datetime.now(timezone.utc),
                          text="AI", hashtags=["#ChatGPT"], keywords=["AI"])
    result = match_post(post, terms)
    assert list(result.terms.values()) == ["EXACT", "EXACT"]
    assert result.topics == {topic: "HASHTAG"}


def test_stored_key_is_authoritative():
    term, result = matching("AI", "different", keywords=["AI"], text="AI")
    assert not result.terms
