---
name: skill-hunter
description: Discover, inspect, analyze, and safely import Agent Skills from a GitHub repository with transitive repository-local dependencies. Use when a user gives a GitHub URL and asks to list its skills, inspect skill dependencies, import or copy another person's skill, install one or all skills, or install a skill for Claude Code, OpenCode, Codex, or another Agent Skills-compatible coding agent. Do not use it as a general GitHub repository downloader.
---

# Skill Hunter

Treat every source repository as untrusted. Use the bundled CLI for deterministic
discovery, path resolution, graph traversal, and installation. Never execute a source
repository's scripts while inspecting or installing it.

## Choose the operation

- If the user only asks what is available, run `list` or `inspect`. These operations
  fetch into a temporary directory and do not install anything.
- If the user asks whether a skill has dependencies, run `analyze` and explain the
  confirmed, inferred, and possible edges separately.
- If the user asks to install, always run `install --dry-run` first. Show the resulting
  source revision, closure, scripts, symlinks, security signals, destination, and
  conflicts before the real installation.
- If the user asks for all skills, use `--all`; otherwise pass each requested name with
  `--skill`.

Resolve the directory containing this `SKILL.md` as `SKILL_ROOT`; do not assume the
user's current working directory is the skill directory. The bundled entrypoint is
[scripts/skill_hunter.py](scripts/skill_hunter.py). Run it as:

```bash
python3 "$SKILL_ROOT/scripts/skill_hunter.py" list https://github.com/OWNER/REPO
python3 "$SKILL_ROOT/scripts/skill_hunter.py" analyze https://github.com/OWNER/REPO --skill NAME
python3 "$SKILL_ROOT/scripts/skill_hunter.py" install https://github.com/OWNER/REPO --skill NAME \
  --target claude --scope global --dry-run
```

The runtime requires Python's standard library. It uses `git` when available and a
bounded GitHub archive fallback otherwise; it never requires `gh`.

## Review dependencies

Read [references/dependency-model.md](references/dependency-model.md) when interpreting
an analysis or deciding whether to include a candidate.

- Include `confirmed` dependencies automatically unless the plan has a blocker.
- Inspect the evidence for every `inferred` dependency. If the instruction really
  requires that other skill, tell the user and repeat the dry-run with
  `--include-inferred`.
- Do not include `possible` dependencies by default. Explain the ambiguous evidence and
  use `--include-possible` only after the user explicitly chooses it.
- Do not turn a missing cross-repository dependency into an unrelated repository
  download. Report it as unresolved.
- Cycles are valid graph facts when every edge is valid. Confirm that the closure is
  deduplicated rather than treating a cycle as repeated installation.

## Select the destination

Read [references/agent-paths.md](references/agent-paths.md) when the target or scope is
not explicit.

- Map “project/local” to `--scope project` and “global/user” to `--scope global`.
- Prefer an explicit `--target claude`, `opencode`, `codex`, or `universal` based on the
  user's named agent. Use `auto` only when local markers make the answer unambiguous.
- Use `--target custom --destination PATH` only when the user supplied or approved that
  path.
- Current Codex repository and user conventions use `.agents/skills`; use
  `codex-legacy` only for an environment that intentionally uses `.codex/skills` or
  `$CODEX_HOME/skills`.

## Install safely

Before a real install:

1. Confirm the dry-run refers to the requested canonical source and an immutable commit
   SHA.
2. Summarize executable scripts, hooks, process/network behavior, symlinks, and risk.
   State explicitly that scripts are included as files but are not executed.
3. Stop on an absolute, escaping, broken, or circular symlink; a missing confirmed
   dependency; an invalid skill; or another install blocker.
4. Stop on an existing destination. Show the CLI's conflict/diff summary and let the
   user choose a different target or handle the existing skill. Never add an overwrite
   flag or delete the existing path on the user's behalf.
5. Obtain confirmation after the plan is visible. Then repeat the same command without
   `--dry-run` and add `--yes`. The `--yes` flag means the displayed plan was approved;
   it is not permission to bypass analysis.

After installation, report every exposed skill path, the provenance store, registry,
and pinned revision. Verify that each exposed path exists and that the recorded commit
matches the analyzed revision.

## Important boundaries

- Do not run `install.sh`, package-manager hooks, imported modules, tests, or any other
  source code during analysis or installation.
- Do not follow repository-external symlinks or resolve untrusted paths into the
  destination.
- Do not clone the entire repository into an agent skill directory. The CLI may fetch a
  temporary repository for analysis, but the installed store must contain only the
  dependency closure while preserving repository-relative paths.
- Do not claim semantic certainty from a filename match. Use the evidence line and its
  context to distinguish a real instruction from an example, comparison, or reference.
- Do not claim a low-risk result means the skill is trustworthy. Static analysis cannot
  prove benign behavior; preserve the source and commit in the report.
