# skill-hunter

Hunt, inspect, and safely import Agent Skills from GitHub — with
repository-local dependency tracking.

`skill-hunter` is an Agent Skill and a standalone Python CLI. It discovers
`SKILL.md` files anywhere in a GitHub repository, builds a static dependency
graph for a selected skill, shows a reviewable install plan, and installs only
the required repository paths. It does not execute code from the source
repository during discovery or installation.

## Why it exists

Copying only the folder that contains `SKILL.md` often produces a broken skill.
A skill can depend on a sibling skill, a shared template several directories
above it, a symlink target, or a helper imported by one of its scripts.

`skill-hunter` keeps those repository-local relationships intact:

```text
skill-a
├── skill-b
│   └── shared/rules.md
├── scripts/foo.py
│   └── shared/utils.py
└── templates/report.md
```

The fetched repository is analyzed in a temporary directory. The installed
artifact is a minimal, repository-shaped dependency closure, not a checkout of
the entire source repository.

## Features

- Finds `SKILL.md` at any depth, including `skills/`, `.claude/skills/`,
  `.agents/skills/`, and nested package layouts.
- Lists skill name, source path, description, dependency metadata,
  installability, and structural warnings.
- Resolves explicit and transitive skill dependencies.
- Follows existing relative paths, safe internal symlinks, and static local
  imports from Python, Node, and shell scripts.
- Reports natural-language skill calls as `inferred` or `possible` candidates
  instead of silently installing every mentioned name.
- Detects cycles and deduplicates shared nodes.
- Supports Claude Code, OpenCode, current Codex conventions, a Codex legacy
  adapter, a portable `.agents` target, and explicit custom destinations.
- Refuses destination collisions and unsafe symlinks.
- Records the exact source commit, dependency graph, and SHA-256 file hashes.
- Uses only the Python standard library at runtime. `git` is preferred but
  optional; `gh` is never required.

## Requirements

- Python 3.9 or newer
- Network access to GitHub for remote sources
- `git` is recommended. Without it, public GitHub repositories use a bounded
  HTTPS API/archive fallback.

No PyPI runtime package is required.

## Installation

### Install as an Agent Skill

Choose the directory your agent reads. These commands install the repository
itself as the `skill-hunter` skill.

Claude Code, global:

```bash
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  ~/.claude/skills/skill-hunter
```

OpenCode, global:

```bash
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  ~/.config/opencode/skills/skill-hunter
```

Codex, global (current open `.agents` convention):

```bash
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  ~/.agents/skills/skill-hunter
```

For project-local use, replace the destination with
`.claude/skills/skill-hunter`, `.opencode/skills/skill-hunter`, or
`.agents/skills/skill-hunter` inside the project.

### Install only the CLI

Run it directly from a checkout:

```bash
git clone https://github.com/woobin-the-creator/skill-hunter.git
cd skill-hunter
python3 scripts/skill_hunter.py --help
```

Or install the console entrypoint in an isolated environment:

```bash
python3 -m pip install git+https://github.com/woobin-the-creator/skill-hunter.git
skill-hunter --help
```

## Agent usage

Once installed as a skill, users can speak naturally:

```text
https://github.com/foo/bar 여기 있는 스킬 보여줘
이 레포의 skill 목록 보여줘
frontend-design skill의 dependency를 분석해줘
여기 있는 스킬 전부 설치해줘
skill-a를 프로젝트 로컬에 설치해줘
skill-a를 Claude Code 글로벌 skill로 설치해줘
이 skill이 다른 파일이나 skill에 의존하는지도 확인해줘
```

The Agent Skill instructs the host to run a dry-run, review semantic candidates
and security signals, show the plan, and obtain confirmation before making an
installation change.

### Claude Code

```text
/skill-hunter https://github.com/foo/bar 여기 있는 스킬 보여줘
```

Claude Code may also invoke the skill automatically when the request matches its
description.

### OpenCode

Ask OpenCode to use `skill-hunter`, or load it through OpenCode's native skill
tool and provide the repository URL. The native adapter writes project skills to
`.opencode/skills` and global skills to `~/.config/opencode/skills`.

### Codex

```text
$skill-hunter inspect https://github.com/foo/bar and show me its skills
```

