import sys

from application.services.champion_reference_bundle_build_service import (
    ChampionReferenceBundleBuildError,
    ChampionReferenceBundleBuildService,
)


ERROR_MESSAGE = (
    "The bundled champion reference dataset "
    "could not be built."
)


def _get_build_summary(
    result,
):
    """
    Validate the safe build summary fields.

    The complete dataset has already been validated by the dataset
    build service. This command validates only the metadata required
    for its user-facing console summary.
    """

    if not isinstance(
        result,
        dict,
    ):
        raise ValueError(
            "Invalid build result."
        )

    dataset = result.get(
        "dataset"
    )

    if not isinstance(
        dataset,
        dict,
    ):
        raise ValueError(
            "Invalid dataset result."
        )

    manifest = dataset.get(
        "manifest"
    )

    if not isinstance(
        manifest,
        dict,
    ):
        raise ValueError(
            "Invalid dataset manifest."
        )

    version = manifest.get(
        "data_dragon_version"
    )

    locale = manifest.get(
        "locale"
    )

    champion_count = manifest.get(
        "champion_count"
    )

    if (
        not isinstance(
            version,
            str,
        )
        or not version.strip()
    ):
        raise ValueError(
            "Invalid Data Dragon version."
        )

    if (
        not isinstance(
            locale,
            str,
        )
        or not locale.strip()
    ):
        raise ValueError(
            "Invalid locale."
        )

    if (
        isinstance(
            champion_count,
            bool,
        )
        or not isinstance(
            champion_count,
            int,
        )
        or champion_count <= 0
    ):
        raise ValueError(
            "Invalid champion count."
        )

    return {
        "data_dragon_version": (
            version.strip()
        ),
        "locale": locale.strip(),
        "champion_count": (
            champion_count
        ),
    }


def main():
    """
    Build the bundled champion reference dataset.

    Returns zero after a successful build and one after any
    controlled or unexpected failure.
    """

    try:
        result = (
            ChampionReferenceBundleBuildService()
            .build_bundled_dataset()
        )

        summary = _get_build_summary(
            result
        )

    except (
        ChampionReferenceBundleBuildError,
        KeyError,
        TypeError,
        ValueError,
    ):
        print(
            ERROR_MESSAGE,
            file=sys.stderr,
        )

        return 1

    except Exception:
        print(
            ERROR_MESSAGE,
            file=sys.stderr,
        )

        return 1

    print(
        "The bundled champion reference dataset "
        "was built."
    )

    print(
        "Data Dragon version: "
        f'{summary["data_dragon_version"]}'
    )

    print(
        "Locale: "
        f'{summary["locale"]}'
    )

    print(
        "Champion count: "
        f'{summary["champion_count"]}'
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )