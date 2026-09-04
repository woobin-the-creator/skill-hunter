from __future__ import annotations

import json
import os
import re
from collections import deque
from pathlib import Path

from .frontmatter import FrontmatterError, clean_terminal_text, dependency_names, split_frontmatter
from .models import RepositoryIndex, SkillInfo


SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DEPENDENCY_KEYS = {"requires", "requiredskills", "skilldependencies"}


def _within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def discover_skill_files(root: Path, *, max_entries: int = 100_000) -> tuple[list[Path], list[str]]:
    root = root.resolve()
    queue: deque[Path] = deque([root])
    visited_directories: set[Path] = set()
    candidates: list[Path] = []
    warnings: list[str] = []
    entries_seen = 0

    while queue:
        logical_directory = queue.popleft()
        try:
            real_directory = logical_directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            warnings.append(f"unreadable or circular directory link {logical_directory}: {type(exc).__name__}")
            continue
        if not _within(root, real_directory):
            warnings.append(f"ignored directory symlink outside repository: {logical_directory.relative_to(root)}")
            continue
        if real_directory in visited_directories:
            continue
        visited_directories.add(real_directory)
        try:
            children = sorted(logical_directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            warnings.append(f"could not read {logical_directory.relative_to(root)}: {type(exc).__name__}")
            continue
        for child in children:
            entries_seen += 1
            if entries_seen > max_entries:
                warnings.append(f"repository scan stopped at entry limit ({max_entries})")
                return candidates, warnings
            if child.name == ".git":
                continue
            try:
                if child.is_symlink():
                    try:
                        resolved = child.resolve(strict=True)
                    except (OSError, RuntimeError) as exc:
                        warnings.append(f"broken or circular symlink: {child.relative_to(root)} ({type(exc).__name__})")
                        continue
                    if not _within(root, resolved):
                        warnings.append(f"ignored symlink outside repository: {child.relative_to(root)} -> {os.readlink(child)}")
                        continue
                    if resolved.is_dir():
                        queue.append(child)
                    elif child.name == "SKILL.md" and resolved.is_file():
                        candidates.append(child)
                elif child.is_dir():
                    queue.append(child)
                elif child.name == "SKILL.md" and child.is_file():
                    candidates.append(child)
            except OSError as exc:
                warnings.append(f"could not inspect {child.relative_to(root)}: {type(exc).__name__}")
    return candidates, warnings


def index_repository(
    root: Path,
    source_url: str,
    revision: str,
    *,
    max_entries: int = 100_000,
) -> RepositoryIndex:
    root = root.resolve()
    candidates, warnings = discover_skill_files(root, max_entries=max_entries)
    skills: dict[str, SkillInfo] = {}
    duplicate_names: dict[str, list[str]] = {}

    for skill_file in sorted(candidates, key=lambda path: path.relative_to(root).as_posix()):
        relative_file = skill_file.relative_to(root).as_posix()
        relative_directory = skill_file.parent.relative_to(root).as_posix() or "."
        candidate_warnings: list[str] = []
        installable = True
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            warnings.append(f"could not read {relative_file}: {type(exc).__name__}")
            continue
        try:
            frontmatter, body = split_frontmatter(raw)
        except FrontmatterError as exc:
            frontmatter = {}
            body = raw
            candidate_warnings.append(str(exc))
            installable = False

        raw_name = frontmatter.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            name = skill_file.parent.name if relative_directory != "." else "unnamed-root-skill"
            candidate_warnings.append("missing string frontmatter field: name")
            installable = False
        else:
            name = clean_terminal_text(raw_name.strip())

        raw_description = frontmatter.get("description")
        if not isinstance(raw_description, str) or not raw_description.strip():
            description = ""
            candidate_warnings.append("missing string frontmatter field: description")
            installable = False
        else:
            description = clean_terminal_text(raw_description.strip())

        if len(name) > 64 or not SKILL_NAME.fullmatch(name):
            candidate_warnings.append("name does not match the portable Agent Skills grammar")
            installable = False
        if len(description) > 1024:
            candidate_warnings.append("description exceeds the 1024-character portable limit")
            installable = False
        if relative_directory != "." and name != skill_file.parent.name:
            candidate_warnings.append(
                f"frontmatter name {name!r} does not match directory {skill_file.parent.name!r}; "
                "the destination link will use the frontmatter name"
            )
        if skill_file.is_symlink() or skill_file.parent.is_symlink():
            candidate_warnings.append("skill entrypoint is reached through a repository symlink")

        dependencies = [clean_terminal_text(item) for item in dependency_names(frontmatter)]
        dependency_sources = {dependency: f"{relative_file} frontmatter" for dependency in dependencies}
        manifest_candidates = [
            skill_file.parent / "skill.json",
            skill_file.parent / "plugin.json",
            skill_file.parent / "manifest.json",
            root / "plugin.json",
            root / ".claude-plugin" / "plugin.json",
        ]
        seen_manifests: set[Path] = set()
        for manifest in manifest_candidates:
            if manifest in seen_manifests or not manifest.exists():
                continue
            seen_manifests.add(manifest)
            manifest_relative = manifest.relative_to(root).as_posix()
            try:
                resolved_manifest = manifest.resolve(strict=True)
                if not _within(root, resolved_manifest):
                    candidate_warnings.append(f"ignored repository-external dependency manifest: {manifest_relative}")
                    continue
                if manifest.stat().st_size > 1024 * 1024:
                    candidate_warnings.append(f"ignored oversized dependency manifest: {manifest_relative}")
                    continue
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                candidate_warnings.append(f"could not parse dependency manifest {manifest_relative}: {type(exc).__name__}")
                continue
            for dependency in _json_dependency_names(payload):
                dependency = clean_terminal_text(dependency)
                if dependency not in dependencies:
                    dependencies.append(dependency)
                    dependency_sources[dependency] = manifest_relative
        info = SkillInfo(
            name=name,
            path=relative_directory,
            description=description,
            frontmatter=frontmatter,
            body=body,
            explicit_dependencies=dependencies,
            dependency_sources=dependency_sources,
            installable=installable,
            warnings=candidate_warnings,
        )
        if name in skills:
            paths = duplicate_names.setdefault(name, [skills[name].path])
            paths.append(relative_directory)
            skills[name].installable = False
            skills[name].warnings.append(f"duplicate skill name at {relative_directory}")
            continue
        skills[name] = info

    for name, paths in duplicate_names.items():
        warnings.append(f"duplicate skill name {name!r}: {', '.join(paths)}")
    if not skills:
        warnings.append("no SKILL.md candidates were discovered")
    return RepositoryIndex(root, source_url, revision, skills, warnings, duplicate_names)


def _json_dependency_names(payload: object) -> list[str]:
    found: list[str] = []

    def add(value: object) -> None:
        values: list[object]
        if isinstance(value, list):
            values = value
        elif isinstance(value, str):
            values = re.split(r"[,\s]+", value)
        else:
            return
        for item in values:
            if isinstance(item, str):
                name = item.strip().strip("'\"")
                if name and name not in found:
                    found.append(name)

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("_", "").replace("-", "")
                if normalized in _DEPENDENCY_KEYS:
                    add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found
