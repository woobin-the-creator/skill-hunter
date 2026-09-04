# skill-hunter design

Status: accepted for implementation
Date: 2026-09-04

## Problem statement

Agent Skill installers normally copy a directory containing `SKILL.md`. That is
insufficient when a skill depends on sibling skills, repository-level templates,
shared libraries, scripts outside the skill directory, or symbolic links. The
installed skill can look valid while failing at runtime because its repository-local
paths no longer resolve.

`skill-hunter` is a dependency-aware importer. Given a GitHub repository URL, it
discovers every `SKILL.md`, statically builds a repository-local dependency graph,
shows a reviewable install plan, and installs only the graph closure. It never runs
code from the source repository.

## Research baseline

The design is clean-room and does not copy source code from the projects below.

- Agent Skills specification: portable skills are directories with a required
  `SKILL.md`; `name` and `description` are required frontmatter fields and optional
  resources are conventionally placed in `scripts/`, `references/`, and `assets/`.
- Vercel `skills`: useful precedents are broad repository discovery, agent adapters,
  input sanitization, symlink/copy installation modes, and provenance lockfiles.
- `junior/skilla`: useful precedents are standard-library-light operation, transitive
  `requires` resolution, immutable commit recording, and never executing skill code
  during install.
- Claude Code: project and user skills conventionally live under `.claude/skills`
  and `~/.claude/skills`.
- OpenCode: native project and user locations are `.opencode/skills` and
  `${XDG_CONFIG_HOME:-~/.config}/opencode/skills`; it also reads `.claude/skills`
  and `.agents/skills` compatibility locations.
- Codex: the current open convention is `.agents/skills` for repository and user
  skills. A `codex-legacy` adapter remains available for installations that still
  use `${CODEX_HOME:-~/.codex}/skills`.

Both reviewed installer projects are MIT licensed. No implementation is imported,
so this project has no derivative-code attribution requirement.

## Scope

### MVP commands

- `inspect SOURCE`: fetch once, identify source/revision, list skills, and summarize
  repository-level warnings.
- `list SOURCE`: list discovered skills with name, path, description, dependencies,
  installability, and structural warnings.
- `analyze SOURCE --skill NAME [...]`: emit the dependency graph and security plan.
- `install SOURCE --skill NAME [...]`: repeat analysis, require confirmation, stage a
  minimal repository tree, link skill roots into the selected agent directory, and
  record provenance.

All commands support human-readable output and `--json`. `install` supports
`--dry-run`; a non-interactive real install requires `--yes`.

`update`, `remove`, `reinstall`, registries, and integrity re-verification are
explicit extension points, not silent partial MVP implementations.

### Source support

- Canonical GitHub HTTPS repository URLs are the public interface.
- GitHub `tree/<ref>/<path>` URLs and an explicit `--ref` are accepted with documented
  limitations for branch names containing `/`.
- Local directories are accepted for deterministic development and fixture tests.
- Git is preferred but not required. The fallback uses GitHub's HTTPS API and archive
  endpoints through Python's standard library.
- The resolved commit SHA, never just a branch name, identifies the analyzed content.

## Architecture

```text
CLI
 |
 +-- Source parser and fetcher
 |    +-- validated github.com URL
 |    +-- no-checkout Git clone + exact Git object materialization
 |    `-- bounded GitHub ZIP fallback
 |
 +-- Repository index
 |    +-- SKILL.md discovery at any depth
 |    +-- small YAML-frontmatter subset parser
 |    `-- duplicate/invalid skill diagnostics
 |
 +-- Static analyzer
 |    +-- explicit skill dependencies
 |    +-- relative path references
 |    +-- internal symlink targets
 |    +-- Python/Node/shell local dependencies
 |    +-- semantic skill-reference candidates
 |    `-- security signal scanner
 |
 +-- Dependency graph and plan
 |    +-- confirmed / inferred / possible edges
 |    +-- transitive closure, deduplication, cycles
 |    `-- risk and blockers
 |
 `-- Installer
      +-- adapter-selected destination
      +-- minimal repository-shaped content store
      +-- skill-root links
      +-- atomic registry/provenance writes
      `-- collision refusal and rollback
```

Modules are kept in one standard-library Python entrypoint for portable skill
distribution, but internal classes separate these responsibilities so they can be
split without changing the CLI contract.

## Dependency model

Every edge records:

- source node and target node;
- edge kind (`explicit-skill`, `relative-path`, `symlink`, `python-import`,
  `node-import`, `shell-source`, or `semantic-skill`);
- confidence (`confirmed`, `inferred`, or `possible`);
- human-readable evidence and source location.

### Confirmed

Automatically included in the closure:

- `requires` / `metadata.requires` / recognized equivalent metadata;
- dependency keys in adjacent `skill.json`, `plugin.json`, or `manifest.json`, and
  recognized root plugin manifests;
- existing relative file or directory references;
- safe repository-internal symlink targets;
- resolvable local Python, Node, or shell dependencies;
- a `SKILL.md` reached through an explicit relative path.

### Inferred

Displayed separately and included only with `--include-inferred`:

- imperative or required natural-language instructions that clearly invoke another
  discovered skill, such as “Use the `frontend-design` skill before this task.”

