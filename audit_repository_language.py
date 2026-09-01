import sys
from collections import Counter
from pathlib import Path

from application.services.repository_language_audit_service import (
    RepositoryLanguageAuditService,
)


AUDIT_ERROR_MESSAGE = (
    "The repository language audit could not be completed."
)


def main(
    project_root=None,
    intentional_exceptions=(),
):
    """Run the tracked-file language audit and return its exit code."""

    resolved_project_root = Path(
        project_root
        if project_root is not None
        else Path(__file__).resolve().parent
    ).resolve()

    try:
        result = RepositoryLanguageAuditService(
            project_root=resolved_project_root,
            intentional_exceptions=intentional_exceptions,
        ).audit_repository()
    except Exception:
        print(AUDIT_ERROR_MESSAGE, file=sys.stderr)
        return 2

    findings = result["findings"]
    if findings:
        _print_report(findings)
        return 1

    counts = result["counts"]
    print(
        "Repository language audit passed: "
        f'{counts["tracked_files"]} tracked files; '
        f'{counts["audited_text"]} audited text; '
        f'{counts["intentional_binary_exclusion"]} '
        "intentional binary exclusions; "
        f'{counts["controlled_non_language_exclusion"]} '
        "controlled non-language exclusions; "
        f"{len(findings)} findings; "
        f'{counts["audit_error"]} audit errors.'
    )
    return 0


def _print_report(findings):
    """Print deterministic, concise, actionable finding details."""

    category_counts = Counter(
        finding["category"]
        for finding in findings
    )
    print("Repository language audit")
    print(f"Total findings: {len(findings)}")
    for category in sorted(category_counts):
        print(f"{category}: {category_counts[category]}")

    for finding in findings:
        matched_terms = ", ".join(finding["matched_terms"])
        text = " ".join(finding["line"].split())
        if len(text) > 160:
            text = text[:157] + "..."
        print(
            f'{_terminal_safe_text(finding["path"])}:'
            f'{_terminal_safe_text(finding["line_number"])} '
            f'[{finding["category"]}/'
            f'{finding.get("finding_type", "language")}] '
            f"{matched_terms}: {text}"
        )


def _terminal_safe_text(value):
    """Render a finding field without terminal-control characters."""

    escaped = []
    for character in str(value):
        if character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif character.isprintable():
            escaped.append(character)
        elif ord(character) <= 0xFF:
            escaped.append(f"\\x{ord(character):02x}")
        elif ord(character) <= 0xFFFF:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(f"\\U{ord(character):08x}")
    return "".join(escaped)


if __name__ == "__main__":
    raise SystemExit(main())