# AGENTS.md — HyperSpy Proposals

## Purpose

This is the central proposals repository for the [hyperspy](https://github.com/hyperspy) GitHub organization. It hosts markdown proposals for changes to `hyperspy/hyperspy`, `hyperspy/rosettasciio`, `hyperspy/hspy-spec`, and `hyperspy/hyperspy-ml`.

## Workflow for AI Agents

1. **Check for existing proposals** — search this repository for proposals related to your task before writing code.
2. **Create a proposal** — if no proposal exists for a non-trivial AI-assisted change, create one before writing code. Submit it as a PR.
3. **Follow accepted proposals** — if a proposal exists and is accepted, follow the plan and reference it in your implementation PR.
4. **Include attribution** — use the `Assisted-by: <tool>:<model>` trailer in all commits, per HyperSpy's AGENTS.md.

## Proposal Format

Each proposal is a markdown file named `proposals/<PR_NUMBER>-<short-slug>.md` with a YAML frontmatter block:

```yaml
---
proposal: 0001
title: "Human-readable title"
type: Architecture          # Architecture | Feature | Bugfix | Process
target_branch: hyperspy/hyperspy:RELEASE_next_minor
target_repos: [hyperspy/hyperspy, hyperspy/rosettasciio]
status: review              # review | accepted | implemented | superseded
ai_assisted: true
created: 2026-07-01
---
```

### Required sections

A proposal is a **decision document**, not a design document. Its purpose is to help reviewers make a decision. Use these sections:

1. **Summary** — 2-3 sentences: what, why, what decision is needed. A reviewer should understand the entire proposal from this alone.
2. **Problem** — concrete, with examples. What's broken today?
3. **Proposed approach** — high-level: what are we proposing and why this way? Include an **Alternatives considered** table.
4. **Impact** — what breaks? For users, extension maintainers, the ecosystem. Migration path. Effort estimate.
5. **Scope** — what's in. What's explicitly NOT in (guardrails against scope creep).
6. **References** — links to discussions, issues, PRs.
7. **Technical design** — mandatory. Tree diagrams, encoding tables, governance models, code samples, conversion examples. This is where implementation detail goes, not in the proposal body.

### What NOT to include

- Questions for the community (discussion belongs in PR review)
- Unverified claims or speculation
- Implementation specs in the body (put them in Technical design)

## CI Checks

Every PR runs these checks:

- **rumdl** — consistent formatting.
- **link-check** — no broken URLs.
- **frontmatter-validation** — YAML metadata block is present, fields are valid, proposal number matches filename.
- **ai-trailer** — commits include `Assisted-by: <tool>:<model>` trailers.

Run checks locally with `pixi run check` (see the [README](README.md#running-checks-locally)).
