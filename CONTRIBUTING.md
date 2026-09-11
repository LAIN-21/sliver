# Contributing

GitHub Issues are the source of truth for executable work. See [ROADMAP.md](docs/ROADMAP.md) for the high-level project map.

## Workflow

GitHub Issue → branch → scoped implementation → Required Verification → pull request → review → merge

- One coherent task per PR by default.
- Do not include unrelated changes.
- The PR must link its issue.
- The PR description must be fully completed. Use [the pull request template](.github/pull_request_template.md).
- Architecture changes need an ADR. See [docs/adr/README.md](docs/adr/README.md).

Coding agents must also follow [AGENTS.md](AGENTS.md).

## Issues

Humans should open work with a [task](.github/ISSUE_TEMPLATE/task.yml) or [bug](.github/ISSUE_TEMPLATE/bug.yml) GitHub form.

Agents may create the equivalent Markdown Task issue programmatically. Programmatic creation must mirror the canonical Task schema in [`.github/ISSUE_TEMPLATE/task.yml`](.github/ISSUE_TEMPLATE/task.yml). GitHub form-only mechanics such as field IDs, placeholders, heading rendering, and UI validation do not need to appear in the final issue body.

A task issue is the implementation contract. Field required vs optional semantics match [`.github/ISSUE_TEMPLATE/task.yml`](.github/ISSUE_TEMPLATE/task.yml).

Required:

- Objective
- Scope
- Out of Scope
- Allowed Paths
- Protected Areas
- Acceptance Criteria
- Required Verification

Optional:

- Context
- Dependencies
- Architecture References

Allowed Paths describe the expected implementation surface. They are not permission to ignore repository invariants. If correctness requires modifying another path, disclose it in the PR under Changes outside expected scope.

Protected Areas must not be modified unless the task itself is revised.

Architecture References should link to [docs/PRODUCT.md](docs/PRODUCT.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), ADRs, or [docs/agents/](docs/agents/) rather than copying architecture rules into the issue.

## Pull requests

Complete every section of the PR template. Write `None` where a section does not apply. Do not use vague answers such as "all done."

List every Required Verification item from the linked issue. For each item, state whether it ran. If an item did not run, explain why. This applies to all verification, not only tests. Write `None` when no Required Verification applies.

If implementation changes established behavior documented in product, architecture, development, or ADR docs, update that documentation in the same PR when it is within Scope.
