from __future__ import annotations

import ast
import errno
import os
import re
import stat
from collections import defaultdict, deque
from pathlib import Path

from .models import (
    AnalysisError,
    AnalysisResult,
    Confidence,
    DependencyEdge,
    RepositoryIndex,
    SecuritySignal,
)


_TEXT_LIMIT = 2 * 1024 * 1024
_SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".ps1", ".rb", ".pl"}
_RELATIVE_PATH = re.compile(
    r"(?<![A-Za-z0-9_:/])(?P<path>(?:\.\.?/)+(?:[A-Za-z0-9_@%+=,~.-]+/)*[A-Za-z0-9_@%+=,~.-]+)"
)
_BARE_RESOURCE_PATH = re.compile(
    r"(?<![A-Za-z0-9_:/])(?P<path>(?:scripts|references|assets|templates|prompts|schemas|rules|examples)/"
    r"(?:[A-Za-z0-9_@%+=,~.-]+/)*[A-Za-z0-9_@%+=,~.-]+)"
)
_NODE_IMPORT = re.compile(
    r"(?:require\s*\(|import\s*\(|\bfrom\s+|^\s*import\s+)[\s]*['\"](?P<path>\.{1,2}/[^'\"]+)['\"]",
    re.MULTILINE,
)
_SHELL_PATH = re.compile(
    r"^\s*(?:source|\.|bash|sh|zsh|python3?|node)\s+(?:--\s+)?(?P<path>['\"]?\.{1,2}/[^\s'\";|&]+)",
    re.MULTILINE,
)


def _within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _node(kind: str, value: str) -> str:
    return f"{kind}:{value}"


