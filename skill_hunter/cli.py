from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .analyzer import analyze_repository
from .discovery import index_repository
from .installer import LINK_MODES, SCOPES, TARGETS, execute_install, make_install_plan
from .models import (
    AnalysisError,
    AnalysisResult,
    CollisionError,
    Confidence,
    SafetyError,
    SkillHunterError,
    SourceError,
)
from .source import acquire_repository, parse_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-hunter",
        description="Discover and safely import Agent Skills with repository-local dependencies.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command, help_text in (
        ("inspect", "inspect a repository and its Agent Skill candidates"),
        ("list", "list Agent Skills found anywhere in a repository"),
    ):
        subparser = subparsers.add_parser(command, help=help_text)
        _add_source_arguments(subparser)

    analyze = subparsers.add_parser("analyze", help="build a dependency and risk graph")
    _add_source_arguments(analyze)
    _add_selection_arguments(analyze)

    install = subparsers.add_parser("install", help="analyze and install a minimal dependency closure")
    _add_source_arguments(install)
    _add_selection_arguments(install)
    install.add_argument("--target", choices=TARGETS, default="auto", help="agent destination adapter")
    install.add_argument("--scope", choices=SCOPES, default="project", help="project or global installation")
    install.add_argument("--destination", help="explicit skill directory for --target custom")
    install.add_argument("--project-root", default=".", help="project root for project scope and state")
    install.add_argument("--state-dir", help="explicit provenance/content-store directory")
    install.add_argument("--link-mode", choices=LINK_MODES, default="auto")
    install.add_argument("--dry-run", action="store_true", help="show the exact plan without writing files")
    install.add_argument("--yes", action="store_true", help="confirm the reviewed plan non-interactively")
    return parser


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="GitHub repository URL or local fixture directory")
    parser.add_argument("--ref", help="branch, tag, or 40-character commit to analyze")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--skill", action="append", dest="skills", help="skill name; repeat to select several")
    selection.add_argument("--all", action="store_true", help="select every valid, uniquely named skill")
    parser.add_argument(
        "--include-inferred",
        action="store_true",
        help="include high-confidence natural-language skill dependencies after review",
    )
    parser.add_argument(
        "--include-possible",
        action="store_true",
        help="also include ambiguous skill mentions; never enabled by default",
    )


def _selected_skills(arguments: argparse.Namespace, index: Any) -> list[str]:
    if arguments.all:
        selected = [name for name, skill in sorted(index.skills.items()) if skill.installable]
        if not selected:
            raise AnalysisError("repository contains no installable skills")
        return selected
    return arguments.skills or []


def _safe(value: object) -> str:
    text = str(value)
    return "".join(char for char in text if char in "\n\t" or ord(char) >= 32).replace("\x1b", "")


def _short(value: str, width: int) -> str:
    clean = " ".join(_safe(value).split())
    return clean if len(clean) <= width else clean[: width - 1] + "…"


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def render_repository(index: Any, method: str, *, verbose: bool) -> None:
    print(f"Repository: {_safe(index.source_url)}")
    print(f"Revision:   {_safe(index.revision)}")
    print(f"Acquired:   {_safe(method)}")
    print(f"Skills:     {len(index.skills)}")
    print()
    if index.skills:
        print(f"{'NAME':24} {'PATH':38} {'DEPS':18} {'STATUS':12} DESCRIPTION")
        print(f"{'-' * 24} {'-' * 38} {'-' * 18} {'-' * 12} {'-' * 36}")
        for name, skill in sorted(index.skills.items()):
            dependencies = ",".join(skill.explicit_dependencies) or "-"
            status = "installable" if skill.installable else "blocked"
            print(
                f"{_short(name, 24):24} {_short(skill.path, 38):38} "
                f"{_short(dependencies, 18):18} {status:12} {_short(skill.description, 64)}"
            )
            if verbose:
                for warning in skill.warnings:
                    print(f"  warning: {_safe(warning)}")
    if index.warnings:
        print("\nRepository warnings:")
        for warning in index.warnings:
            print(f"  - {_safe(warning)}")


def render_analysis(analysis: AnalysisResult) -> None:
    print(f"Source:      {_safe(analysis.source_url)}")
    print(f"Revision:    {_safe(analysis.revision)}")
    print(f"Requested:   {', '.join(map(_safe, analysis.requested_skills))}")
    print(f"Install set: {', '.join(map(_safe, analysis.installed_skills))}")
    print(f"Closure:     {len(analysis.included_paths)} entries, {_format_bytes(analysis.total_bytes)}")
    print(f"Risk:        {analysis.risk.upper()}")

    labels = (
        (Confidence.CONFIRMED, "Confirmed dependencies"),
        (Confidence.INFERRED, "Inferred dependencies (review before inclusion)"),
        (Confidence.POSSIBLE, "Possible dependencies (excluded by default)"),
    )
    for confidence, label in labels:
        edges = analysis.edges_by_confidence(confidence)
        if not edges:
            continue
        print(f"\n{label}:")
        for edge in edges:
            print(
                f"  - {_safe(edge.source)} -> {_safe(edge.target)} "
                f"[{edge.kind}; {_safe(edge.location)}] {_short(edge.evidence, 100)}"
            )
    if analysis.cycles:
        print("\nDependency cycles (deduplicated):")
        for cycle in analysis.cycles:
            print("  - " + " -> ".join(map(_safe, cycle)))
    if analysis.scripts:
        print("\nScripts (not executed):")
        for script in analysis.scripts:
            print(f"  - {_safe(script)}")
    if analysis.symlinks:
        print("\nSymlinks:")
        for link in analysis.symlinks:
            print(f"  - {_safe(link['path'])} -> {_safe(link['target'])}")
    if analysis.signals:
        print("\nStatic security signals:")
        for signal in analysis.signals:
            location = f"{signal.path}:{signal.line}" if signal.line else signal.path
            print(f"  - {signal.severity.upper()} {_safe(location)}: {_safe(signal.message)}")
    if analysis.warnings:
        print("\nWarnings:")
        for warning in analysis.warnings:
            print(f"  - {_safe(warning)}")
    if analysis.blockers:
        print("\nInstall blockers:")
        for blocker in analysis.blockers:
            print(f"  - {_safe(blocker)}")


