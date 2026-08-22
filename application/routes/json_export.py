from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    render_template,
)

from application.services.json_export_service import (
    JsonExportError,
    JsonExportService,
)


json_export_bp = Blueprint(
    "json_export",
    __name__,
)


@json_export_bp.get(
    "/settings/data-export"
)
def get_json_export():
    """
    Show a summary of the data included in a JSON export.

    The page displays counts and format metadata only. Actual
    person, account, PUUID, champion, and mastery values are not
    embedded in the HTML response.
    """

    export_summary = None
    export_error = None

    try:
        document = (
            JsonExportService
            .build_export_document()
        )

        export_summary = {
            "format": document["format"],
            "format_version": (
                document["format_version"]
            ),
            "database_schema_version": (
                document[
                    "database_schema_version"
                ]
            ),
            "record_counts": dict(
                document["record_counts"]
            ),
        }

    except JsonExportError as error:
        export_error = str(
            error
        )

    return render_template(
        "json_export.html",
        export_summary=export_summary,
        export_error=export_error,
    )


@json_export_bp.get(
    "/settings/data-export/download"
)
def download_json_export():
    """
    Download a complete portable JSON export.

    The same UTC timestamp is used in both the document metadata
    and the downloaded filename.
    """

    exported_at = datetime.now(
        timezone.utc
    )

    try:
        export_bytes = (
            JsonExportService
            .build_export_bytes(
                exported_at=exported_at
            )
        )

        export_file_name = (
            JsonExportService
            .build_export_file_name(
                exported_at=exported_at
            )
        )

    except JsonExportError as error:
        response = Response(
            (
                "JSON export failed: "
                f"{error}"
                "\n"
            ),
            status=500,
            content_type=(
                "text/plain; charset=utf-8"
            ),
        )

        response.headers[
            "Cache-Control"
        ] = "no-store, max-age=0"

        response.headers[
            "Pragma"
        ] = "no-cache"

        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        return response

    response = Response(
        export_bytes,
        status=200,
        content_type=(
            "application/json; charset=utf-8"
        ),
    )

    response.headers[
        "Content-Disposition"
    ] = (
        "attachment; "
        f'filename="{export_file_name}"'
    )

    response.headers[
        "Cache-Control"
    ] = "no-store, max-age=0"

    response.headers[
        "Pragma"
    ] = "no-cache"

    response.headers[
        "Expires"
    ] = "0"

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    return response