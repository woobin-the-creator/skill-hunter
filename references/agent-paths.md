# Agent destination adapters

Use an explicit adapter whenever the user names an agent. Conventions can evolve; these
defaults reflect the official documentation reviewed for the initial release.

| Adapter | Project scope | Global scope |
| --- | --- | --- |
| `claude` | `<project>/.claude/skills` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` |
| `opencode` | `<project>/.opencode/skills` | `${XDG_CONFIG_HOME:-~/.config}/opencode/skills` |
| `codex` | `<project>/.agents/skills` | `~/.agents/skills` |
| `codex-legacy` | `<project>/.codex/skills` | `${CODEX_HOME:-~/.codex}/skills` |
| `universal` | `<project>/.agents/skills` | `${XDG_CONFIG_HOME:-~/.config}/agents/skills` |
| `custom` | explicit `--destination` | explicit `--destination` |

OpenCode also discovers compatible `.claude/skills` and `.agents/skills` locations, but
its native adapter is preferable when the user explicitly names OpenCode. Claude Code's
documented native location is `.claude/skills`.

`auto` checks existing configuration markers without executing an agent. It stops when
zero or multiple targets match, so an agent can ask or select an explicit adapter rather
than guessing.

Project state is stored under `<project>/.skill-hunter`. Global state uses
`${XDG_DATA_HOME:-~/.local/share}/skill-hunter`. Repository content never controls these
paths.
