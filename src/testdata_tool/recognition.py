from __future__ import annotations

from pathlib import Path

from .config import AppConfig
from .models import DetectionResult
from .normalize import normalize_header


def _preview(path: Path, limit: int = 64 * 1024) -> tuple[bytes, str]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
    except OSError:
        return b"", ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp1252", "latin1"):
        try:
            return raw, raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw, raw.decode("latin1", errors="replace")


def _fingerprint_matches(path: Path, fingerprint: dict, raw: bytes, text: str) -> bool:
    kind = fingerprint.get("kind")
    value = str(fingerprint.get("value", ""))
    lines = text.splitlines()
    if kind == "first_line_contains":
        return bool(lines) and value.casefold() in lines[0].casefold()
    if kind == "first_line_prefix":
        return bool(lines) and lines[0].lstrip().casefold().startswith(value.casefold())
    if kind == "line_contains":
        index = int(fingerprint.get("line", 1))
        candidates = lines[max(0, index - 1) : index + 1]
        return any(value.casefold() in line.casefold() for line in candidates)
    if kind == "magic":
        return value.encode("latin1", errors="ignore") in raw[:32]
    if kind == "sheet_keyword":
        return False
    if kind == "sibling_ext":
        return any(
            sibling.is_file() and sibling.suffix.casefold() == value.casefold()
            for sibling in path.parent.iterdir()
        )
    return False


def detect_type(path: Path, config: AppConfig) -> DetectionResult:
    raw, text = _preview(path)
    haystack = normalize_header(str(path))
    scored: list[tuple[int, str, str]] = []
    for test_type, rule in config.type_rules.items():
        if test_type == "OTHERS":
            continue
        extensions = {str(ext).casefold() for ext in rule.get("extensions", [])}
        if path.suffix.casefold() not in extensions:
            continue
        score = 1
        reasons = ["扩展名"]
        if any(
            normalize_header(word) in haystack
            for word in rule.get("path_keywords", [])
        ):
            score += 20
            reasons.append("路径关键词")
        matched_fingerprints = sum(
            _fingerprint_matches(path, fp, raw, text)
            for fp in rule.get("fingerprints", [])
        )
        if matched_fingerprints:
            score += 100 * matched_fingerprints
            reasons.append("结构指纹")
        scored.append((score, test_type, "+".join(reasons)))
    if not scored:
        return DetectionResult(None, None, "没有匹配的扩展名或类型规则")
    scored.sort(reverse=True)
    best_score = scored[0][0]
    winners = [item for item in scored if item[0] == best_score]
    if len(winners) != 1:
        return DetectionResult(
            None,
            None,
            "类型冲突：" + "、".join(item[1] for item in winners),
            conflict=True,
        )
    _, test_type, reason = winners[0]
    parser_id = config.type_rules[test_type].get("parser")
    return DetectionResult(test_type, parser_id, reason)
