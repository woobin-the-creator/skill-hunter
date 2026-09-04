# Dependency model

Use this reference when reviewing `analyze` or `install --dry-run` output.

## Confidence classes

### Confirmed

The static analyzer can resolve the dependency to repository content:

- recognized `requires` metadata;
- an existing relative path;
- an internal symbolic-link target;
- a static Python, Node, or shell repository-local import;
- a relative reference to another `SKILL.md`.

Confirmed dependencies enter the default transitive closure. A missing explicit skill
or an unsafe symlink is a blocker rather than a silently omitted edge.

### Inferred

A `SKILL.md` instruction uses imperative/required wording to invoke another discovered
skill, but the relationship is natural language rather than a machine declaration.
Review the evidence. Include it with `--include-inferred` only when the other skill is
needed to perform the workflow.

### Possible

The text mentions another discovered skill in ambiguous, illustrative, negative,
optional, or comparative context. Leave it excluded unless the user deliberately
chooses `--include-possible` after seeing the evidence.

## Graph semantics

Nodes are `skill:<name>` or `file:<repository-relative-path>`. Edges retain source,
target, kind, confidence, evidence, and location. Multiple source files may legitimately
point to one node; the node is materialized only once. Skill cycles are reported as a
closed path and do not cause repeated traversal.

## Static-analysis limits

The analyzer follows literal, repository-resolvable paths. It does not execute code,
evaluate templates, resolve dynamic imports, install language packages, initialize Git
submodules, or fetch cross-repository dependencies. Treat unresolved runtime-generated
paths as review items, not as proof that no dependency exists.

## Installed layout

The content store preserves every selected entry's repository-relative path. Agent
directories receive links to skill roots in that store. This is why a dependency such
as `../../shared/utils.py` still resolves without copying an unrelated large directory.

Copy mode is intentionally narrower: it is safe only for a single self-contained skill.
For other graphs, use the default symlink mode.
