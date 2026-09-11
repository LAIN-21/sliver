# Agent instructions

This file is the repository-wide constitution. Read it before modifying the repository.

Canonical docs:

- Product: [docs/PRODUCT.md](docs/PRODUCT.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Development: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Area instructions: [docs/agents/](docs/agents/)
- ADRs: [docs/adr/README.md](docs/adr/README.md)

## Precedence

- This file defines repository-wide invariants and cannot be weakened.
- Area-specific instructions under [docs/agents/](docs/agents/) may add stricter constraints.
- The assigned GitHub Issue defines task-specific Scope, Out of Scope, Allowed Paths, Protected Areas, Acceptance Criteria, and Required Verification.
- More specific instructions may narrow behavior but may never override repository-wide product, security, or architecture invariants.

An issue that says "modify payments however needed" still cannot override a global safety boundary.

## Issue contract

- Read the assigned GitHub Issue before modifying code.
- Follow the issue's Scope, Out of Scope, Allowed Paths, Protected Areas, Acceptance Criteria, and Required Verification.
- Allowed Paths describe the expected implementation surface, not permission to ignore repository invariants.
- If correctness requires work outside Allowed Paths, disclose it in the PR under Changes outside expected scope.
- Do not modify Protected Areas unless the task itself is revised.
- Prefer the smallest coherent change that satisfies the issue.
- Do not perform unrelated cleanup or refactoring.
- Do not silently expand Scope.
- If correctness requires work outside allowed Scope, report the reason explicitly.

## Task issue creation

- Before creating a Task issue programmatically, read [`.github/ISSUE_TEMPLATE/task.yml`](.github/ISSUE_TEMPLATE/task.yml).
- Reproduce the same Task field labels.
- Preserve required vs optional semantics.
- Do not silently omit required fields.
- Verify the created issue contains all required Task fields.
- Do not invent labels, milestones, assignees, or other metadata unless explicitly requested.

## Required reading

- Read [docs/PRODUCT.md](docs/PRODUCT.md) when product behavior is involved.
- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) when architectural boundaries are involved.
- Read relevant files under [docs/agents/](docs/agents/) for the area you are changing.

## Invariants

- Never expose protected paid seller data through public discovery metadata.
- Never implement autonomous buyer spending as Sliver platform behavior.
- Preserve the Resource abstraction unless an approved ADR changes it.
- Do not port prototype code from `ripple-challenge` without an explicit task.
- Never modify `LICENSE` unless explicitly assigned.

## Dependencies and architecture

- Do not casually introduce a new framework, service, database, queue, infrastructure dependency, or major library.
- Significant architecture changes require an ADR.
- Do not edit generated files or lockfiles unless the task requires a dependency/tooling change.

## Secrets, config, and artifacts

- Never commit secrets.
- Document every future environment variable in `.env.example` once that file exists.
- Do not create planning, summary, scratch, or generated documentation files unless the task explicitly requests a persistent repository artifact.
- Put completion reports in the pull request template, not in leftover repository files.

## Documentation and verification

- If implementation changes established behavior in [docs/PRODUCT.md](docs/PRODUCT.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), or an ADR, update that documentation in the same PR when it is within Scope.
- Never silently leave authoritative documentation inconsistent with implementation.
- Run all Required Verification.
- In the PR, list every Required Verification item from the issue, state whether each ran, and explain why any item did not run.
- Write `None` when no Required Verification applies.
- This applies to all verification, not only tests.
- Never claim a test was run if it was not.
- Explicitly state tests that were not run and why.
- Complete the PR template truthfully. Do not write vague answers such as "all done."