def render_install_plan(plan: Any) -> None:
    print("\nInstall plan:")
    print(f"  Destination: {_safe(plan.destination)}")
    print(f"  State:       {_safe(plan.state_root)}")
    print(f"  Store:       {_safe(plan.store)}")
    print(f"  Adapter:     {plan.target} ({plan.scope})")
    print(f"  Link mode:   {plan.link_mode}" + (" (copy fallback is safe)" if plan.copy_safe else ""))
    if plan.conflicts:
        print("  Conflicts:")
        for conflict in plan.conflicts:
            print(f"    - {_safe(conflict['skill'])}: {_safe(conflict['path'])} — {_safe(conflict['detail'])}")
    else:
        print("  Conflicts:   none")


def _json_dump(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def run(arguments: argparse.Namespace) -> int:
    source = parse_source(arguments.source, arguments.ref)
    with acquire_repository(source) as acquired:
        index = index_repository(acquired.root, source.canonical_url, acquired.revision)
        for warning in acquired.warnings:
            if warning not in index.warnings:
                index.warnings.append(warning)

        if arguments.command in {"inspect", "list"}:
            if arguments.json:
                payload = index.public_dict()
                payload["acquisition"] = acquired.method
                _json_dump(payload)
            else:
                render_repository(index, acquired.method, verbose=arguments.command == "inspect")
            return 0 if index.skills else 2

        selected = _selected_skills(arguments, index)
        analysis = analyze_repository(
            index,
            selected,
            include_inferred=arguments.include_inferred,
            include_possible=arguments.include_possible,
        )
        if arguments.command == "analyze":
            if arguments.json:
                _json_dump({"acquisition": acquired.method, "analysis": analysis.public_dict()})
            else:
                render_analysis(analysis)
            return 3 if analysis.blockers else 0

        project_root = Path(arguments.project_root).expanduser().resolve()
        plan = make_install_plan(
            index,
            analysis,
            target=arguments.target,
            scope=arguments.scope,
            project_root=project_root,
            destination=arguments.destination,
            state_dir=arguments.state_dir,
            link_mode=arguments.link_mode,
        )
        if arguments.json and arguments.dry_run:
            _json_dump(
                {
                    "dry_run": True,
                    "acquisition": acquired.method,
                    "analysis": analysis.public_dict(),
                    "install_plan": plan.public_dict(),
                }
            )
        elif not arguments.json:
            render_analysis(analysis)
            render_install_plan(plan)

        if arguments.dry_run:
            if analysis.blockers:
                return 3
            if plan.conflicts:
                return 4
            return 0
        if analysis.blockers:
            raise SafetyError("install plan contains blockers; no files were changed")
        if plan.conflicts:
            raise CollisionError("install plan contains destination conflicts; no files were changed")
        if not arguments.yes:
            if not sys.stdin.isatty():
                raise SafetyError("non-interactive installation requires --yes after reviewing a dry-run")
            answer = input("Proceed with this reviewed plan? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Cancelled; no files were changed.")
                return 1
        result = execute_install(index, analysis, plan)
        if arguments.json:
            _json_dump({"analysis": analysis.public_dict(), "install_plan": plan.public_dict(), "result": result})
        else:
            print("\nInstalled successfully:")
            for path in result["installed"]:
                print(f"  - {_safe(path)}")
            print(f"Provenance store: {_safe(result['store'])}")
            print(f"Registry:         {_safe(result['registry'])}")
            print(f"Pinned revision:  {_safe(result['revision'])}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return run(arguments)
    except CollisionError as exc:
        print(f"error: {_safe(exc)}", file=sys.stderr)
        return 4
    except SourceError as exc:
        print(f"error: {_safe(exc)}", file=sys.stderr)
        return 5
    except (AnalysisError, SafetyError, SkillHunterError) as exc:
        print(f"error: {_safe(exc)}", file=sys.stderr)
        return 3 if isinstance(exc, SafetyError) else 2
    except OSError as exc:
        print(f"error: filesystem operation failed safely ({type(exc).__name__}): {_safe(exc)}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("error: interrupted; no source script was executed", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
