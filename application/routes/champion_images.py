from flask import (
    Blueprint,
    Response,
    abort,
    send_file,
)

from application.services.champion_reference_image_service import (
    ChampionReferenceImageError,
    ChampionReferenceImageService,
)


champion_images_bp = Blueprint(
    "champion_images",
    __name__,
)


PLACEHOLDER_SVG = """\
<svg
    xmlns="http://www.w3.org/2000/svg"
    width="128"
    height="128"
    viewBox="0 0 128 128"
    role="img"
    aria-label="Champion image unavailable"
>
    <rect
        width="128"
        height="128"
        rx="12"
        fill="#e5e7eb"
    />
    <circle
        cx="64"
        cy="46"
        r="20"
        fill="#9ca3af"
    />
    <path
        d="M28 108c3-25 17-38 36-38s33 13 36 38"
        fill="#9ca3af"
    />
    <text
        x="64"
        y="121"
        text-anchor="middle"
        font-family="sans-serif"
        font-size="10"
        fill="#374151"
    >
        Champion
    </text>
</svg>
"""


def _placeholder_response():
    """
    Return a controlled inline SVG placeholder.
    """

    return Response(
        PLACEHOLDER_SVG,
        status=200,
        mimetype="image/svg+xml",
        headers={
            "Cache-Control": (
                "no-store"
            ),
        },
    )


@champion_images_bp.route(
    "/champions/images/<string:image_filename>",
    methods=[
        "GET",
    ],
)
def champion_image(
    image_filename,
):
    """
    Return one validated local champion image.

    Invalid filenames return 404. Missing, damaged, or otherwise
    unavailable local images return a controlled SVG placeholder.
    """

    image_service = (
        ChampionReferenceImageService()
    )

    try:
        image_result = (
            image_service.resolve_image(
                image_filename
            )
        )

    except ChampionReferenceImageError:
        abort(
            404
        )

    except Exception:
        return _placeholder_response()

    if (
        not isinstance(
            image_result,
            dict,
        )
        or image_result.get(
            "placeholder",
            True,
        )
    ):
        return _placeholder_response()

    image_file = image_result.get(
        "image_file"
    )

    if image_file is None:
        return _placeholder_response()

    try:
        return send_file(
            image_file,
            mimetype="image/png",
            as_attachment=False,
            conditional=True,
        )

    except (
        OSError,
        TypeError,
        ValueError,
    ):
        return _placeholder_response()