### Possible

Never included by default. These are mentions whose context is ambiguous, illustrative,
negative, comparative, or otherwise unsuitable for automatic installation. They can be
selected only with `--include-possible`, which is deliberately explicit.

### Graph closure

Traversal is queue-based and keyed by normalized repository-relative node identity.
The analyzer records back-edges as cycles and never enqueues a visited node twice.
Missing confirmed dependencies and unsafe symlinks become install blockers.

## Relative-path-preserving installation

Flattening dependencies into an agent's skill folder would break paths such as
`../../shared/utils.py`. Instead, each installation creates a content-addressed store:

```text
<state>/stores/<owner>--<repo>/<commit>-<closure>/repo/
  skills/foo/
  skills/bar/
  shared/utils.py
  templates/report.md
```

Only graph-closure entries are materialized, but their paths relative to repository
root are unchanged. The adapter destination exposes links such as:

```text
.claude/skills/foo -> <store>/repo/skills/foo
.claude/skills/bar -> <store>/repo/skills/bar
```

This preserves path behavior without copying the unrelated repository. `--link-mode
copy` is allowed only when every dependency is contained in the installed skill roots;
otherwise the CLI refuses rather than knowingly produce a broken installation.

Project state defaults to `<project>/.skill-hunter/`; global state follows
`${XDG_DATA_HOME:-~/.local/share}/skill-hunter/`. A custom destination or state path is
accepted only from CLI arguments, never from repository content.

## Agent adapters

| Target | Project destination | Global destination |
| --- | --- | --- |
| `claude` | `.claude/skills` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` |
| `opencode` | `.opencode/skills` | `${XDG_CONFIG_HOME:-~/.config}/opencode/skills` |
| `codex` | `.agents/skills` | `~/.agents/skills` |
| `codex-legacy` | `.codex/skills` | `${CODEX_HOME:-~/.codex}/skills` |
| `universal` | `.agents/skills` | `${XDG_CONFIG_HOME:-~/.config}/agents/skills` |
| `custom` | explicit `--destination` | explicit `--destination` |

`auto` detects existing agent configuration markers. Ambiguous detection stops with a
short list of explicit target choices instead of guessing.

## Static analysis rules

### Frontmatter

The parser intentionally supports the portable subset needed for discovery:

- scalar strings, quoted strings, folded/literal scalar blocks;
- inline and block lists;
- nested mappings used by `metadata` and dependency extensions.

Malformed or unsupported frontmatter is diagnosed. It is never evaluated, tagged, or
passed to an unsafe general-purpose loader.

Recognized dependency keys include `requires`, `requiredSkills`, `required-skills`,
`skillDependencies`, and `skill-dependencies`, at top level or below `metadata` /
`dependencies`. The same keys are scanned recursively in bounded JSON skill/plugin
manifests. Values may be a list or a comma/space-delimited string.

### Files and scripts

- Relative references are resolved from the referencing file and must remain within
  the repository root.
- Python is parsed with `ast`; only repository-resolvable imports are added.
- Node static `require`, `import ... from`, side-effect imports, and dynamic imports
  with literal relative paths are followed.
- Shell `source`, `.`, and direct local interpreter/script invocations are followed.
- Dynamic imports, generated paths, language package-manager dependencies, and remote
  URLs are reported but not resolved as repository-local dependencies.

## Threat model and safety invariants

The remote repository, its paths, metadata, instructions, scripts, and archives are
untrusted input.

- Source scripts, install hooks, and package managers are never executed.
- Git uses a no-checkout clone; exact immutable tree objects are materialized without
  checkout filters, hooks, or `.gitattributes` export exclusions.
- Archive members are bounded and rejected on absolute paths, `..`, NULs, device-like
  entries, or repository escape.
- Repository-provided names never choose an arbitrary destination path.
- Absolute, escaping, broken, or circular symlinks are blocked and never followed.
- Collision checks complete before destination mutation. Existing skills are never
  overwritten.
- Installation uses staging, atomic metadata replacement, and rollback of links created
  during a failed transaction.
- Executables, hooks, shell/process execution, network access, credential references,
  destructive commands, and `curl | sh`-style patterns are summarized before install.
- Output strips control characters so repository metadata cannot spoof terminal text.
- Provenance records the canonical source URL, immutable commit, graph, file hashes,
  target, scope, and timestamp.

## Non-goals and limits

- This is not a complete language package manager and does not install pip/npm/system
  packages.
- It does not prove that a skill is benign; it reports static signals for human/agent
  review.
- Natural-language classification is conservative and deterministic. The Agent Skill
  instructs the host model to review inferred/possible evidence before approval.
- Cross-repository skill dependencies are reported as unresolved in the MVP.
- Copy mode cannot preserve arbitrary dependencies outside skill roots.
- Git submodule contents are not fetched automatically.

## External behavior contract

- Read-only commands do not mutate the current project or user skill directories.
- `install --dry-run` performs the same analysis and collision checks as installation
  but creates no destination, state, registry, or provenance files.
- A high-risk blocker produces a non-zero exit and no partial installation.
- A successful install leaves every installed skill root readable at the adapter path,
  every confirmed repository-local path resolvable in the store, and an immutable
  commit in provenance.
