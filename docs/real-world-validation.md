# Real-world dry-run validation

Date: 2026-09-04

Mode: `install --dry-run` only
Source scripts executed: none

All destinations below were deliberately nonexistent before each command. A follow-up
filesystem check confirmed that none of the project roots, agent destinations, state
directories, stores, registries, or provenance files were created by dry-run.

## 1. junior/skilla — conventional `skills/<name>` layout

```text
Source: https://github.com/junior/skilla
Revision: a16ed9dded19e072da83538598bc246a3df13579
Layout characteristic: skills/skilla/SKILL.md, external CLI expected on PATH
Selected skill: skilla
Closure: 1 entry, 6.1 KiB
Risk: MEDIUM
Result: PASS
```

Command:

```bash
python3 scripts/skill_hunter.py install https://github.com/junior/skilla \
  --skill skilla --target codex --scope project \
  --project-root /tmp/skill-hunter-dryrun-skilla --dry-run
```

Observed security summary: the instructions contain executable network command text and
an external URL. The source repository's code was not executed.

## 2. axross/nakami — `.claude/skills/<name>` layout with script

```text
Source: https://github.com/axross/nakami
Revision: 211240d4902e9f14d66901845c70c8e4c7180d48
Layout characteristic: .claude/skills with a Node .mjs helper
Selected skill: agent-skill-management
Closure: 2 entries, 29.1 KiB
Risk: MEDIUM
Result: PASS
```

Command:

```bash
python3 scripts/skill_hunter.py install https://github.com/axross/nakami \
  --skill agent-skill-management --target claude --scope project \
  --project-root /tmp/skill-hunter-dryrun-nakami --dry-run
```

Observed graph: `SKILL.md` references
`scripts/check-installed-copies.mjs`, and that script references its sibling
`../SKILL.md`. Both nodes were deduplicated in the two-entry closure. The script was
reported and not executed.

## 3. vercel-labs/agent-skills — packaged rules and multiline metadata

```text
Source: https://github.com/vercel-labs/agent-skills
Revision: 063bee94c3f4df8453406c830b0a7df0f2860278
Layout characteristic: skills/<source-dir>, bundled rule files, frontmatter name differs
  from source directory, plain multiline YAML description
Selected skill: vercel-composition-patterns
Closure: 14 entries, 49.2 KiB
Risk: LOW
Result: PASS
```

Command:

```bash
python3 scripts/skill_hunter.py install https://github.com/vercel-labs/agent-skills \
  --skill vercel-composition-patterns --target opencode --scope project \
  --project-root /tmp/skill-hunter-dryrun-vercel --dry-run
```

Observed graph: direct rule references were resolved inside the 14-entry skill closure.
The source directory `composition-patterns` and frontmatter name
`vercel-composition-patterns` differ; discovery reports this structure and the install
plan safely exposes the frontmatter name at the agent destination. A template-only
`rules/area-description.md` reference was reported as unresolved rather than invented.

## Edge case found and fixed

The first Vercel run exposed two real ecosystem patterns that were added as regression
tests before the final runs:

1. a plain multiline YAML scalar under `description:`; and
2. a valid install plan whose source directory name differs from frontmatter `name`.

The parser now folds that safe YAML subset, and the installer preserves the source tree
while naming the destination link from validated frontmatter. No source file is renamed
inside the store.

## Acquisition evidence

All three runs used the hardened `git-no-checkout` path. The CLI cloned the source
without a working-tree checkout, resolved the 40-character commit, and materialized
exact Git blob objects. Checkout hooks, smudge filters, source scripts, and
`.gitattributes` `export-ignore` behavior were not invoked.

The same `junior/skilla` list operation was also run with a `PATH` containing neither
`git` nor `gh`. The bounded `github-archive` fallback discovered the same skill at the
same commit `a16ed9dded19e072da83538598bc246a3df13579`. This verifies that neither CLI is a
mandatory runtime dependency.
