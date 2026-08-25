"""Named ticker filter segments — parse, expand, and match.

Syntax (filter box / stored match strings):
  plain terms     OR substring includes (comma-separated)
  -term           exclude (wins over includes)
  @Name           expand named segment (per-user)
  * / +*          starred OR / AND (mobile parity)

Define / delete are client commands against preferences, not match tokens:
  @Name=terms     upsert segment
  @Name!          delete segment
"""

from __future__ import annotations

import re
from typing import Any, Mapping

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_REF_RE = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{0,31})$")
_DEFINE_RE = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{0,31})=(.*)$", re.DOTALL)
_DELETE_RE = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{0,31})!$")

MAX_EXPAND_DEPTH = 4


def normalize_segment_name(name: str) -> str | None:
    text = str(name or "").strip()
    if not text or not NAME_RE.match(text):
        return None
    return text.upper()


def parse_command(raw: str) -> dict[str, Any] | None:
    """Return define/delete command if the *entire* field is a segment command."""
    text = str(raw or "").strip()
    if not text:
        return None
    deleted = _DELETE_RE.match(text)
    if deleted:
        name = normalize_segment_name(deleted.group(1))
        return {"op": "delete", "name": name} if name else None
    defined = _DEFINE_RE.match(text)
    if defined:
        name = normalize_segment_name(defined.group(1))
        if not name:
            return None
        return {"op": "define", "name": name, "match": defined.group(2).strip()}
    return None


def split_terms(filter_text: str) -> list[str]:
    return [part.strip() for part in str(filter_text or "").split(",") if part.strip()]


def expand_filter(
    filter_text: str,
    segments: Mapping[str, str] | None,
    *,
    depth: int = 0,
    stack: frozenset[str] | None = None,
) -> str:
    """Resolve ``@Name`` refs into their stored match strings (cycle-safe).

    Incomplete tokens (bare ``@`` / unknown ``@Name``) are dropped so typing
    toward a segment does not wipe the filtered list.

    In-progress define tokens (``@Name=AMZN``) contribute the RHS so the first
    ticker after ``=`` is not dropped when comma-splitting ``@Name=AMZN,GOOG``.
    """
    segs = {str(k).upper(): str(v) for k, v in (segments or {}).items() if v is not None}
    seen = stack or frozenset()
    out: list[str] = []
    for term in split_terms(filter_text):
        # Live ``@Name=…`` while defining — use the match RHS, not the @ token.
        defined = _DEFINE_RE.match(term)
        if defined:
            rest = defined.group(2).strip()
            if rest:
                out.extend(split_terms(expand_filter(rest, segs, depth=depth, stack=seen)))
            continue
        if term == "@" or re.match(r"^@[A-Za-z0-9_]*$", term):
            ref = _REF_RE.match(term)
            if not ref:
                continue
            name = ref.group(1).upper()
            if name in seen or depth >= MAX_EXPAND_DEPTH:
                continue
            body = segs.get(name)
            if body is None or body == "":
                continue
            expanded = expand_filter(body, segs, depth=depth + 1, stack=seen | {name})
            out.extend(split_terms(expanded))
            continue
        out.append(term)
    return ", ".join(out)


def parse_match_terms(filter_text: str) -> dict[str, Any]:
    includes: list[str] = []
    excludes: list[str] = []
    require_starred = False
    for term in split_terms(filter_text):
        if term.startswith("@"):
            continue
        lower = term.lower()
        if lower in ("+*", "+star"):
            require_starred = True
            continue
        if lower in ("*", "star", "⭐"):
            includes.append("*")
            continue
        if term.startswith("-") and len(term) > 1:
            excludes.append(term[1:].lower())
            continue
        includes.append(lower)
    return {
        "includes": includes,
        "excludes": excludes,
        "requireStarred": require_starred,
    }


def symbol_matches_filter(
    symbol: str,
    filter_text: str,
    *,
    segments: Mapping[str, str] | None = None,
    starred: set[str] | frozenset[str] | None = None,
) -> bool:
    expanded = expand_filter(filter_text, segments)
    parsed = parse_match_terms(expanded)
    sym = str(symbol or "").upper()
    sym_l = sym.lower()
    starred_set = {str(s).upper() for s in (starred or set())}
    is_starred = sym in starred_set

    if parsed["requireStarred"] and not is_starred:
        return False
    for ex in parsed["excludes"]:
        if ex and ex in sym_l:
            return False
    includes = parsed["includes"]
    if not includes:
        return True
    return any(
        (term == "*" and is_starred) or (term != "*" and term in sym_l)
        for term in includes
    )


def normalize_segments_map(raw: Any) -> dict[str, str]:
    """Coerce preferences blob → ``{NAME: matchString}`` (drop invalid)."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = normalize_segment_name(str(key))
        if not name:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        out[name] = text
    return dict(sorted(out.items()))


def merge_segments(
    current: Mapping[str, str],
    incoming: Any,
) -> dict[str, str]:
    """Merge patch. ``null`` / ``""`` deletes a name; other strings upsert."""
    out = dict(current)
    if not isinstance(incoming, dict):
        raise ValueError("tickerSegments must be an object")
    for key, value in incoming.items():
        name = normalize_segment_name(str(key))
        if not name:
            raise ValueError(
                f"invalid segment name {key!r} "
                "(use letters/digits/underscore, start with a letter)"
            )
        if value is None or (isinstance(value, str) and value.strip() == ""):
            out.pop(name, None)
            continue
        out[name] = str(value).strip()
    return dict(sorted(out.items()))


def export_segments_text(segments: Mapping[str, str]) -> str:
    lines = [f"@{name}={match}" for name, match in normalize_segments_map(segments).items()]
    return "\n".join(lines) + ("\n" if lines else "")
