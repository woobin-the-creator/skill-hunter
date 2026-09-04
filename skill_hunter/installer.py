from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AnalysisResult, CollisionError, RepositoryIndex, SafetyError, SkillHunterError


TARGETS = ("auto", "claude", "opencode", "codex", "codex-legacy", "universal", "custom")
SCOPES = ("project", "global")
LINK_MODES = ("auto", "symlink", "copy")


@dataclass
class InstallPlan:
    destination: Path
    state_root: Path
    store: Path
    target: str
    scope: str
    link_mode: str
    copy_safe: bool
    closure_id: str
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "destination": str(self.destination),
            "state_root": str(self.state_root),
            "store": str(self.store),
            "target": self.target,
            "scope": self.scope,
            "link_mode": self.link_mode,
            "copy_safe": self.copy_safe,
            "closure_id": self.closure_id,
            "conflicts": self.conflicts,
        }


def resolve_destination(
    target: str,
    scope: str,
    *,
    project_root: Path,
    destination: str | None = None,
) -> tuple[str, Path]:
    if target not in TARGETS:
        raise SkillHunterError(f"unsupported target: {target}")
    if scope not in SCOPES:
        raise SkillHunterError(f"unsupported scope: {scope}")
    project_root = project_root.expanduser().resolve()
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser()

    if target == "custom":
        if not destination:
            raise SkillHunterError("--target custom requires --destination")
        return target, Path(destination).expanduser().resolve()
    if destination:
        raise SkillHunterError("--destination is accepted only with --target custom")
    if target == "auto":
        target = _detect_target(scope, project_root)

    if scope == "project":
        relative = {
            "claude": ".claude/skills",
            "opencode": ".opencode/skills",
            "codex": ".agents/skills",
            "codex-legacy": ".codex/skills",
            "universal": ".agents/skills",
        }[target]
        resolved = (project_root / relative).resolve()
        if os.path.commonpath((str(project_root), str(resolved))) != str(project_root):
            raise SafetyError("project destination resolves outside the selected project root")
        return target, resolved

    global_destinations = {
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser() / "skills",
        "opencode": config_home / "opencode" / "skills",
        "codex": home / ".agents" / "skills",
        "codex-legacy": Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser() / "skills",
        "universal": config_home / "agents" / "skills",
    }
    return target, global_destinations[target].resolve()


def _detect_target(scope: str, project_root: Path) -> str:
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser()
    if scope == "project":
        candidates = {
            "claude": project_root / ".claude",
            "opencode": project_root / ".opencode",
            "codex": project_root / ".agents",
            "codex-legacy": project_root / ".codex",
        }
    else:
        candidates = {
            "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser(),
            "opencode": config_home / "opencode",
            "codex": home / ".agents",
            "codex-legacy": Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser(),
        }
    detected = [name for name, marker in candidates.items() if marker.exists()]
    if len(detected) == 1:
        return detected[0]
    if not detected:
        raise SkillHunterError(
            "could not auto-detect an agent; pass --target claude, opencode, codex, universal, or custom"
        )
    raise SkillHunterError(f"agent detection is ambiguous ({', '.join(detected)}); pass --target explicitly")


def default_state_root(scope: str, project_root: Path) -> Path:
    if scope == "project":
        return project_root.expanduser().resolve() / ".skill-hunter"
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")).expanduser()
    return data_home.resolve() / "skill-hunter"


def make_install_plan(
    index: RepositoryIndex,
    analysis: AnalysisResult,
    *,
    target: str,
    scope: str,
    project_root: Path,
    destination: str | None = None,
    state_dir: str | None = None,
    link_mode: str = "auto",
) -> InstallPlan:
    if link_mode not in LINK_MODES:
        raise SkillHunterError(f"unsupported link mode: {link_mode}")
    resolved_target, resolved_destination = resolve_destination(
        target,
        scope,
        project_root=project_root,
        destination=destination,
    )
    state_root = Path(state_dir).expanduser().resolve() if state_dir else default_state_root(scope, project_root)
    if _paths_overlap(state_root, resolved_destination):
        raise SafetyError("the content/provenance state directory must not overlap the agent skill destination")
    source_slug = _source_slug(analysis.source_url)
    closure = _closure_identifier(index, analysis)
    store = state_root / "stores" / source_slug / f"{analysis.revision.replace(':', '-')[:40]}-{closure[:12]}"
    copy_safe = _copy_mode_safe(index, analysis)
    if link_mode == "copy" and not copy_safe:
        raise SafetyError(
            "copy mode cannot preserve this graph's repository-relative paths; use symlink mode"
        )

    conflicts: list[dict[str, Any]] = []
    for skill_name in analysis.installed_skills:
        target_path = resolved_destination / skill_name
        if os.path.lexists(target_path):
            info = index.skills[skill_name]
            source_path = index.root if info.path == "." else index.root.joinpath(*info.path.split("/"))
            conflicts.append(_describe_conflict(skill_name, source_path, target_path))
    return InstallPlan(
        destination=resolved_destination,
        state_root=state_root,
        store=store,
        target=resolved_target,
        scope=scope,
        link_mode=link_mode,
        copy_safe=copy_safe,
        closure_id=closure,
        conflicts=conflicts,
    )


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        common = Path(os.path.commonpath((str(first), str(second))))
    except ValueError:
        return False
    return common == first or common == second


