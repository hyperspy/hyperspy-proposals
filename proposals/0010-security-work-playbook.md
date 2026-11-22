---
proposal: "0010"
title: "HyperSpy ecosystem security-work playbook"
type: Process
target_branch: hyperspy/.github:main
target_repos: [hyperspy/.github]
status: review
ai_assisted: true
created: 2026-11-22
---

## Summary

Create organization-level guidance for deciding, verifying, disclosing, and learning
from security work across the HyperSpy ecosystem. The decision needed is whether to
centralize this decision discipline in `hyperspy/.github` as documentation and
copy-paste templates, without centralizing security implementation code.

## Problem

Security reports and dependency changes can cross package, upstream, application,
and CI/CD trust boundaries. Without a shared decision procedure, contributors can
build broad local guards before establishing demonstrated impact or upstream
ownership, reproduce behavior at the wrong layer, or leave residual risk recorded
only in transient work artifacts. AI-assisted work adds a need for explicit scope,
review limits, publication authorization, and attribution.

The organization currently has shared contributor and AI-policy documents, but no
canonical guide covering the complete security-work lifecycle.

## Proposed approach

Add three linked documents to `hyperspy/.github`:

1. A concise playbook covering intake, ownership, minimum-fix selection, evidence,
   dependencies, CI/CD, AI-agent execution, disclosure, residual risk, and learning.
2. A copy-paste agent brief requiring concrete scope, acceptance commands, positive
   controls, authorization, review caps, cleanup, and disclosure obligations.
3. A lessons index and case-study template seeded only with public upstream
   documentation and discussions.

Update the existing organization README and contributor guide only enough to make
the resources discoverable. Follow the target repository's existing validation and
PR conventions.

### Alternatives considered

| Approach | Decision | Rationale |
| --- | --- | --- |
| Central decision playbook and templates | Proposed | Shares repeatable decisions while leaving implementation in owning repositories. |
| Duplicate full guidance in each repository | Reject | Increases synchronization cost and divergent policy. |
| Build a shared security guard framework | Reject | Creates maintenance burden before individual cases establish ownership and need. |
| File-I/O-only guidance | Reject | Omits injection, supply-chain, CI/CD, data-handling, disclosure, and other lifecycle concerns. |
| Wait for repository-specific incidents | Reject | Does not provide a reusable intake and decision procedure. |

## Impact

No package API, runtime behavior, dependency, workflow, or user data changes. The
new documents should reduce duplicated decision work and make security-change
review expectations clearer. Maintainers retain responsibility for case-specific
risk decisions and coordinated disclosure.

The initial change is limited to one documentation PR. After it merges, separate
small PRs can add thin links in ecosystem repositories; no migration is required.

## Scope

In scope:

- Full-lifecycle, risk-based security-work decision guidance.
- Minimum effective fixes, primary-source evidence, compatibility, and residual risk.
- Dependency and CI/CD security expectations based on GitHub and OpenSSF guidance.
- AI-agent scope, verification, review, authorization, and attribution discipline.
- Public, independently verifiable upstream lessons with review dates and revisit triggers.

Explicitly out of scope:

- Security implementation code, shared parsers, validators, sandbox frameworks, or guard libraries.
- New CI, Markdown, Sphinx, towncrier, or other repository tooling.
- Private reports, unpublished advisories, remediation history, or undisclosed case studies.
- Changes to runtime packages, workflows, branch protections, or organization settings.
- Merging the implementation PR or rolling links out to other repositories in the same change.

## References

- [HyperSpy AI policy](https://github.com/hyperspy/.github/blob/main/AI-POLICY.md)
- [NIST Secure Software Development Framework](https://csrc.nist.gov/Projects/ssdf)
- [OpenSSF coordinated vulnerability disclosure guide](https://oss-vulnerability-guide.openssf.org/)
- [GitHub Actions secure use reference](https://docs.github.com/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)
- [GitHub dependency review](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review)

## Technical design

### Document responsibilities

```text
hyperspy/.github
├── SECURITY-PLAYBOOK.md      # Canonical lifecycle and decision rules
├── SECURITY-AGENT-BRIEF.md   # Case-specific execution prompt template
├── SECURITY-LESSONS.md       # Public case-study index and template
├── README.md                 # Resource discovery
└── CONTRIBUTING.md           # Contributor entry point
```

### Governance model

The playbook defines decision quality, not implementations. The package that owns
the demonstrated behavior owns its fix and tests. Upstream-owned behavior is routed
upstream; application trust boundaries remain application responsibilities. A
dependency floor, existing runtime policy control, honest trust-boundary warning,
or genuine isolation is preferred over a new incomplete downstream guard where
those options close the demonstrated risk.

Each completed security change must leave a durable residual-risk statement.
Lessons are added only when they change future behavior and have a specific revisit
trigger. Public examples are illustrative rather than a limit on threat scope.

### Validation and publication

Use the target repository's existing pre-commit, pytest, and self-test checks;
verify local links, external primary sources, and `git diff --check`. Review the
final diff for confidentiality, unsupported claims, duplicated AI policy, and
framework-building advice. Publish as a draft PR with explicit AI attribution,
then mark ready only after this proposal is accepted and all required checks pass.
