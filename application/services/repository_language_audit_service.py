from pathlib import Path
import re


class RepositoryLanguageAuditService:
    """
    Scans project-owned source files for Norwegian prose that must
    be converted to English during Step 10.

    The audit intentionally ignores generated directories, binary
    assets, unsupported file types, and explicitly allowlisted
    fixtures or phrases.

    Only distinctive Norwegian words and phrases are included in
    the detection vocabulary. Technical words that are valid in
    both English and Norwegian are intentionally excluded to avoid
    false positives.
    """

    EXCLUDED_DIRECTORY_NAMES = frozenset(
        {
            ".git",
            ".venv",
            "build",
            "dist",
            "__pycache__",
        }
    )

    SUPPORTED_FILE_SUFFIXES = frozenset(
        {
            ".css",
            ".html",
            ".js",
            ".json",
            ".md",
            ".py",
            ".spec",
            ".txt",
        }
    )

    DOCUMENTATION_FILE_NAMES = frozenset(
        {
            "README.md",
        }
    )

    NORWEGIAN_TERMS = (
        "kunne ikke",
        "innstillinger",
        "programmet",
        "avsluttes",
        "avslutt",
        "oppretter",
        "opprettes",
        "opprettet",
        "opprett",
        "personer",
        "ingen",
        "ennå",
        "uten",
        "internett",
        "tilbake",
        "lagre",
        "lagret",
        "erstatt",
        "fjern",
        "fjernet",
        "nøkkel",
        "nøkkelen",
        "kryptert",
        "bruker",
        "brukeren",
        "sikkerhet",
        "oppdater",
        "oppdateres",
        "oppdatering",
        "oppdatert",
        "mangler",
        "manglende",
        "tilgjengelig",
        "medfølgende",
        "datasett",
        "lokalt",
        "kilde",
        "vellykket",
        "feilet",
        "feil",
        "slett",
        "gjenopprett",
        "importer",
        "eksporter",
        "konto",
        "kontoer",
        "synkroniser",
        "synkroniseres",
        "synkronisering",
        "sist",
        "navn",
        "bilde",
        "bilder",
        "vises",
        "finnes",
        "fortsatt",
        "brukes",
        "beholdes",
        "eldre",
        "nyeste",
        "antall",
        "størrelse",
        "oppstart",
        "automatisk",
        "manuelt",
        "kontrollert",
        "ukjent",
        "advarsel",
        "melding",
        "meldinger",
        "juridisk",
        "informasjon",
        "grafiske",
        "rettigheter",
        "dataene",
        "fungerer",
        "koblet",
        "frakoblet",
        "handlinger",
        "velg",
        "valgt",
        "bekreft",
        "bekreftelse",
        "avbryt",
        "last ned",
        "last opp",
        "nedlasting",
        "opplasting",
        "påkrevd",
        "ugyldig",
        "gyldig",
        "tomme",
        "klarte ikke",
        "prøv igjen",
        "allerede",
        "registrert",
        "registrere",
        "endre",
        "endret",
        "endringer",
        "sammenlign",
        "bevar",
        "bevares",
        "hent",
        "hentes",
        "venter",
        "pågår",
        "ferdig",
        "fullført",
        "avbrutt",
        "adgang",
        "tilgang",
        "mappe",
        "filen",
        "filene",
        "skadet",
        "trygt",
        "trygg",
        "hemmeligheter",
        "brukerdata",
        "programfil",
        "programfiler",
        "vedlikehold",
        "administrer",
        "administrasjon",
        "åpne",
        "lukk",
        "lukker",
        "lukket",
        "startet",
        "stopp",
        "stopper",
        "stanset",
        "sammen",
        "samme",
        "annen",
        "andre",
        "denne",
        "disse",
        "dette",
        "hvis",
        "dersom",
        "fordi",
        "etter",
        "før",
        "eller",
        "også",
        "ikke",
    )

    def __init__(
        self,
        project_root,
        allowlisted_paths=(),
        allowlisted_phrases=(),
    ):
        self.project_root = Path(
            project_root
        ).resolve()

        self.allowlisted_paths = frozenset(
            self._normalize_relative_path(
                path
            )
            for path in allowlisted_paths
        )

        self.allowlisted_phrases = tuple(
            str(phrase)
            for phrase in allowlisted_phrases
            if str(phrase)
        )

    def audit(self):
        """
        Return deterministic language findings sorted by path and
        line number.
        """

        findings = []

        for file_path in self._get_source_files():
            relative_path = (
                file_path
                .relative_to(
                    self.project_root
                )
                .as_posix()
            )

            if relative_path in self.allowlisted_paths:
                continue

            try:
                content = file_path.read_text(
                    encoding="utf-8"
                )
            except (
                OSError,
                UnicodeDecodeError,
            ):
                continue

            category = self._classify_path(
                relative_path
            )

            for line_number, line in enumerate(
                content.splitlines(),
                start=1,
            ):
                if self._is_allowlisted_line(
                    line
                ):
                    continue

                matched_terms = (
                    self._find_matching_terms(
                        line
                    )
                )

                if not matched_terms:
                    continue

                findings.append(
                    {
                        "path": relative_path,
                        "line_number": line_number,
                        "category": category,
                        "matched_terms": (
                            matched_terms
                        ),
                        "line": line.strip(),
                    }
                )

        return sorted(
            findings,
            key=lambda finding: (
                finding["path"],
                finding["line_number"],
            ),
        )

    def _get_source_files(self):
        """
        Return supported project files in deterministic path order.
        """

        file_paths = []

        for file_path in self.project_root.rglob(
            "*"
        ):
            if not file_path.is_file():
                continue

            relative_parts = (
                file_path
                .relative_to(
                    self.project_root
                )
                .parts
            )

            if any(
                part
                in self.EXCLUDED_DIRECTORY_NAMES
                for part in relative_parts
            ):
                continue

            if (
                file_path.suffix.lower()
                not in self.SUPPORTED_FILE_SUFFIXES
            ):
                continue

            file_paths.append(
                file_path
            )

        return sorted(
            file_paths,
            key=lambda path: (
                path
                .relative_to(
                    self.project_root
                )
                .as_posix()
            ),
        )

    def _find_matching_terms(
        self,
        line,
    ):
        """
        Return unique Norwegian terms ordered by their position in
        the line.
        """

        normalized_line = line.casefold()
        matches = []

        for definition_order, term in enumerate(
            self.NORWEGIAN_TERMS
        ):
            match = re.search(
                self._build_term_pattern(
                    term
                ),
                normalized_line,
                flags=re.IGNORECASE,
            )

            if match is None:
                continue

            matches.append(
                (
                    match.start(),
                    definition_order,
                    term,
                )
            )

        matches.sort(
            key=lambda match: (
                match[0],
                match[1],
            )
        )

        return tuple(
            match[2]
            for match in matches
        )

    def _is_allowlisted_line(
        self,
        line,
    ):
        """
        Return whether a complete line contains an approved phrase.
        """

        return any(
            phrase in line
            for phrase in self.allowlisted_phrases
        )

    @classmethod
    def _classify_path(
        cls,
        relative_path,
    ):
        """
        Classify a finding according to its repository location.
        """

        path = Path(
            relative_path
        )

        normalized_path = (
            path.as_posix()
        )

        if normalized_path.startswith(
            "application/templates/"
        ):
            return "user_facing"

        if normalized_path.startswith(
            "tests/"
        ):
            return "test_only"

        if (
            path.name
            in cls.DOCUMENTATION_FILE_NAMES
            or path.suffix.lower()
            in {
                ".md",
                ".txt",
            }
        ):
            return "documentation"

        return "developer_facing"

    @staticmethod
    def _build_term_pattern(
        term,
    ):
        """
        Build a Unicode-aware whole-term matching expression.
        """

        escaped_term = re.escape(
            term
        )

        return (
            rf"(?<!\w)"
            rf"{escaped_term}"
            rf"(?!\w)"
        )

    @staticmethod
    def _normalize_relative_path(
        path,
    ):
        """
        Normalize allowlisted paths to repository-style separators.
        """

        return Path(
            str(path)
        ).as_posix()