The current Codex adapter uses `.agents/skills` for repository and user scope.
Use `--target codex-legacy` only when an older setup intentionally reads
`.codex/skills` or `$CODEX_HOME/skills`.

## CLI usage

```text
skill-hunter inspect SOURCE
skill-hunter list SOURCE
skill-hunter analyze SOURCE --skill NAME [--skill NAME ...]
skill-hunter analyze SOURCE --all
skill-hunter install SOURCE --skill NAME --target TARGET --scope SCOPE --dry-run
```

The repository script exposes the same interface:

```bash
python3 scripts/skill_hunter.py list https://github.com/foo/bar
```

### Discover skills

```bash
python3 scripts/skill_hunter.py inspect https://github.com/foo/bar
python3 scripts/skill_hunter.py list https://github.com/foo/bar --json
```

`inspect` includes per-skill warnings. `list` is the concise inventory view.
Both commands are read-only.

### Analyze one skill

```bash
python3 scripts/skill_hunter.py analyze https://github.com/foo/bar \
  --skill frontend-design
```

Example plan fragment:

```text
Source:      https://github.com/foo/bar
Revision:    9c84e1f0123456789c84e1f0123456789c84e1f0
Requested:   frontend-design
Install set: frontend-design, design-system
Risk:        MEDIUM

Confirmed dependencies:
  - skill:frontend-design -> skill:design-system [explicit-skill]
  - file:scripts/render.py -> file:shared/utils.py [python-import]

Scripts (not executed):
  - skills/frontend-design/scripts/render.py
```

### Dry-run before installation

Project-local Claude Code plan:

```bash
python3 scripts/skill_hunter.py install https://github.com/foo/bar \
  --skill frontend-design \
  --target claude \
  --scope project \
  --dry-run
```

Global Codex plan:

```bash
python3 scripts/skill_hunter.py install https://github.com/foo/bar \
  --skill frontend-design \
  --target codex \
  --scope global \
  --dry-run
```

Install all valid skills in a repository:

```bash
python3 scripts/skill_hunter.py install https://github.com/foo/bar \
  --all --target opencode --scope project --dry-run
```

After reviewing the exact plan, repeat the same command without `--dry-run` and
add `--yes`. Non-interactive real installs require `--yes`.

### Semantic dependency choices

An imperative sentence such as “Use the `frontend-design` skill before this
task” is reported as `inferred`. It is not installed by default:

```bash
python3 scripts/skill_hunter.py analyze https://github.com/foo/bar \
  --skill report-builder --include-inferred
```

Ambiguous examples and comparisons remain `possible`. Including them requires
the deliberately explicit `--include-possible` flag.

## Agent destination adapters

| Target | Project scope | Global scope |
| --- | --- | --- |
| `claude` | `.claude/skills` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` |
| `opencode` | `.opencode/skills` | `${XDG_CONFIG_HOME:-~/.config}/opencode/skills` |
| `codex` | `.agents/skills` | `~/.agents/skills` |
| `codex-legacy` | `.codex/skills` | `${CODEX_HOME:-~/.codex}/skills` |
| `universal` | `.agents/skills` | `${XDG_CONFIG_HOME:-~/.config}/agents/skills` |
| `custom` | explicit `--destination` | explicit `--destination` |

`--target auto` uses existing configuration markers only when one result is
unambiguous. It asks for an explicit target rather than guessing when several
agents are installed.

Path conventions were checked against the
[Agent Skills specification](https://agentskills.io/specification),
[Claude Code skills documentation](https://code.claude.com/docs/en/slash-commands),
[OpenCode skills documentation](https://opencode.ai/docs/skills), and
[official OpenAI Codex skill documentation](https://developers.openai.com/codex/skills).

## Supported dependency detection

| Dependency type | Confidence | Behavior |
| --- | --- | --- |
| `requires`, `metadata.requires`, JSON manifest variants | Confirmed | Recursive skill closure |
| Existing `./` or `../` path | Confirmed | File/directory closure |
| Referenced conventional resource path such as `scripts/x.py` | Confirmed | File/directory closure |
| Repository-internal symlink target | Confirmed | Link plus target closure |
| Static Python repository-local import | Confirmed | Module and recursive imports |
| Static Node relative import/require | Confirmed | Module and recursive imports |
| Shell `source` or local script invocation | Confirmed | Script and recursive references |
| Imperative natural-language skill call | Inferred | Review; opt in |
| Example, comparison, optional, or ambiguous skill mention | Possible | Excluded by default |

The graph records evidence and source location for each edge. Repeated nodes are
materialized once, and cycles are reported without recursive duplication.

## Installation layout and provenance

For arbitrary relative paths to keep working, the minimal closure is stored with
its original repository layout:

```text
<state>/stores/<source>/<commit>-<closure>/
├── provenance.json
└── repo/
    ├── skills/foo/
    ├── skills/bar/
    └── shared/utils.py
