# Acceptance and evidence plan

Status values are updated only after observable evidence exists.

## Product acceptance matrix

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| A01 | Independent project named `skill-hunter` | repository root name, root `SKILL.md`, independent `.git` | Pass |
| A02 | Discover skills anywhere in a GitHub repository | discovery fixtures plus real repositories with distinct layouts | Pass |
| A03 | List name, path, description, metadata, dependencies, installability, warnings | CLI text/JSON assertions | Pass |
| A04 | Select one or all skills | CLI tests for repeated `--skill` and `--all` | Pass |
| A05 | Explicit dependency closure | fixture `foo -> bar` | Pass |
| A06 | Transitive dependency closure | fixture `foo -> bar -> baz` | Pass |
| A07 | Relative file closure | fixture `foo -> ../../shared/rules.md` | Pass |
| A08 | Internal symlink closure and path preservation | fixture symlink plus installed-link resolution | Pass |
| A09 | Script-local dependency closure | Python, Node, and shell fixtures | Pass |
| A10 | Natural-language skill invocation candidate | inferred/possible classification fixture | Pass |
| A11 | Cycle detection and deduplication | `foo -> bar -> foo`, shared dependency graph assertions | Pass |
| A12 | Repository-external symlink blocked | external symlink fixture and install refusal | Pass |
| A13 | Existing skill not overwritten | sentinel-content collision test | Pass |
| A14 | Unrelated large directory excluded | closure and installed-store assertions | Pass |
| A15 | Dry-run has zero installation writes | before/after filesystem assertion | Pass |
| A16 | Provenance includes immutable commit SHA | local Git fixture and manifest assertion | Pass |
| A17 | Claude/OpenCode/Codex adapters | project/global destination resolution tests | Pass |
| A18 | No source code executed | malicious marker fixture remains absent | Pass |
| A19 | Runtime does not require `gh` | live restricted-`PATH` archive-fallback validation | Pass |
| A20 | GitHub archive fallback | mocked archive test and live no-git fallback | Pass |
| A21 | Public quality files | README, MIT LICENSE, `.gitignore`, CI workflow, validator | Pass |
| A22 | Three real repository dry-runs | recorded source, SHA, discovered selection, result | Pass |
| A23 | Secret/personal-path hygiene | tracked-file scans and staged-diff review | Pass |
| A24 | Public GitHub publication | public visibility, `main`, remote SHA equality | Pass |

## Required fixture cases

The test suite must include the twelve user-specified cases as named test methods or
subtests, not merely cover them incidentally:

1. independent skill;
2. explicit dependency;
3. transitive dependency;
4. relative file dependency;
5. symlink dependency;
6. script dependency;
7. dependency cycle;
8. repository-external symlink;
9. existing installation collision;
10. natural-language skill call;
11. unrelated large directory exclusion;
12. shared dependency deduplication.

Additional tests cover malformed frontmatter, duplicate names, path traversal,
archive extraction, risk signals, destination adapters, JSON output, dry-run write
invariants, copy-mode limits, and transactional rollback where practical.

## Real-repository evidence format

Each integration validation records:

```text
Source: <canonical GitHub URL>
Revision: <40-character commit SHA>
Layout characteristic: <root / skills / .claude / nested package>
Command: <dry-run command>
Selected skill(s): <names>
Closure: <skill and external repository-local paths>
Result: PASS or FAIL with reason
```

No script from those repositories may be executed during validation.

## Release gate

Publication is allowed only when:

- the full local test suite passes;
- the skill creator validator passes;
- three real-repository dry-runs pass;
- all install blockers fail closed without partial writes;
- tracked files contain no token-like values, local absolute workspace paths, fixture
  secrets, caches, temporary clones, or generated test artifacts;
- `git status` contains only intended files before the initial commit;
- the GitHub repository is public and does not pre-exist with unrelated content;
- local `HEAD`, `origin/main`, and the GitHub-reported default-branch SHA match.
