"""Deterministic matching against the stored normalized watch-term keys."""
import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from app.dto.normalized import NormalizedPost


def normalize_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


@dataclass(frozen=True)
class TermCandidate:
    term_id: UUID
    topic_id: UUID
    term: str
    normalized_term: str
    term_type: str


@dataclass(frozen=True)
class Matches:
    terms: dict[UUID, str]
    topics: dict[UUID, str]


def match_post(post: NormalizedPost, candidates: list[TermCandidate]) -> Matches:
    terms: dict[UUID, str] = {}
    topics: dict[UUID, str] = {}
    text = normalize_term(post.text or "")
    for term in candidates:
        key = term.normalized_term  # DB is authoritative; never rewrite seed keys.
        if not key:
            continue
        values = post.hashtags if term.term_type == "HASHTAG" else post.keywords
        methods = ["EXACT" if value.strip() == term.term else "NORMALIZED"
                   for value in values if normalize_term(value) == key]
        if term.term_type == "KEYWORD":
            if re.fullmatch(r"[a-z0-9_]+", key):
                found = re.search(r"(?<![a-z0-9_])" + re.escape(key) + r"(?![a-z0-9_])", text)
            else:
                found = key in text
            if found:
                methods.append("NORMALIZED")
        if methods:
            terms[term.term_id] = "EXACT" if "EXACT" in methods else "NORMALIZED"
            if term.term_type == "HASHTAG" or term.topic_id not in topics:
                topics[term.topic_id] = term.term_type
    return Matches(terms, topics)
