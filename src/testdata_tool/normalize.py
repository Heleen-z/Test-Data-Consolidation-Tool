from __future__ import annotations

import re
import unicodedata
from collections import defaultdict


def normalize_header(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"\s+", " ", text)


def build_alias_index(
    canonical_fields: list[str], aliases: dict[str, list[str]] | None = None
) -> dict[str, set[str]]:
    aliases = aliases or {}
    index: dict[str, set[str]] = defaultdict(set)
    for canonical in canonical_fields:
        for candidate in [canonical, *aliases.get(canonical, [])]:
            key = normalize_header(candidate)
            if key:
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
        actual_by_key[normalize_header(actual)].append(actual)

    mapping: dict[str, str] = {}
    errors: list[str] = []
    for key, actuals in actual_by_key.items():
        targets = index.get(key, set())
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