```

The selected agent directory gets relative links to the skill roots in that
store. Project state defaults to `<project>/.skill-hunter`; global state defaults
to `${XDG_DATA_HOME:-~/.local/share}/skill-hunter`.

`provenance.json` records:

- canonical source URL;
- exact 40-character Git commit for GitHub sources;
- requested and transitive skills;
- dependency edges and confidence;
- every installed repository-relative path and SHA-256 hash (or symlink target);
- destination adapter, scope, and installation timestamp.

A registry beside the stores makes future `update`, `remove`, `reinstall`, and
integrity verification possible without guessing ownership.

## Safety principles

- The source repository is untrusted input.
- Git acquisition uses a no-checkout clone and materializes exact immutable tree
  objects without checkout filters, hooks, or `.gitattributes` export exclusions.
- Repository scripts, install hooks, package managers, and tests are never run.
- Archive file count, download size, and extracted size are bounded.
- Absolute paths, path traversal, special files, escaping/broken/circular
  symlinks, and destination escape are rejected.
- Existing skills are never overwritten. A collision produces a small diff
  summary and no mutation.
- Installation is staged; exposed links and a newly created store are rolled
  back if the transaction fails.
- Executable files, hooks, network/process behavior, destructive commands,
  credential references, and pipe-to-shell patterns are reported before install.
- Terminal control characters from repository metadata are stripped from human
  output.
- A `LOW` risk label is not a security guarantee. Static analysis cannot prove a
  third-party skill is benign.

## Known limitations

- Dynamic imports, generated paths, runtime reflection, and language package
  dependencies are not fully resolvable statically.
- pip, npm, system packages, and other external dependencies are reported only
  through visible evidence; they are never installed automatically.
- Cross-repository skill dependencies are not fetched in the MVP.
- Git submodules are not initialized automatically.
- A GitHub `/tree/<ref>/<path>` URL treats the first segment after `tree/` as the
  ref. Use `--ref` plus a repository-root URL when a branch name contains `/`.
- General YAML is intentionally unsupported. The parser accepts the safe subset
  commonly used by Agent Skill frontmatter, including mappings, lists, quoted
  values, and multiline descriptions.
- Symlink mode is required for graphs that depend on files outside one skill
  root. Copy fallback is limited to a self-contained single skill.
- Windows symlink creation can require Developer Mode or elevated permission.
- Semantic classification is conservative and deterministic; the host agent or
  user must review inferred and possible evidence.

## Development and tests

The project has no runtime test dependency:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q skill_hunter scripts
```

The suite creates temporary Git repositories and covers the required fixtures:
independent skills, explicit and transitive dependencies, relative files,
symlinks, Python/Node/shell imports, cycles, escaping symlinks, collisions,
natural-language calls, unrelated large content, shared dependency
deduplication, archive safety, adapters, provenance, and dry-run write
invariants.

Design decisions and the release evidence gate are documented in
[`docs/design.md`](docs/design.md) and
[`docs/acceptance.md`](docs/acceptance.md).

## Related ecosystem work

The implementation is clean-room. The design review considered the MIT-licensed
[Vercel `skills` CLI](https://github.com/vercel-labs/skills) and
[`junior/skilla`](https://github.com/junior/skilla) for ecosystem conventions,
but does not copy their source code. `skill-hunter` focuses specifically on
repository-local dependency graphs and path-preserving minimal imports.

## License

[MIT](LICENSE)