def _source_slug(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.hostname == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        value = "--".join(parts[:2])
    else:
        value = Path(urllib.parse.unquote(parsed.path)).name or "local"
    safe = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in safe.split("-") if part)[:120] or "source"


def _closure_identifier(index: RepositoryIndex, analysis: AnalysisResult) -> str:
    digest = hashlib.sha256()
    digest.update(analysis.source_url.encode())
    digest.update(analysis.revision.encode())
    for relative in analysis.included_paths:
        digest.update(b"\0")
        digest.update(relative.encode())
        path = index.root.joinpath(*relative.split("/"))
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(b"F")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _copy_mode_safe(index: RepositoryIndex, analysis: AnalysisResult) -> bool:
    if len(analysis.installed_skills) != 1:
        return False
    root = index.skills[analysis.installed_skills[0]].path
    if root == ".":
        return True
    prefix = f"{root}/"
    return all(path == root or path.startswith(prefix) for path in analysis.included_paths)


def _tree_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if root.is_symlink():
        return {".": f"link:{os.readlink(root)}"}
    if not root.is_dir():
        return {".": "non-directory"}
    for current, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        current_path = Path(current)
        for name in list(directories):
            path = current_path / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                manifest[relative] = f"link:{os.readlink(path)}"
                directories.remove(name)
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                manifest[relative] = f"link:{os.readlink(path)}"
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest[relative] = f"sha256:{digest}"
    return manifest


def _describe_conflict(skill_name: str, source: Path, destination: Path) -> dict[str, Any]:
    if destination.is_symlink():
        return {
            "skill": skill_name,
            "path": str(destination),
            "kind": "symlink",
            "detail": f"existing symlink -> {os.readlink(destination)}",
        }
    try:
        source_manifest = _tree_manifest(source)
        destination_manifest = _tree_manifest(destination)
        added = sorted(set(source_manifest) - set(destination_manifest))
        removed = sorted(set(destination_manifest) - set(source_manifest))
        changed = sorted(
            path for path in set(source_manifest) & set(destination_manifest) if source_manifest[path] != destination_manifest[path]
        )
        detail = f"would add {len(added)}, change {len(changed)}, leave destination-only {len(removed)} files"
        return {
            "skill": skill_name,
            "path": str(destination),
            "kind": "directory" if destination.is_dir() else "file",
            "detail": detail,
            "sample_added": added[:5],
            "sample_changed": changed[:5],
            "sample_destination_only": removed[:5],
        }
    except OSError as exc:
        return {
            "skill": skill_name,
            "path": str(destination),
            "kind": "unreadable",
            "detail": type(exc).__name__,
        }


