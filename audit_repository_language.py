import sys
from collections import Counter
from pathlib import Path

from application.services.repository_language_audit_service import (
    RepositoryLanguageAuditService,
)


AUDIT_ERROR_MESSAGE = (
    "The repository language audit could not be completed."
)

CLI_ALLOWLISTED_PATHS = (
    (
        "application/services/"
        "repository_language_audit_service.py"
    ),
    "tests/test_audit_repository_language.py",
    (
        "tests/"
        "test_repository_language_audit_precision.py"
    ),
    (
        "tests/"
        "test_repository_language_audit_service.py"
    ),
)


def main(
    project_root=None,
    allowlisted_paths=(),
    allowlisted_phrases=(),
):
    """
    Run the repository-wide English conversion audit.

    Returns:
    - 0 when no Norwegian project-owned prose is found
    - 1 when findings remain
    - 2 when the audit cannot be completed
    """

    resolved_project_root = Path(
        project_root
        if project_root is not None
        else Path(__file__).resolve().parent
    ).resolve()

    try:
        findings = (
            RepositoryLanguageAuditService(
                project_root=resolved_project_root,
                allowlisted_paths=(
                    allowlisted_paths
                ),
                allowlisted_phrases=(
                    allowlisted_phrases
                ),
            )
            .audit()
        )

    except Exception:
        print(
            AUDIT_ERROR_MESSAGE,
            file=sys.stderr,
        )

        return 2

    if not findings:
        print(
            "No Norwegian project-owned prose was found."
        )

        return 0

    _print_report(
        findings
    )

    return 1


def _print_report(
    findings,
):
    """
    Print a deterministic, human-readable audit report.
    """

    category_counts = Counter(
        finding["category"]
        for finding in findings
    )

    print(
        "Repository language audit"
    )

    print(
        "========================="
    )

    print(
        f"Total findings: {len(findings)}"
    )

    for category in sorted(
        category_counts
    ):
        print(
            f"{category}: "
            f"{category_counts[category]}"
        )

    print()

    for finding in findings:
        matched_terms = ", ".join(
            finding["matched_terms"]
        )

        print(
            f'{finding["path"]}:'
            f'{finding["line_number"]}'
        )

        print(
            f'  Category: '
            f'{finding["category"]}'
        )

        print(
            f"  Terms: {matched_terms}"
        )

        print(
            f'  Text: {finding["line"]}'
        )

        print()


if __name__ == "__main__":
    raise SystemExit(
        main(
            allowlisted_paths=(
                CLI_ALLOWLISTED_PATHS
            ),
        )
    )