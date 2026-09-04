from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    POSSIBLE = "possible"


@dataclass(frozen=True)
class SourceSpec:
    original: str
    kind: str
    canonical_url: str
    owner: str | None = None
    repo: str | None = None
    ref: str | None = None
    subpath: str | None = None
    local_path: Path | None = None


@dataclass
class AcquiredRepository:
    root: Path
    source: SourceSpec
    revision: str
    method: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class SkillInfo:
    name: str
    path: str
    description: str
    frontmatter: dict[str, Any]
    body: str
    explicit_dependencies: list[str] = field(default_factory=list)
    dependency_sources: dict[str, str] = field(default_factory=dict)
    installable: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def skill_file(self) -> str:
        return f"{self.path}/SKILL.md" if self.path != "." else "SKILL.md"

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "frontmatter": self.frontmatter,
            "dependencies": self.explicit_dependencies,
            "dependency_sources": self.dependency_sources,
            "installable": self.installable,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str
    kind: str
    confidence: Confidence
    evidence: str
    location: str

    def public_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["confidence"] = self.confidence.value
        return data


@dataclass(frozen=True)
class SecuritySignal:
    severity: str
    kind: str
    path: str
    message: str
    line: int | None = None


@dataclass
class RepositoryIndex:
    root: Path
    source_url: str
    revision: str
    skills: dict[str, SkillInfo]
    warnings: list[str] = field(default_factory=list)
    duplicate_names: dict[str, list[str]] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_url,
            "revision": self.revision,
            "skills": [self.skills[name].public_dict() for name in sorted(self.skills)],
            "duplicates": self.duplicate_names,
            "warnings": self.warnings,
        }


@dataclass
class AnalysisResult:
    source_url: str
    revision: str
    requested_skills: list[str]
    installed_skills: list[str]
    included_paths: list[str]
    edges: list[DependencyEdge]
    cycles: list[list[str]]
    scripts: list[str]
    symlinks: list[dict[str, str]]
    signals: list[SecuritySignal]
    warnings: list[str]
    blockers: list[str]
    risk: str
    total_bytes: int

    def edges_by_confidence(self, confidence: Confidence) -> list[DependencyEdge]:
        return [edge for edge in self.edges if edge.confidence == confidence]

    def public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_url,
            "revision": self.revision,
            "requested_skills": self.requested_skills,
            "installed_skills": self.installed_skills,
            "included_paths": self.included_paths,
            "dependencies": [edge.public_dict() for edge in self.edges],
            "cycles": self.cycles,
            "scripts": self.scripts,
            "symlinks": self.symlinks,
            "security_signals": [asdict(signal) for signal in self.signals],
            "warnings": self.warnings,
            "blockers": self.blockers,
            "risk": self.risk,
            "file_count": len(self.included_paths),
            "total_bytes": self.total_bytes,
        }


class SkillHunterError(RuntimeError):
    """Base exception for expected user-facing failures."""


class SourceError(SkillHunterError):
    pass


class AnalysisError(SkillHunterError):
    pass


class SafetyError(SkillHunterError):
    pass


class CollisionError(SkillHunterError):
    pass