class RepositoryAnalyzer:
    def __init__(
        self,
        index: RepositoryIndex,
        *,
        include_inferred: bool = False,
        include_possible: bool = False,
    ) -> None:
        self.index = index
        self.root = index.root.resolve()
        self.include_inferred = include_inferred or include_possible
        self.include_possible = include_possible
        self._included: set[str] = set()
        self._file_queue: deque[str] = deque()
        self._scanned_files: set[str] = set()
        self._skills: list[str] = []
        self._skill_set: set[str] = set()
        self._edges: list[DependencyEdge] = []
        self._edge_keys: set[tuple[str, str, str, str, str]] = set()
        self._warnings: list[str] = list(index.warnings)
        self._warning_set: set[str] = set(index.warnings)
        self._blockers: list[str] = []
        self._blocker_set: set[str] = set()
        self._signals: list[SecuritySignal] = []
        self._signal_keys: set[tuple[str, str, str, int | None]] = set()
        self._symlinks: list[dict[str, str]] = []
        self._symlink_paths: set[str] = set()
        self._scripts: set[str] = set()
        self._total_bytes = 0
        self._ignored_references: set[tuple[str, str]] = set()
        self._skill_by_file = {skill.skill_file: name for name, skill in index.skills.items()}

    def analyze(self, requested_skills: list[str]) -> AnalysisResult:
        if not requested_skills:
            raise AnalysisError("select at least one skill")
        requested: list[str] = []
        for name in requested_skills:
            if name not in requested:
                requested.append(name)
            info = self.index.skills.get(name)
            if info is None:
                raise AnalysisError(f"skill not found: {name}")
            if not info.installable:
                details = "; ".join(info.warnings) or "invalid skill metadata"
                raise AnalysisError(f"skill {name!r} is not installable: {details}")

        for name in requested:
            self._add_skill(name)
        while self._file_queue:
            relative = self._file_queue.popleft()
            if relative in self._scanned_files:
                continue
            self._scanned_files.add(relative)
            self._scan_file(relative)

        cycles = self._detect_skill_cycles()
        risk = self._risk_level()
        return AnalysisResult(
            source_url=self.index.source_url,
            revision=self.index.revision,
            requested_skills=requested,
            installed_skills=list(self._skills),
            included_paths=sorted(self._included),
            edges=sorted(
                self._edges,
                key=lambda edge: (edge.source, edge.target, edge.confidence.value, edge.kind, edge.location),
            ),
            cycles=cycles,
            scripts=sorted(self._scripts),
            symlinks=sorted(self._symlinks, key=lambda item: item["path"]),
            signals=sorted(self._signals, key=lambda item: (item.severity, item.path, item.line or 0, item.kind)),
            warnings=self._warnings,
            blockers=self._blockers,
            risk=risk,
            total_bytes=self._total_bytes,
        )

    def _add_skill(self, name: str) -> None:
        if name in self._skill_set:
            return
        info = self.index.skills.get(name)
        if info is None:
            self._block(f"required skill {name!r} is not present in this repository")
            return
        if not info.installable:
            self._block(f"required skill {name!r} is not installable: {'; '.join(info.warnings)}")
            return
        self._skill_set.add(name)
        self._skills.append(name)
        if info.path == ".":
            self._include_path(info.skill_file)
            if (self.root / "agents" / "openai.yaml").is_file():
                self._include_path("agents/openai.yaml")
        else:
            self._include_path(info.path)

        license_value = info.frontmatter.get("license")
        if isinstance(license_value, str):
            license_target = self._resolve_file_reference(info.skill_file, license_value, allow_bare=True)
            if license_target:
                self._record_file_dependency(
                    _node("skill", name),
                    info.skill_file,
                    license_target,
                    "metadata-file",
                    f"license metadata {license_value}",
                )

        for dependency in info.explicit_dependencies:
            declaration = info.dependency_sources.get(dependency, f"{info.skill_file} frontmatter")
            declaration_path = declaration.split(" ", 1)[0]
            if declaration_path != info.skill_file and (self.root / declaration_path).is_file():
                self._include_path(declaration_path)
            edge = DependencyEdge(
                source=_node("skill", name),
                target=_node("skill", dependency),
                kind="explicit-skill",
                confidence=Confidence.CONFIRMED,
                evidence=f"declared dependency {dependency!r} in {declaration}",
                location=declaration_path,
            )
            self._add_edge(edge)
            if dependency not in self.index.skills:
                self._block(f"{name!r} requires missing repository-local skill {dependency!r}")
            else:
                self._add_skill(dependency)

    def _include_path(self, relative: str) -> None:
        relative = relative.replace("\\", "/").strip("/") or "."
        path = self.root if relative == "." else self.root.joinpath(*relative.split("/"))
        try:
            info = path.lstat()
        except OSError as exc:
            self._warn(f"referenced path is unreadable: {relative} ({type(exc).__name__})")
            return
        if stat.S_ISLNK(info.st_mode):
            self._include_symlink(relative, path)
            return
        if stat.S_ISDIR(info.st_mode):
            try:
                children = sorted(path.iterdir(), key=lambda item: item.name)
            except OSError as exc:
                self._block(f"could not enumerate dependency directory {relative}: {type(exc).__name__}")
                return
            for child in children:
                if child.name == ".git":
                    continue
                child_relative = child.relative_to(self.root).as_posix()
                self._include_path(child_relative)
            return
        if not stat.S_ISREG(info.st_mode):
            self._block(f"unsupported special file in dependency closure: {relative}")
            return
        if relative in self._included:
            return
        self._included.add(relative)
        self._total_bytes += info.st_size
        self._file_queue.append(relative)
        if path.suffix.lower() in _SCRIPT_SUFFIXES or info.st_mode & 0o111:
            self._scripts.add(relative)
        if info.st_mode & 0o111:
            self._signal("medium", "executable", relative, "file has an executable mode bit")

    def _include_symlink(self, relative: str, path: Path) -> None:
        if relative not in self._included:
            self._included.add(relative)
        try:
            target_text = os.readlink(path)
        except OSError as exc:
            self._block(f"could not read symlink {relative}: {type(exc).__name__}")
            return
        if relative not in self._symlink_paths:
            self._symlink_paths.add(relative)
            self._symlinks.append({"path": relative, "target": target_text})
        if os.path.isabs(target_text):
            self._block(f"absolute symlink is not allowed: {relative} -> {target_text}")
            return
        try:
            target = path.resolve(strict=True)
        except RuntimeError:
            self._block(f"circular symlink is not allowed: {relative} -> {target_text}")
            return
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                self._block(f"circular symlink is not allowed: {relative} -> {target_text}")
            else:
                self._block(f"broken symlink is not allowed: {relative} -> {target_text}")
            return
        if not _within(self.root, target):
            self._block(f"repository-external symlink is not allowed: {relative} -> {target_text}")
            return
        target_relative = target.relative_to(self.root).as_posix()
        self._add_edge(
            DependencyEdge(
                source=_node("file", relative),
                target=_node("file", target_relative),
                kind="symlink",
                confidence=Confidence.CONFIRMED,
                evidence=f"symlink target {target_text}",
                location=relative,
            )
        )
        self._include_path(target_relative)

    def _scan_file(self, relative: str) -> None:
        path = self.root.joinpath(*relative.split("/"))
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size > _TEXT_LIMIT:
            self._warn(f"skipped static text analysis for large file: {relative} ({size} bytes)")
            return
        try:
            raw = path.read_bytes()
        except OSError as exc:
            self._warn(f"could not read dependency file {relative}: {type(exc).__name__}")
            return
        if b"\x00" in raw:
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return

        self._scan_security(relative, text)
        source_node = self._source_node(relative)
        self._scan_relative_paths(relative, text, source_node)
        suffix = path.suffix.lower()
        if suffix == ".py":
            self._scan_python_imports(relative, text, source_node)
        if suffix in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
            self._scan_node_imports(relative, text, source_node)
        if suffix in {".sh", ".bash", ".zsh"} or text.startswith("#!"):
            self._scan_shell_dependencies(relative, text, source_node)
        skill_name = self._skill_by_file.get(relative)
        if skill_name:
            self._scan_semantic_skill_references(skill_name, relative, text)

    def _source_node(self, relative: str) -> str:
        skill = self._skill_by_file.get(relative)
        return _node("skill", skill) if skill else _node("file", relative)

    def _scan_relative_paths(self, relative: str, text: str, source_node: str) -> None:
        seen: set[str] = set()
        candidates = [(match.group("path"), False) for match in _RELATIVE_PATH.finditer(text)]
        candidates.extend((match.group("path"), True) for match in _BARE_RESOURCE_PATH.finditer(text))
        for candidate, allow_bare in candidates:
            raw = candidate.rstrip(".,:;)]}")
            if raw in seen:
                continue
            seen.add(raw)
            target = self._resolve_file_reference(relative, raw, allow_bare=allow_bare)
            if target is None:
                if (relative, raw) not in self._ignored_references and (Path(raw).suffix or "SKILL.md" in raw):
                    self._warn(f"unresolved relative reference in {relative}: {raw}")
                continue
            self._record_file_dependency(source_node, relative, target, "relative-path", raw)

    def _scan_python_imports(self, relative: str, text: str, source_node: str) -> None:
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            self._warn(f"could not parse Python syntax for dependency analysis: {relative}")
            return
        for statement in ast.walk(tree):
            candidates: list[tuple[str, int, list[str]]] = []
            if isinstance(statement, ast.Import):
                candidates.extend((alias.name, 0, []) for alias in statement.names)
            elif isinstance(statement, ast.ImportFrom):
                imported = [alias.name for alias in statement.names if alias.name != "*"]
                candidates.append((statement.module or "", statement.level, imported))
            for module, level, imported in candidates:
                targets = self._resolve_python_module(relative, module, level, imported)
                for target in targets:
                    self._record_file_dependency(
                        source_node,
                        relative,
                        target,
                        "python-import",
                        f"Python import {'.' * level}{module}",
                    )

    def _resolve_python_module(self, source: str, module: str, level: int, imported: list[str]) -> list[str]:
        source_parent = self.root.joinpath(*source.split("/")).parent
        module_parts = [part for part in module.split(".") if part]
        roots: list[Path] = []
        if level:
            base = source_parent
            for _ in range(max(0, level - 1)):
                base = base.parent
            roots.append(base)
        else:
            roots.extend([source_parent, self.root])

        found: list[Path] = []
        for base in roots:
            candidate_base = base.joinpath(*module_parts) if module_parts else base
            candidates = [candidate_base.with_suffix(".py"), candidate_base / "__init__.py"]
            for candidate in candidates:
                if candidate.is_file() and _within(self.root, candidate.resolve()):
                    found.append(candidate)
                    break
            if found:
                if candidate_base.is_dir():
                    for imported_name in imported:
                        imported_file = candidate_base / f"{imported_name}.py"
                        imported_package = candidate_base / imported_name / "__init__.py"
                        if imported_file.is_file():
                            found.append(imported_file)
                        elif imported_package.is_file():
                            found.append(imported_package)
                break
        unique: list[str] = []
        for target in found:
            relative = target.relative_to(self.root).as_posix()
            if relative not in unique:
                unique.append(relative)
        return unique

    def _scan_node_imports(self, relative: str, text: str, source_node: str) -> None:
        for match in _NODE_IMPORT.finditer(text):
            raw = match.group("path")
            target = self._resolve_file_reference(relative, raw, extensions=(".js", ".mjs", ".cjs", ".ts", ".tsx", ".json"))
            if target:
                self._record_file_dependency(source_node, relative, target, "node-import", raw)

    def _scan_shell_dependencies(self, relative: str, text: str, source_node: str) -> None:
        for match in _SHELL_PATH.finditer(text):
            raw = match.group("path").strip("'\"")
            target = self._resolve_file_reference(relative, raw)
            if target:
                self._record_file_dependency(source_node, relative, target, "shell-source", raw)

    def _scan_semantic_skill_references(self, skill_name: str, relative: str, text: str) -> None:
        for line_number, line in enumerate(text.splitlines(), 1):
            lowered = line.lower()
            if "skill" not in lowered:
                continue
            for candidate in sorted(self.index.skills):
                if candidate == skill_name:
                    continue
                if not re.search(rf"(?<![a-z0-9-])`?{re.escape(candidate.lower())}`?(?![a-z0-9-])", lowered):
                    continue
                illustrative = bool(re.search(r"\b(example|for example|e\.g\.|compare|unlike|optional|do not|don't|avoid)\b", lowered))
                imperative = bool(
                    re.search(r"\b(use|invoke|run|load|apply|call|read|activate)\b", lowered)
                    and re.search(r"\b(must|required|before|first|then|after|use|invoke|run|load|apply|call|read|activate)\b", lowered)
                )
                confidence = Confidence.POSSIBLE if illustrative or not imperative else Confidence.INFERRED
                edge = DependencyEdge(
                    source=_node("skill", skill_name),
                    target=_node("skill", candidate),
                    kind="semantic-skill",
                    confidence=confidence,
                    evidence=line.strip()[:240],
                    location=f"{relative}:{line_number}",
                )
                self._add_edge(edge)
                if confidence == Confidence.INFERRED and self.include_inferred:
                    self._add_skill(candidate)
                elif confidence == Confidence.POSSIBLE and self.include_possible:
                    self._add_skill(candidate)

    def _resolve_file_reference(
        self,
        source_relative: str,
        raw: str,
        *,
        extensions: tuple[str, ...] = (),
        allow_bare: bool = False,
    ) -> str | None:
        raw = raw.strip().strip("'\"")
        raw = raw.split("#", 1)[0]
        raw = re.sub(r":\d+(?::\d+)?$", "", raw)
        if not raw or (not allow_bare and not raw.startswith(("./", "../"))):
            return None
        if allow_bare and (raw.startswith("/") or "://" in raw):
            return None
        if any(token in raw for token in ("$", "{", "}", "*", "?", "\x00")):
            return None
        source_path = self.root.joinpath(*source_relative.split("/"))
        lexical = Path(os.path.abspath(source_path.parent / raw))
        if not _within(self.root, lexical):
            self._ignored_references.add((source_relative, raw))
            self._signal(
                "high",
                "path-escape-reference",
                source_relative,
                f"references a path outside the repository: {raw}",
            )
            self._warn(f"ignored repository-external relative reference in {source_relative}: {raw}")
            return None

        candidates = [lexical]
        if extensions and not lexical.suffix:
            candidates.extend(Path(f"{lexical}{extension}") for extension in extensions)
            candidates.extend(lexical / f"index{extension}" for extension in extensions)
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            self._include_symlink_components(candidate)
            if not _within(self.root, resolved):
                self._ignored_references.add((source_relative, raw))
                self._signal(
                    "high",
                    "path-escape-reference",
                    source_relative,
                    f"traverses a symlink outside the repository: {raw}",
                )
                return None
            return resolved.relative_to(self.root).as_posix()
        return None

    def _include_symlink_components(self, path: Path) -> None:
        current = self.root
        for part in path.relative_to(self.root).parts:
            current = current / part
            if current.is_symlink():
                self._include_path(current.relative_to(self.root).as_posix())

    def _record_file_dependency(
        self,
        source_node: str,
        source_relative: str,
        target_relative: str,
        kind: str,
        evidence: str,
    ) -> None:
        skill_target = self._skill_by_file.get(target_relative)
        target_node = _node("skill", skill_target) if skill_target else _node("file", target_relative)
        self._add_edge(
            DependencyEdge(
                source=source_node,
                target=target_node,
                kind=kind,
                confidence=Confidence.CONFIRMED,
                evidence=evidence,
                location=source_relative,
            )
        )
        if skill_target:
            self._add_skill(skill_target)
        else:
            self._include_path(target_relative)

    def _scan_security(self, relative: str, text: str) -> None:
        patterns = [
            ("high", "pipe-to-shell", r"\b(?:curl|wget)\b[^\n|]{0,300}\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b", "downloads content and pipes it to a shell"),
            ("high", "destructive-command", r"\brm\s+-[^\n]*r[^\n]*f|\bshutil\.rmtree\s*\(", "contains a recursive destructive operation"),
            ("medium", "network-execution", r"\b(?:curl|wget)\b|\brequests\.(?:get|post)\b|\bfetch\s*\(", "contains executable network access"),
            ("low", "external-url", r"https?://", "references an external URL"),
            ("medium", "process-execution", r"\bsubprocess\.(?:run|Popen|call)\b|\bos\.system\s*\(|\bchild_process\b", "starts a local process"),
            ("medium", "credential-access", r"\b(?:GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY)\b|(?:^|[/'\"])\.ssh(?:[/\"]|$)", "references credentials or credential storage"),
            ("medium", "absolute-write", r"\b(?:open|write_text|write_bytes)\s*\(\s*['\"]/(?:etc|usr|var|opt)/", "may write to an absolute system path"),
        ]
        if any(part.lower() in {"hooks", ".git-hooks", "githooks"} for part in Path(relative).parts):
            self._signal("medium", "hook", relative, "file is located in a hook directory")
        for severity, kind, pattern, message in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                self._signal(severity, kind, relative, message, line)

    def _add_edge(self, edge: DependencyEdge) -> None:
        key = (edge.source, edge.target, edge.kind, edge.confidence.value, edge.location)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self._edges.append(edge)

    def _warn(self, message: str) -> None:
        if message not in self._warning_set:
            self._warning_set.add(message)
            self._warnings.append(message)

    def _block(self, message: str) -> None:
        if message not in self._blocker_set:
            self._blocker_set.add(message)
            self._blockers.append(message)

    def _signal(self, severity: str, kind: str, path: str, message: str, line: int | None = None) -> None:
        key = (severity, kind, path, line)
        if key not in self._signal_keys:
            self._signal_keys.add(key)
            self._signals.append(SecuritySignal(severity, kind, path, message, line))

    def _detect_skill_cycles(self) -> list[list[str]]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in self._edges:
            if not edge.source.startswith("skill:") or not edge.target.startswith("skill:"):
                continue
            included = edge.confidence == Confidence.CONFIRMED
            included = included or (edge.confidence == Confidence.INFERRED and self.include_inferred)
            included = included or (edge.confidence == Confidence.POSSIBLE and self.include_possible)
            if included:
                adjacency[edge.source[6:]].add(edge.target[6:])

        state: dict[str, int] = {}
        stack: list[str] = []
        cycles: list[list[str]] = []
        canonical_cycles: set[tuple[str, ...]] = set()

        def visit(name: str) -> None:
            state[name] = 1
            stack.append(name)
            for dependency in sorted(adjacency.get(name, ())):
                if state.get(dependency, 0) == 0:
                    visit(dependency)
                elif state.get(dependency) == 1:
                    start = stack.index(dependency)
                    cycle = stack[start:] + [dependency]
                    core = cycle[:-1]
                    rotations = [tuple(core[index:] + core[:index]) for index in range(len(core))]
                    canonical = min(rotations) if rotations else tuple()
                    if canonical not in canonical_cycles:
                        canonical_cycles.add(canonical)
                        cycles.append(cycle)
            stack.pop()
            state[name] = 2

        for skill in sorted(self._skill_set):
            if state.get(skill, 0) == 0:
                visit(skill)
        return cycles

    def _risk_level(self) -> str:
        if self._blockers or any(signal.severity == "high" for signal in self._signals):
            return "high"
        if self._scripts or self._symlinks or any(signal.severity == "medium" for signal in self._signals):
            return "medium"
        if any(edge.confidence != Confidence.CONFIRMED for edge in self._edges):
            return "medium"
        return "low"


def analyze_repository(
    index: RepositoryIndex,
    requested_skills: list[str],
    *,
    include_inferred: bool = False,
    include_possible: bool = False,
) -> AnalysisResult:
    return RepositoryAnalyzer(
        index,
        include_inferred=include_inferred,
        include_possible=include_possible,
    ).analyze(requested_skills)
