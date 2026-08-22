from collections.abc import Mapping
from threading import RLock

from application.services.json_import_execution_service import (
    JsonImportExecutionError,
    JsonImportExecutionService,
)
from application.services.json_import_plan_service import (
    JsonImportPlanError,
    JsonImportPlanService,
)
from application.services.json_import_preview_service import (
    JsonImportPreviewError,
    JsonImportPreviewService,
)
from application.services.json_import_read_service import (
    JsonImportReadError,
    JsonImportReadService,
)
from application.services.json_import_staging_service import (
    JsonImportStagingError,
    JsonImportStagingService,
)


class JsonImportWorkflowError(RuntimeError):
    """
    Raised when a JSON import workflow stage cannot be completed.

    The stage attribute identifies where the workflow stopped.

    A blocking preview or staging summary may be attached so a
    future route can render useful information without trusting
    client-provided state.
    """

    def __init__(
        self,
        message,
        *,
        stage,
        preview=None,
        staging=None,
    ):
        super().__init__(
            message
        )

        self.stage = stage
        self.preview = preview
        self.staging = staging


class JsonImportWorkflowService:
    """
    Coordinates the complete JSON import safety sequence.

    Routes and other callers should use this service rather than
    coordinating read, staging, preview, plan, and execution
    independently.

    The preferred browser workflow is:

    1. stage_stream()
    2. inspect_staged()
    3. execute_staged()

    Direct stream and file methods remain available for tests and
    trusted local tooling.
    """

    EXECUTION_CONFIRMATION_TEXT = "IMPORT"

    _STAGED_OPERATION_LOCK = RLock()

    @classmethod
    def stage_stream(
        cls,
        stream,
        file_name,
        max_file_size_bytes=(
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        ),
        expiration_minutes=(
            JsonImportStagingService
            .DEFAULT_EXPIRATION_MINUTES
        ),
    ):
        """
        Validate and privately stage one uploaded JSON file.

        The staged bytes are loaded again from disk before preview
        and plan generation. This verifies that the persisted source
        is the source being shown to the user.

        Staging is serialized with staged execution so a new upload
        cannot replace the active source while it is being consumed.

        No database writes are performed.
        """

        with cls._STAGED_OPERATION_LOCK:
            staging_summary = cls._stage_stream(
                stream=stream,
                file_name=file_name,
                max_file_size_bytes=(
                    max_file_size_bytes
                ),
                expiration_minutes=(
                    expiration_minutes
                ),
            )

            try:
                return cls.inspect_staged(
                    staging_summary[
                        "staging_token"
                    ]
                )

            except JsonImportWorkflowError as error:
                if error.staging is None:
                    error.staging = staging_summary

                raise

    @classmethod
    def inspect_staged(
        cls,
        staging_token,
    ):
        """
        Load, verify, preview, and plan the active staged import.

        The marker, file size, SHA-256, timestamps, format metadata,
        and complete JSON document are revalidated by the staging
        service before database comparison.

        No database writes are performed.
        """

        loaded_staging = cls._load_staged(
            staging_token
        )

        staging_summary = loaded_staging[
            "staging"
        ]

        try:
            prepared_import = (
                cls._prepare_read_result(
                    loaded_staging[
                        "read_result"
                    ]
                )
            )

        except JsonImportWorkflowError as error:
            if error.staging is None:
                error.staging = staging_summary

            raise

        return cls._attach_staging(
            prepared_import=prepared_import,
            staging_summary=staging_summary,
        )

    @classmethod
    def execute_staged(
        cls,
        staging_token,
        confirmation_text,
    ):
        """
        Revalidate and execute the active staged JSON import once.

        Confirmation, staged-file verification, preview, and plan
        validation happen before the source is consumed.

        Immediately before backup and transactional execution, the
        active staging token is cancelled and its source files are
        removed. This is the irreversible consumption boundary. A
        second request using the same token therefore cannot execute
        the import again, including when database execution later
        fails or the original HTTP response is repeated.

        Wrong confirmation and blocking previews do not cross the
        consumption boundary and leave the staged source available.
        """

        with cls._STAGED_OPERATION_LOCK:
            cls._require_execution_confirmation(
                confirmation_text
            )

            prepared_import = cls.inspect_staged(
                staging_token
            )

            try:
                cls._require_executable_prepared_import(
                    prepared_import
                )

            except JsonImportWorkflowError as error:
                if error.staging is None:
                    error.staging = prepared_import.get(
                        "staging"
                    )

                raise

            staging_cleanup = (
                cls._consume_staged_before_execution(
                    staging_token=(
                        staging_token
                    ),
                    staging_summary=(
                        prepared_import[
                            "staging"
                        ]
                    ),
                )
            )

            try:
                execution_result = (
                    cls._execute_prepared_import(
                        prepared_import
                    )
                )

            except JsonImportWorkflowError as error:
                if error.staging is None:
                    error.staging = prepared_import.get(
                        "staging"
                    )

                raise

            return {
                "source": execution_result[
                    "source"
                ],
                "preview": execution_result[
                    "preview"
                ],
                "plan": execution_result[
                    "plan"
                ],
                "execution": execution_result[
                    "execution"
                ],
                "staging": prepared_import[
                    "staging"
                ],
                "staging_cleanup": (
                    staging_cleanup
                ),
            }

    @classmethod
    def cancel_staged(
        cls,
        staging_token,
    ):
        """
        Cancel the active staged import without database changes.
        """

        with cls._STAGED_OPERATION_LOCK:
            try:
                return (
                    JsonImportStagingService
                    .cancel_staged(
                        staging_token
                    )
                )

            except JsonImportStagingError as error:
                raise JsonImportWorkflowError(
                    "The staged JSON import could not be cancelled.",
                    stage="staging",
                ) from error

    @classmethod
    def inspect_stream(
        cls,
        stream,
        file_name,
        max_file_size_bytes=(
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        ),
    ):
        """
        Inspect one uploaded binary stream without staging it.

        A plan is included only when the preview has no blockers.

        Browser routes should normally use stage_stream() instead.
        """

        read_result = cls._read_stream(
            stream=stream,
            file_name=file_name,
            max_file_size_bytes=(
                max_file_size_bytes
            ),
        )

        return cls._prepare_read_result(
            read_result
        )

    @classmethod
    def inspect_file(
        cls,
        file_path,
        max_file_size_bytes=(
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        ),
    ):
        """
        Inspect one local JSON file without database writes.
        """

        read_result = cls._read_file(
            file_path=file_path,
            max_file_size_bytes=(
                max_file_size_bytes
            ),
        )

        return cls._prepare_read_result(
            read_result
        )

    @classmethod
    def execute_stream(
        cls,
        stream,
        file_name,
        confirmation_text,
        max_file_size_bytes=(
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        ),
    ):
        """
        Re-read and execute one uploaded JSON document directly.

        The complete safety chain is rebuilt immediately before
        execution. Inspection results from an earlier request are
        never trusted as executable state.

        Browser routes should normally use execute_staged() instead.
        """

        cls._require_execution_confirmation(
            confirmation_text
        )

        read_result = cls._read_stream(
            stream=stream,
            file_name=file_name,
            max_file_size_bytes=(
                max_file_size_bytes
            ),
        )

        prepared_import = (
            cls._prepare_read_result(
                read_result
            )
        )

        return cls._execute_prepared_import(
            prepared_import
        )

    @classmethod
    def execute_file(
        cls,
        file_path,
        confirmation_text,
        max_file_size_bytes=(
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        ),
    ):
        """
        Re-read and execute one trusted local JSON document.
        """

        cls._require_execution_confirmation(
            confirmation_text
        )

        read_result = cls._read_file(
            file_path=file_path,
            max_file_size_bytes=(
                max_file_size_bytes
            ),
        )

        prepared_import = (
            cls._prepare_read_result(
                read_result
            )
        )

        return cls._execute_prepared_import(
            prepared_import
        )

    @classmethod
    def _stage_stream(
        cls,
        stream,
        file_name,
        max_file_size_bytes,
        expiration_minutes,
    ):
        try:
            return (
                JsonImportStagingService
                .stage_stream(
                    stream=stream,
                    file_name=file_name,
                    max_file_size_bytes=(
                        max_file_size_bytes
                    ),
                    expiration_minutes=(
                        expiration_minutes
                    ),
                )
            )

        except JsonImportStagingError as error:
            raise JsonImportWorkflowError(
                "The JSON import file could not be staged "
                "safely.",
                stage="staging",
            ) from error

    @classmethod
    def _load_staged(
        cls,
        staging_token,
    ):
        try:
            return (
                JsonImportStagingService
                .load_staged(
                    staging_token
                )
            )

        except JsonImportStagingError as error:
            raise JsonImportWorkflowError(
                "The staged JSON import could not be loaded or "
                "verified.",
                stage="staging",
            ) from error

    @classmethod
    def _consume_staged_before_execution(
        cls,
        staging_token,
        staging_summary,
    ):
        """
        Irreversibly consume the active staging token.

        Database backup and execution must not begin unless this
        operation completes. Once it succeeds, replaying the same
        staged request is impossible because the active marker and
        staged source have been removed.
        """

        try:
            cancellation_result = (
                JsonImportStagingService
                .cancel_staged(
                    staging_token
                )
            )

        except JsonImportStagingError as error:
            raise JsonImportWorkflowError(
                "The staged JSON import could not be consumed "
                "safely before execution.",
                stage="staging",
                staging=staging_summary,
            ) from error

        return {
            "cleared": True,
            "consumed": True,
            "error": None,
            "cancelled": (
                cancellation_result[
                    "cancelled"
                ]
            ),
        }

    @classmethod
    def _read_stream(
        cls,
        stream,
        file_name,
        max_file_size_bytes,
    ):
        try:
            return (
                JsonImportReadService
                .read_stream(
                    stream=stream,
                    file_name=file_name,
                    max_file_size_bytes=(
                        max_file_size_bytes
                    ),
                )
            )

        except JsonImportReadError as error:
            raise JsonImportWorkflowError(
                "The JSON import file could not be read or "
                "validated.",
                stage="read",
            ) from error

    @classmethod
    def _read_file(
        cls,
        file_path,
        max_file_size_bytes,
    ):
        try:
            return (
                JsonImportReadService
                .read_file(
                    file_path=file_path,
                    max_file_size_bytes=(
                        max_file_size_bytes
                    ),
                )
            )

        except JsonImportReadError as error:
            raise JsonImportWorkflowError(
                "The JSON import file could not be read or "
                "validated.",
                stage="read",
            ) from error

    @classmethod
    def _prepare_read_result(
        cls,
        read_result,
    ):
        try:
            preview = (
                JsonImportPreviewService
                .build_preview(
                    read_result
                )
            )

        except JsonImportPreviewError as error:
            raise JsonImportWorkflowError(
                "The JSON import preview could not be built.",
                stage="preview",
            ) from error

        plan = None

        if preview["can_import"]:
            try:
                plan = (
                    JsonImportPlanService
                    .build_plan(
                        import_read_result=(
                            read_result
                        ),
                        import_preview=preview,
                    )
                )

            except JsonImportPlanError as error:
                raise JsonImportWorkflowError(
                    "The JSON import plan could not be built.",
                    stage="plan",
                    preview=preview,
                ) from error

        return {
            "source": cls._build_source_summary(
                read_result
            ),
            "preview": preview,
            "plan": plan,
        }

    @classmethod
    def _require_executable_prepared_import(
        cls,
        prepared_import,
    ):
        if not isinstance(
            prepared_import,
            Mapping,
        ):
            raise JsonImportWorkflowError(
                "The prepared JSON import is invalid.",
                stage="execution",
            )

        preview = prepared_import.get(
            "preview"
        )

        plan = prepared_import.get(
            "plan"
        )

        if (
            not isinstance(
                preview,
                Mapping,
            )
            or not preview.get(
                "can_import",
                False,
            )
            or preview.get(
                "blockers"
            )
        ):
            raise JsonImportWorkflowError(
                "The JSON import contains blocking conflicts and "
                "cannot be executed.",
                stage="preview",
                preview=preview,
            )

        if plan is None:
            raise JsonImportWorkflowError(
                "The JSON import has no executable plan.",
                stage="plan",
                preview=preview,
            )

        return preview, plan

    @classmethod
    def _execute_prepared_import(
        cls,
        prepared_import,
    ):
        preview, plan = (
            cls._require_executable_prepared_import(
                prepared_import
            )
        )

        try:
            execution_result = (
                JsonImportExecutionService
                .apply_plan(
                    plan
                )
            )

        except JsonImportExecutionError as error:
            raise JsonImportWorkflowError(
                "The JSON import could not be applied safely.",
                stage="execution",
                preview=preview,
            ) from error

        return {
            "source": prepared_import[
                "source"
            ],
            "preview": preview,
            "plan": plan,
            "execution": execution_result,
        }

    @staticmethod
    def _attach_staging(
        prepared_import,
        staging_summary,
    ):
        return {
            "source": prepared_import[
                "source"
            ],
            "preview": prepared_import[
                "preview"
            ],
            "plan": prepared_import[
                "plan"
            ],
            "staging": dict(
                staging_summary
            ),
        }

    @classmethod
    def _require_execution_confirmation(
        cls,
        confirmation_text,
    ):
        if (
            not isinstance(
                confirmation_text,
                str,
            )
            or confirmation_text
            != cls.EXECUTION_CONFIRMATION_TEXT
        ):
            raise JsonImportWorkflowError(
                "JSON import requires the exact confirmation "
                f'text "{cls.EXECUTION_CONFIRMATION_TEXT}".',
                stage="confirmation",
            )

    @staticmethod
    def _build_source_summary(
        read_result,
    ):
        return {
            "file_name": read_result[
                "file_name"
            ],
            "file_size_bytes": read_result[
                "file_size_bytes"
            ],
            "sha256": read_result[
                "sha256"
            ],
            "format": read_result[
                "format"
            ],
            "format_version": read_result[
                "format_version"
            ],
            "database_schema_version": (
                read_result[
                    "database_schema_version"
                ]
            ),
            "exported_at": read_result[
                "exported_at"
            ],
            "record_counts": dict(
                read_result[
                    "record_counts"
                ]
            ),
        }