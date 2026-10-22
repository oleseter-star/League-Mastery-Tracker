"""
Names for match history queues and patches.

Riot's game data records a patch by its game version (15.x in 2025,
16.x in 2026), while Riot announces the same patches as 25.x and 26.x.
Patches are stored as the game version records them and shown the way
Riot announces them.
"""


RANKED_SOLO_DUO = 420
RANKED_FLEX = 440
CLASH = 700

QUEUE_NAMES = {
    RANKED_SOLO_DUO: "Ranked Solo/Duo",
    RANKED_FLEX: "Ranked Flex",
    CLASH: "Clash",
}

MODE_QUEUE_IDS = {
    "solo": RANKED_SOLO_DUO,
    "flex": RANKED_FLEX,
    "clash": CLASH,
}

# Ranked 5s (weekend premade ranked) is imported through Riot's "ranked"
# match type, but its queue ID is not known yet. Add it here with its mode
# names once probe_match_history.py has reported it.
UNKNOWN_MODES = {
    "5s": "Ranked 5s",
    "fives": "Ranked 5s",
}

# Game versions from this major onwards are announced ten higher:
# game version 15.21 is patch 25.21, and 16.18 is patch 26.18.
FIRST_YEAR_NAMED_MAJOR = 15
YEAR_NAME_OFFSET = 10


def queue_label(queue_id):
    return QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")


def queue_id_for_mode(mode):
    """
    Return the queue ID for a mode name such as "solo" or "flex".
    """

    normalized = str(mode or "").strip().lower()

    if normalized in MODE_QUEUE_IDS:
        return MODE_QUEUE_IDS[normalized]

    if normalized in UNKNOWN_MODES:
        raise ValueError(
            f"The {UNKNOWN_MODES[normalized]} queue ID is not known yet. "
            "Run probe_match_history.py; it reports it under "
            "\"Other ranked games\"."
        )

    raise ValueError(
        f"Unknown mode {mode!r}. Use one of: "
        f"{', '.join(sorted(MODE_QUEUE_IDS))}."
    )


def patch_from_game_version(game_version):
    """
    Return "major.minor" from a game version such as "16.18.712.3456".
    """

    parts = str(game_version or "").split(".")

    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None

    return f"{int(parts[0])}.{int(parts[1])}"


def patch_sort_key(patch):
    major, _, minor = str(patch).partition(".")

    try:
        return (int(major), int(minor))
    except ValueError:
        return (0, 0)


def display_patch(patch):
    """
    Show a stored patch the way Riot announces it, for example 16.18 as 26.18.
    """

    if patch is None:
        return "Unknown"

    major, minor = patch_sort_key(patch)

    if major >= FIRST_YEAR_NAMED_MAJOR:
        major += YEAR_NAME_OFFSET

    return f"{major}.{minor}"


def parse_patch(text):
    """
    Turn a typed patch, either "26.18" or "16.18", into the stored form.
    """

    major_text, separator, minor_text = str(text or "").strip().partition(".")

    if not separator or not major_text.isdigit() or not minor_text.isdigit():
        raise ValueError(f"Expected a patch such as 26.18, got {text!r}.")

    major = int(major_text)

    if major >= FIRST_YEAR_NAMED_MAJOR + YEAR_NAME_OFFSET:
        major -= YEAR_NAME_OFFSET

    return f"{major}.{int(minor_text)}"


def parse_patch_selection(values, available_patches):
    """
    Expand typed patches into stored patches.

    Each value is a patch ("26.18"), a comma-separated list
    ("26.17,26.18"), or an inclusive range ("26.12-26.18") that selects
    every stored patch in between.
    """

    selected = []

    for value in values:
        for part in str(value).split(","):
            part = part.strip()

            if not part:
                continue

            first, separator, last = part.partition("-")

            if separator:
                low = patch_sort_key(parse_patch(first))
                high = patch_sort_key(parse_patch(last))

                if low > high:
                    low, high = high, low

                selected.extend(
                    patch
                    for patch in available_patches
                    if low <= patch_sort_key(patch) <= high
                )
            else:
                selected.append(parse_patch(part))

    return tuple(sorted(set(selected), key=patch_sort_key, reverse=True))
