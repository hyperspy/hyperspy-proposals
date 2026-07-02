#!/usr/bin/env python3
"""Validate YAML frontmatter in proposal markdown files.

Checks every root-level ####-*.md proposal file for:
  - Required YAML frontmatter block
  - Required fields: proposal, title, type, target_branch, target_repos,
    status, ai_assisted, created
  - Valid enum values for type and status
  - ai_assisted as boolean
  - proposal number matches filename prefix

Exits 0 if all files pass, 1 on any validation error.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(2)

REQUIRED_FIELDS = {
    "proposal",
    "title",
    "type",
    "target_branch",
    "target_repos",
    "status",
    "ai_assisted",
    "created",
}

VALID_TYPES = {"Architecture", "Feature", "Bugfix", "Process"}
VALID_STATUSES = {"review", "accepted", "implemented", "superseded"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict | None:
    """Extract and parse YAML frontmatter from markdown text. Returns None if no
    frontmatter found."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    return yaml.safe_load(match.group(1))


def _validate_frontmatter(frontmatter: dict, filename: str) -> list[str]:
    """Return list of error messages (empty if valid)."""
    errors: list[str] = []

    # 1. Required fields present
    missing = REQUIRED_FIELDS - set(frontmatter.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")

    # 2. Validate 'type' enum
    prop_type = frontmatter.get("type")
    if prop_type and prop_type not in VALID_TYPES:
        errors.append(
            f"Invalid type '{prop_type}'. Must be one of: {', '.join(sorted(VALID_TYPES))}"
        )

    # 3. Validate 'status' enum
    status = frontmatter.get("status")
    if status and status not in VALID_STATUSES:
        errors.append(
            f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    # 4. Validate ai_assisted is boolean
    ai_assisted = frontmatter.get("ai_assisted")
    if ai_assisted is not None and not isinstance(ai_assisted, bool):
        errors.append(f"ai_assisted must be a boolean, got {type(ai_assisted).__name__}")

    # 5. Validate proposal number matches filename prefix
    proposal = frontmatter.get("proposal")
    if proposal is not None:
        expected_prefix = f"{int(proposal):04d}"
        if not filename.startswith(expected_prefix):
            errors.append(
                f"proposal number '{proposal}' does not match filename prefix "
                f"'{expected_prefix}' (filename: {filename})"
            )

    return errors


def _nonzero_str(value: object) -> bool:
    """Return True if value is a non-empty string."""
    return isinstance(value, str) and len(value) > 0


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent.parent
    md_files = sorted(repo_root.glob("proposals/[0-9][0-9][0-9][0-9]-*.md"))

    all_errors: dict[str, list[str]] = {}
    errors = 0

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(text)

        if frontmatter is None:
            all_errors[md_file.name] = ["No YAML frontmatter found (missing --- ... --- block)"]
            errors += 1
            continue

        file_errors = _validate_frontmatter(frontmatter, md_file.name)
        if file_errors:
            all_errors[md_file.name] = file_errors
            errors += len(file_errors)

    if all_errors:
        print(f"\n{errors} validation error(s) found:\n")
        for fname, errs in all_errors.items():
            print(f"  {fname}:")
            for e in errs:
                print(f"    - {e}")
        print()
        return 1

    print(f"All {len(md_files)} proposal file(s) passed frontmatter validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