def execute_install(index: RepositoryIndex, analysis: AnalysisResult, plan: InstallPlan) -> dict[str, Any]:
    if analysis.blockers:
        raise SafetyError("installation blocked: " + "; ".join(analysis.blockers))
    if plan.conflicts:
        names = ", ".join(conflict["skill"] for conflict in plan.conflicts)
        raise CollisionError(f"existing skill paths would be overwritten ({names}); no files were changed")
    if _closure_identifier(index, analysis) != plan.closure_id:
        raise SafetyError("source content changed after analysis; run a new dry-run before installing")

    plan.state_root.mkdir(parents=True, exist_ok=True)
    stores_parent = plan.store.parent
    stores_parent.mkdir(parents=True, exist_ok=True)
    staging_parent = plan.state_root / "staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="install-", dir=staging_parent))
    new_store = False
    created_paths: list[Path] = []
    actual_mode = plan.link_mode
    try:
        repo_stage = stage / "repo"
        repo_stage.mkdir()
        _materialize_closure(index.root, repo_stage, analysis.included_paths)
        provenance = _build_provenance(index, analysis, plan)
        _write_json_atomic(stage / "provenance.json", provenance)

        if plan.store.exists():
            existing = _read_json(plan.store / "provenance.json")
            if existing.get("closure_id") != provenance["closure_id"]:
                raise SafetyError(f"existing content store is inconsistent: {plan.store}")
            shutil.rmtree(stage)
        else:
            os.replace(stage, plan.store)
            new_store = True

        plan.destination.mkdir(parents=True, exist_ok=True)
        try:
            created_paths, actual_mode = _expose_skills(index, analysis, plan)
        except OSError:
            for path in reversed(created_paths):
                _remove_created_path(path)
            created_paths = []
            if plan.link_mode == "auto" and plan.copy_safe:
                actual_mode = "copy"
                created_paths, actual_mode = _expose_skills(index, analysis, plan, force_copy=True)
            else:
                raise

        registry_path = plan.state_root / "registry.json"
        registry = _read_json(registry_path) if registry_path.exists() else {"schema_version": 1, "installations": {}}
        if not isinstance(registry.get("installations"), dict):
            raise SafetyError(f"invalid registry format: {registry_path}")
        installed_at = provenance["installed_at"]
        if len(analysis.installed_skills) != len(created_paths):
            raise SafetyError("installer produced an inconsistent number of exposed skill paths")
        for skill_name, exposed in zip(analysis.installed_skills, created_paths):
            registry["installations"][str(exposed)] = {
                "source": analysis.source_url,
                "commit": analysis.revision,
                "skill": skill_name,
                "store": str(plan.store),
                "target": plan.target,
                "scope": plan.scope,
                "mode": actual_mode,
                "installed_at": installed_at,
            }
        _write_json_atomic(registry_path, registry)
        return {
            "installed": [str(path) for path in created_paths],
            "store": str(plan.store),
            "registry": str(registry_path),
            "mode": actual_mode,
            "revision": analysis.revision,
        }
    except Exception:
        for path in reversed(created_paths):
            _remove_created_path(path)
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if new_store and plan.store.exists():
            shutil.rmtree(plan.store, ignore_errors=True)
        raise


def _materialize_closure(source_root: Path, destination_root: Path, paths: list[str]) -> None:
    for relative in sorted(paths, key=lambda value: (value.count("/"), value)):
        source = source_root.joinpath(*relative.split("/"))
        destination = destination_root.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        info = source.lstat()
        if source.is_symlink():
            target = os.readlink(source)
            if os.path.isabs(target):
                raise SafetyError(f"refused absolute symlink during materialization: {relative}")
            try:
                resolved_target = source.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise SafetyError(f"refused broken or circular symlink during materialization: {relative}") from exc
            if os.path.commonpath((str(source_root.resolve()), str(resolved_target))) != str(source_root.resolve()):
                raise SafetyError(f"refused repository-external symlink during materialization: {relative}")
            os.symlink(target, destination)
        elif source.is_file():
            shutil.copy2(source, destination, follow_symlinks=False)
        else:
            raise SafetyError(f"closure contains unsupported entry: {relative} ({info.st_mode:o})")


def _build_provenance(index: RepositoryIndex, analysis: AnalysisResult, plan: InstallPlan) -> dict[str, Any]:
    file_records: list[dict[str, str]] = []
    for relative in analysis.included_paths:
        path = index.root.joinpath(*relative.split("/"))
        if path.is_symlink():
            file_records.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
        else:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            file_records.append({"path": relative, "type": "file", "sha256": digest.hexdigest()})
    return {
        "schema_version": 1,
        "source": analysis.source_url,
        "commit": analysis.revision,
        "requested_skills": analysis.requested_skills,
        "installed_skills": analysis.installed_skills,
        "closure_id": plan.closure_id,
        "dependencies": [edge.public_dict() for edge in analysis.edges],
        "files": file_records,
        "destination": str(plan.destination),
        "target": plan.target,
        "scope": plan.scope,
        "installed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _expose_skills(
    index: RepositoryIndex,
    analysis: AnalysisResult,
    plan: InstallPlan,
    *,
    force_copy: bool = False,
) -> tuple[list[Path], str]:
    mode = "copy" if force_copy or plan.link_mode == "copy" else "symlink"
    created: list[Path] = []
    try:
        for skill_name in analysis.installed_skills:
            info = index.skills[skill_name]
            stored_skill = plan.store / "repo"
            if info.path != ".":
                stored_skill = stored_skill.joinpath(*info.path.split("/"))
            destination = plan.destination / skill_name
            if os.path.lexists(destination):
                raise CollisionError(f"destination appeared during install: {destination}")
            if mode == "copy":
                shutil.copytree(stored_skill, destination, symlinks=True)
            else:
                relative_target = os.path.relpath(stored_skill, destination.parent)
                os.symlink(relative_target, destination, target_is_directory=True)
            created.append(destination)
        return created, mode
    except Exception:
        for path in reversed(created):
            _remove_created_path(path)
        raise


def _remove_created_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyError(f"could not read JSON state {path}: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SafetyError(f"JSON state must be an object: {path}")
    return data


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
