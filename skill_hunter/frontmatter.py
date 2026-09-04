from __future__ import annotations

import json
import re
from typing import Any


class FrontmatterError(ValueError):
    pass


_DEPENDENCY_KEYS = {
    "requires",
    "requiredskills",
    "required-skills",
    "skilldependencies",
    "skill-dependencies",
}


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the deliberately small YAML subset used by Agent Skill metadata."""
    normalized = text.replace("\r\n", "\n")
    opening = re.match(r"\A---[ \t]*\n", normalized)
    if opening is None:
        raise FrontmatterError("SKILL.md must begin with YAML frontmatter")
    closing = re.search(r"^---[ \t]*(?:\n|\Z)", normalized[opening.end() :], re.MULTILINE)
    if closing is None:
        raise FrontmatterError("SKILL.md frontmatter is missing its closing delimiter")
    start = opening.end()
    end = start + closing.start()
    suffix = normalized[start + closing.end() :]
    raw = normalized[start:end]
    return _parse_yaml_subset(raw), suffix


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def _split_key_value(text: str) -> tuple[str, str]:
    quote: str | None = None
    for index, char in enumerate(text):
        if char in {"'", '"'}:
            quote = None if quote == char else (char if quote is None else quote)
        elif char == ":" and quote is None:
            key = text[:index].strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
                raise FrontmatterError(f"unsupported frontmatter key: {key!r}")
            return key, text[index + 1 :].strip()
    raise FrontmatterError(f"expected key/value mapping entry: {text!r}")


def _parse_scalar(value: str) -> Any:
    value = _strip_comment(value).strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_inline_items(inner)]
    if value.startswith("{") and value.endswith("}"):
        result: dict[str, Any] = {}
        for item in _split_inline_items(value[1:-1]):
            key, child = _split_key_value(item)
            result[key] = _parse_scalar(child)
        return result
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value[1:-1]
        return value[1:-1].replace("''", "'")
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    return value


def _split_inline_items(value: str) -> list[str]:
    items: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if quote is not None:
            continue
        if char in "[{(":
            depth += 1
        elif char in "]})":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            items.append(value[start:index].strip())
            start = index + 1
    items.append(value[start:].strip())
    return [item for item in items if item]


def _parse_yaml_subset(raw: str) -> dict[str, Any]:
    lines = raw.splitlines()
    meaningful = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not meaningful:
        return {}
    if "\t" in raw:
        raise FrontmatterError("tabs are not supported in frontmatter indentation")

    def parse_block(start: int, level: int) -> tuple[Any, int]:
        while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("#")):
            start += 1
        if start >= len(lines):
            return {}, start
        is_list = lines[start][level:].lstrip().startswith("-")
        container: Any = [] if is_list else {}
        index = start
        while index < len(lines):
            line = lines[index]
            if not line.strip() or line.lstrip().startswith("#"):
                index += 1
                continue
            current = _indent(line)
            if current < level:
                break
            if current > level:
                raise FrontmatterError(f"unexpected indentation on line {index + 1}")
            stripped = line.strip()
            if is_list:
                if not stripped.startswith("-"):
                    break
                item = stripped[1:].strip()
                if not item:
                    next_index = index + 1
                    if next_index < len(lines) and _indent(lines[next_index]) > level:
                        value, index = parse_block(next_index, _indent(lines[next_index]))
                        container.append(value)
                        continue
                    container.append(None)
                elif ":" in item and re.match(r"^[A-Za-z0-9_.-]+\s*:", item):
                    key, child = _split_key_value(item)
                    container.append({key: _parse_scalar(child)})
                else:
                    container.append(_parse_scalar(item))
                index += 1
                continue

            key, value_text = _split_key_value(stripped)
            if value_text in {"|", ">", "|-", ">-", "|+", ">+"}:
                block_lines: list[str] = []
                index += 1
                while index < len(lines):
                    child_line = lines[index]
                    if child_line.strip() and _indent(child_line) <= level:
                        break
                    cut = min(len(child_line), level + 2)
                    block_lines.append(child_line[cut:])
                    index += 1
                separator = "\n" if value_text.startswith("|") else " "
                container[key] = separator.join(part.strip() if separator == " " else part for part in block_lines).strip()
                continue
            if value_text:
                container[key] = _parse_scalar(value_text)
                index += 1
                continue
            next_index = index + 1
            while next_index < len(lines) and (not lines[next_index].strip() or lines[next_index].lstrip().startswith("#")):
                next_index += 1
            if next_index < len(lines) and _indent(lines[next_index]) > level:
                child_text = lines[next_index].strip()
                child_is_collection = child_text.startswith("-") or bool(
                    re.match(r"^[A-Za-z0-9_.-]+\s*:", child_text)
                )
                if child_is_collection:
                    value, index = parse_block(next_index, _indent(lines[next_index]))
                    container[key] = value
                else:
                    continuation: list[str] = []
                    index = next_index
                    while index < len(lines):
                        child_line = lines[index]
                        if child_line.strip() and _indent(child_line) <= level:
                            break
                        if child_line.strip() and not child_line.lstrip().startswith("#"):
                            continuation.append(_strip_comment(child_line.strip()))
                        index += 1
                    container[key] = " ".join(part for part in continuation if part).strip()
            else:
                container[key] = {}
                index += 1
        return container, index

    first_indent = _indent(meaningful[0])
    parsed, _ = parse_block(0, first_indent)
    if not isinstance(parsed, dict):
        raise FrontmatterError("frontmatter root must be a mapping")
    return parsed


def dependency_names(frontmatter: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def add_value(value: Any) -> None:
        values: list[Any]
        if isinstance(value, list):
            values = value
        elif isinstance(value, str):
            values = re.split(r"[,\s]+", value)
        else:
            return
        for item in values:
            if not isinstance(item, str):
                continue
            name = item.strip().strip("'\"")
            if name and name not in found:
                found.append(name)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("_", "-")
                comparable = normalized.replace("-", "")
                if normalized in _DEPENDENCY_KEYS or comparable in {
                    key.replace("-", "") for key in _DEPENDENCY_KEYS
                }:
                    add_value(child)
                elif normalized in {"metadata", "dependencies", "dependency"}:
                    visit(child)

    visit(frontmatter)
    return found


def clean_terminal_text(value: str) -> str:
    return "".join(char for char in value if char in "\n\t" or ord(char) >= 32).replace("\x1b", "")
