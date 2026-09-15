from __future__ import annotations

import re
import unicodedata
from collections import defaultdict


_INVISIBLE = "\u00ad\u200b\u200c\u200d\u2060\ufeff"
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_OPEN_BRACKETS = "([{\u3010\uff3b"
_CLOSE_BRACKETS = ")]}\u3011\uff3d"


def _recover_degree_mojibake(text: str) -> str:
    """Repair a CP1252 unit that was previously decoded as GB18030.

    This deliberately only accepts a repaired candidate containing a degree
    unit.  It never transforms normal Chinese field names merely because they
    can be round-tripped through a different encoding.
    """
    if not any("\u3400" <= char <= "\u9fff" for char in text):
        return text
    try:
        repaired = text.encode("gb18030").decode("cp1252")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if re.search(r"[\u00b0\u00ba\u02da]\s*[cCfFkK]", repaired):
        return repaired
    return text


def _normalise_degree_units(text: str) -> str:
    # NFKC turns the half-width Japanese long sound mark (ｰ) into ー.  It is
    # only a degree-sign lookalike in a unit position, so leave ordinary Japanese
    # names untouched and convert it only immediately before C/F/K.
    return re.sub(
        r"[\u00b0\u00ba\u02da\u30fc\uff70]\s*([cCfFkK])",
        lambda match: "\u00b0" + match.group(1),
        text,
    )


def normalize_header(value: object) -> str:
    if value is None:
        return ""
    text = _recover_degree_mojibake(str(value))
    # NFKC would otherwise turn masculine ordinal º into the letter o.
    text = text.replace("\u00ba", "\u00b0").replace("\u02da", "\u00b0")
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans({char: "" for char in _INVISIBLE})
    )
    text = _normalise_degree_units(text)
    text = text.translate(str.maketrans(_DASHES, "-" * len(_DASHES)))
    text = text.translate(str.maketrans(_OPEN_BRACKETS, "[" * len(_OPEN_BRACKETS)))
    text = text.translate(str.maketrans(_CLOSE_BRACKETS, "]" * len(_CLOSE_BRACKETS)))
    text = text.casefold()
    # Headers vary between e.g. "TCK 01", "TCK-01", "TCK_01" and "TCK01".
    # Separator punctuation has no semantic value in a column name, while the
    # degree sign is retained to keep temperature units distinct from bare C/F/K.
    compact = "".join(
        char
        for char in text
        if char in "[]" or unicodedata.category(char)[0] != "P"
    )
    return re.sub(r"\s+", " ", compact).strip()


def _matching_keys(value: object) -> set[str]:
    key = normalize_header(value)
    # Some exporters remove a separator entirely while others replace it with a
    # space.  Use both forms so "actual_value" and "actual value" match, while
    # retaining the readable normalized form for rules and diagnostics.
    return {key, key.replace(" ", "")} if key else set()


def build_alias_index(
    canonical_fields: list[str], aliases: dict[str, list[str]] | None = None
) -> dict[str, set[str]]:
    aliases = aliases or {}
    index: dict[str, set[str]] = defaultdict(set)
    for canonical in canonical_fields:
        for candidate in [canonical, *aliases.get(canonical, [])]:
            for key in _matching_keys(candidate):
                index[key].add(canonical)
    return dict(index)


def match_headers(
    canonical_fields: list[str],
    actual_fields: list[str],
    aliases: dict[str, list[str]] | None = None,
) -> tuple[dict[str, str], list[str]]:
    index = build_alias_index(canonical_fields, aliases)
    actual_by_key: dict[str, list[str]] = defaultdict(list)
    for actual in actual_fields:
        # The compact key is used only when direct normalization found nothing.
        # Keeping one key per source header avoids duplicate diagnostics here.
        direct = normalize_header(actual)
        if direct:
            actual_by_key[direct].append(actual)

    mapping: dict[str, str] = {}
    errors: list[str] = []
    for key, actuals in actual_by_key.items():
        targets = index.get(key, set())
        if not targets:
            targets = index.get(key.replace(" ", ""), set())
        if len(actuals) > 1 and targets:
            errors.append(f"重复表头 {actuals[0]}")
        if len(targets) > 1:
            errors.append(f"表头 {actuals[0]} 同时匹配多个标准字段")
        if len(actuals) == 1 and len(targets) == 1:
            target = next(iter(targets))
            if target in mapping:
                errors.append(f"多个原始字段匹配 {target}")
            else:
                mapping[target] = actuals[0]
    return mapping, errors
