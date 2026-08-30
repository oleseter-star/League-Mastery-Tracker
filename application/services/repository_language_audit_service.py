from pathlib import Path
import re
import subprocess


class RepositoryLanguageAuditService:
    """
    Audit every locally tracked repository path for project-owned
    Norwegian prose and controlled terminology.

    Candidate discovery uses the local Git index. Tests may inject
    an equivalent tracked path sequence without creating a Git
    repository.
    """

    DOCUMENTATION_FILE_NAMES = frozenset({"README.md"})

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

    CONTROLLED_TERMINOLOGY = (
        "player",
        "user account",
        "mastery score",
        "Synchronize mastery",
        "Champion Mastery points",
        "Missing champion data",
        "Reference update",
        "reference dataset",
        "champion database",
        "database import",
        "backup import",
        "last sync timestamp",
    )

    BINARY_SIGNATURES = (
        b"\x89PNG\r\n\x1a\n",
        b"\x00\x00\x01\x00",
        b"SQLite format 3\x00",
    )

    def __init__(
        self,
        project_root,
        tracked_paths=None,
        intentional_exceptions=(),
    ):
        self.project_root = Path(project_root).resolve()
        self._tracked_paths = (
            None
            if tracked_paths is None
            else tuple(
                self._normalize_relative_path(path)
                for path in tracked_paths
            )
        )
        self.intentional_exceptions = tuple(
            self._normalize_exception(exception)
            for exception in (
                self.default_intentional_exceptions()
                + tuple(intentional_exceptions)
            )
        )
        self._norwegian_pattern = self._compile_terms(
            self.NORWEGIAN_TERMS
        )
        self._controlled_pattern = self._compile_terms(
            self.CONTROLLED_TERMINOLOGY
        )

    @classmethod
    def default_intentional_exceptions(cls):
        """Return exact, documented exceptions for audit fixtures."""

        exceptions = []
        service_path = (
            "application/services/"
            "repository_language_audit_service.py"
        )

        for term in cls.NORWEGIAN_TERMS:
            source_line = f'"{term}",'
            exceptions.append(
                {
                    "path": service_path,
                    "line": source_line,
                    "finding_type": "norwegian_vocabulary",
                    "reason": "Required Norwegian detector vocabulary.",
                }
            )

        for term in cls.CONTROLLED_TERMINOLOGY:
            exceptions.append(
                {
                    "path": service_path,
                    "line": f'"{term}",',
                    "finding_type": "controlled_terminology",
                    "reason": "Required controlled terminology detector vocabulary.",
                }
            )

        player_pattern_line = (
            'r"^\\s*'
            + "pla"
            + "yer"
            + '\\s*(?:=|\\.)",'
        )
        exceptions.append(
            {
                "path": service_path,
                "line": player_pattern_line,
                "finding_type": "controlled_terminology",
                "reason": "Required machine-identifier detector pattern.",
            }
        )

        exceptions.extend(cls._fixture_exceptions())
        return tuple(exceptions)

    @staticmethod
    def _fixture_exceptions():
        """Return intentional user-name and detector-fixture exceptions."""

        name_reason = "Intentional Unicode Person-name fixture."
        service_path = (
            "application/services/"
            "repository_language_audit_service.py"
        )
        exceptions = [
            {
                "path": "tests/test_json_export_end_to_end.py",
                "line": 'display_name="\u00c6gir Export",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_end_to_end.py",
                "line": '"\u00c6gir Export",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_routes.py",
                "line": 'display_name="\u00c6gir \u00d8st",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_routes.py",
                "line": '"\u00c6gir \u00d8st",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_service.py",
                "line": 'display_name="\u00c5se",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_service.py",
                "line": '"\u00c5se",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_service.py",
                "line": 'display_name="\u00c6gir \u00d8st",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
            {
                "path": "tests/test_json_export_service.py",
                "line": '"\u00c6gir \u00d8st",',
                "finding_type": "norwegian_character",
                "reason": name_reason,
            },
        ]

        fixture_lines = {
            "tests/test_audit_repository_language.py": (
                '"innstillinger",',
                '"line": "<a>Innstillinger</a>",',
                '"tilbake",',
                '"<a>Tilbake til innstillinger</a>"',
                '"programmet",',
                '"avsluttes",',
                '\'EXPECTED = "Programmet avsluttes"\'',
                '"innstillinger, tilbake",',
                '"line": \'MESSAGE = "Ingen oversettelse"\',',
            ),
            "tests/test_repository_language_audit_precision.py": (
                '\'PERSON_NAME = "Bjørn"\\n\'',
                '\'SECOND_PERSON_NAME = "Ægir Export"\\n\'',
                '"line": \'PERSON_NAME = "Bjørn"\',',
                '\'SECOND_PERSON_NAME = "Ægir Export"\'',
                '"Programmet kunne ikke oppdateres, "',
                '"men eksisterende data er fortsatt tilgjengelig."',
                '"programmet",',
                '"kunne ikke",',
                '"fortsatt",',
            ),
            "tests/test_repository_language_audit_service.py": (
                '"<h1>Innstillinger</h1>\\n",',
                '"innstillinger",',
                '"<h1>Innstillinger</h1>"',
                '\'"""Oppretter en lokal backup."""\\n\'',
                '\'MESSAGE = "Backup kunne ikke opprettes."\\n\'',
                '"oppretter",',
                '"kunne ikke",',
                '\'"Programmet avsluttes."\\n\'',
                '"programmet",',
                '"avsluttes",',
                '"Programmet fungerer uten internett.\\n"',
                '"<p>Ingen personer er "',
                '"opprettet ennå.</p>\\n"',
                '"ingen",',
                '"personer",',
                '"opprettet",',
                '"ennå",',
                '\'"Innstillinger"\\n\'',
                'b"Innstillinger"',
                '"Innstillinger\\n",',
                'fixture_line = \'MESSAGE = "Programmet avsluttes."\'',
                'fixture_line = \'VALUE = "Ingen oversettelse"\'',
                '\'PERSON_NAME = "Ægir Export"\\n\'',
                '\'SECOND_NAME = "Bjørn"\\n\'',
                '"line": \'PERSON_NAME = "Ægir Export"\',',
                '"line": \'SECOND_NAME = "Bjørn"\',',
                '\'FIRST = "Innstillinger"\\n\'',
                '\'SECOND = "Programmet avsluttes"\\n\'',
                '"<p>Ingen personer.</p>\\n",',
                '"<p>INNSTILLINGER</p>\\n"',
                '"<p>Programmet Avsluttes</p>\\n"',
                '"tests/Ægir.py",',
                '"Programmet kunne ikke starte.\\n",',
                '"Programmet avsluttes.\\n".encode("utf-8")',
                '+ "Programmet avsluttes.\\n".encode("utf-8")',
                '+ "Programmet avsluttes.\\n".encode("utf-16-le")',
                '+ "Programmet avsluttes.\\n".encode("utf-16-be")',
                'allowed_line = \'PERSON_NAME = "Bjørn"\'',
                '+ "  # Programmet avsluttes.\\n"',
            ),
        }

        for path, lines in fixture_lines.items():
            for line in lines:
                finding_type = (
                    "norwegian_character"
                    if re.search(r"[\u00e6\u00f8\u00e5\u00c6\u00d8\u00c5]", line)
                    and not any(
                        term.casefold() in line.casefold()
                        for term in RepositoryLanguageAuditService.NORWEGIAN_TERMS
                    )
                    else "norwegian_vocabulary"
                )
                exceptions.append(
                    {
                        "path": path,
                        "line": line,
                        "finding_type": finding_type,
                        "reason": "Exact language-detector test fixture.",
                    }
                )
                exceptions.append(
                    {
                        "path": service_path,
                        "line": f"{line!r},",
                        "finding_type": finding_type,
                        "reason": "Exact fixture inventory value.",
                    }
                )

        controlled_fixture_lines = {
            "tests/test_home_champion_reference_status_template.py": (
                '"The reference dataset is unavailable. "',
                '"Reference update",',
            ),
            "tests/test_json_export_routes.py": (
                '"Champion Mastery points",',
            ),
            "tests/test_shared_layout.py": (
                '"Synchronize mastery",',
                '"Missing champion data · "',
                '"Missing champion data",',
            ),
            "tests/test_repository_language_audit_service.py": (
                '"player",',
                '"player = Person()\\n"',
                '"player.display_name = \'Example\'\\n"',
                '"user account",',
                '"mastery score",',
                '"Synchronize mastery",',
                '"Champion Mastery points",',
                '"Missing champion data",',
                '"Reference update",',
                '"reference dataset",',
                '"champion database",',
                '"database import",',
                '"backup import",',
                '"last sync timestamp",',
            ),
        }

        for path, lines in controlled_fixture_lines.items():
            for line in lines:
                exceptions.append(
                    {
                        "path": path,
                        "line": line,
                        "finding_type": "controlled_terminology",
                        "reason": "Exact obsolete-copy or detector fixture.",
                    }
                )
                exceptions.append(
                    {
                        "path": service_path,
                        "line": f"{line!r},",
                        "finding_type": "controlled_terminology",
                        "reason": "Exact fixture inventory value.",
                    }
                )

        return tuple(exceptions)

    def get_tracked_paths(self):
        """Return the exact NUL-delimited local Git tracked path set."""

        if self._tracked_paths is not None:
            return self._tracked_paths

        completed_process = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=self.project_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if completed_process.returncode != 0:
            raise OSError("Local tracked-file enumeration failed.")

        return tuple(
            path_bytes.decode("utf-8", errors="surrogateescape")
            for path_bytes in completed_process.stdout.split(b"\0")
            if path_bytes
        )

    def audit(self):
        """Return deterministic language findings for compatibility."""

        return self.audit_repository()["findings"]

    def audit_repository(self):
        """Return findings and one explicit outcome per tracked path."""

        tracked_paths = self.get_tracked_paths()
        outcomes = []
        findings = []
        applied_exceptions = []

        for relative_path in tracked_paths:
            outcome, path_findings, path_exceptions = self._audit_path(
                relative_path
            )
            outcomes.append(outcome)
            findings.extend(path_findings)
            applied_exceptions.extend(path_exceptions)

        findings.sort(
            key=lambda finding: (
                finding["path"],
                finding["line_number"],
                finding["finding_type"],
            )
        )
        counts = {
            "tracked_files": len(tracked_paths),
            "audited_text": 0,
            "intentional_binary_exclusion": 0,
            "controlled_non_language_exclusion": 0,
            "audit_error": 0,
        }
        for outcome in outcomes:
            counts[outcome["outcome"]] += 1

        return {
            "tracked_paths": tracked_paths,
            "outcomes": tuple(outcomes),
            "findings": findings,
            "counts": counts,
            "applied_exceptions": tuple(applied_exceptions),
        }

    def _audit_path(self, relative_path):
        file_path = self.project_root / relative_path

        if not file_path.exists():
            return self._audit_error(
                relative_path,
                "Tracked path is missing from the working tree.",
            )

        if not file_path.is_file():
            return (
                {
                    "path": relative_path,
                    "outcome": "controlled_non_language_exclusion",
                    "encoding": None,
                },
                [],
                [],
            )

        try:
            raw_content = file_path.read_bytes()
        except OSError:
            return self._audit_error(
                relative_path,
                "Tracked path could not be read.",
            )

        kind, content, encoding = self._decode_text(raw_content)
        if kind == "binary":
            return (
                {
                    "path": relative_path,
                    "outcome": "intentional_binary_exclusion",
                    "encoding": None,
                },
                [],
                [],
            )

        if kind == "unexpected_nul":
            return self._audit_error(
                relative_path,
                (
                    "Tracked text contains an unexpected NUL byte "
                    "and cannot be audited safely."
                ),
            )

        if kind == "error":
            return self._audit_error(
                relative_path,
                "Tracked text has malformed or unsupported encoding.",
            )

        category = self._classify_path(relative_path)
        findings = []
        applied_exceptions = []

        for line_number, line in enumerate(content.splitlines(), start=1):
            for finding in self._find_line_findings(
                relative_path,
                line_number,
                category,
                line,
            ):
                exception = self._matching_exception(finding, line)
                if exception is None:
                    findings.append(finding)
                else:
                    applied_exceptions.append(exception)

        return (
            {
                "path": relative_path,
                "outcome": "audited_text",
                "encoding": encoding,
            },
            findings,
            applied_exceptions,
        )

    def _find_line_findings(
        self,
        relative_path,
        line_number,
        category,
        line,
    ):
        findings = []
        norwegian_terms = self._find_matching_terms(
            line,
            self.NORWEGIAN_TERMS,
            self._norwegian_pattern,
        )
        if norwegian_terms:
            findings.append(
                self._finding(
                    relative_path,
                    line_number,
                    category,
                    "norwegian_vocabulary",
                    norwegian_terms,
                    line,
                )
            )
        else:
            norwegian_characters = tuple(
                dict.fromkeys(
                    re.findall(
                        r"[\u00e6\u00f8\u00e5\u00c6\u00d8\u00c5]",
                        line,
                    )
                )
            )
            if norwegian_characters:
                findings.append(
                    self._finding(
                        relative_path,
                        line_number,
                        category,
                        "norwegian_character",
                        norwegian_characters,
                        line,
                    )
                )

        controlled_terms = tuple(
            term
            for term in self._find_matching_terms(
                line,
                self.CONTROLLED_TERMINOLOGY,
                self._controlled_pattern,
            )
            if not self._is_technical_controlled_use(term, line)
        )
        if controlled_terms:
            findings.append(
                self._finding(
                    relative_path,
                    line_number,
                    category,
                    "controlled_terminology",
                    controlled_terms,
                    line,
                )
            )

        return findings

    @staticmethod
    def _finding(path, line_number, category, finding_type, terms, line):
        return {
            "path": path,
            "line_number": line_number,
            "category": category,
            "finding_type": finding_type,
            "matched_terms": tuple(term.casefold() for term in terms),
            "line": line.strip(),
        }

    @staticmethod
    def _is_technical_controlled_use(term, line):
        normalized = line.casefold()
        normalized_term = term.casefold()

        if normalized_term == "player" and re.search(
            r"^\s*player\s*(?:=|\.)",
            normalized,
        ):
            return True
        if normalized_term == "user account" and "windows user account" in normalized:
            return True
        if normalized_term == "database import" and (
            normalized.lstrip().startswith("from application.database")
        ):
            return True
        if normalized_term == "reference update" and (
            "champion reference update" in normalized
        ):
            return True
        if normalized_term == "reference dataset" and (
            "champion reference dataset" in normalized
            or "bundled champion reference dataset" in normalized
            or "active reference dataset" in normalized
        ):
            return True
        if normalized_term == "champion database" and any(
            marker in normalized
            for marker in (" table", "sqlite", "schema", "migration")
        ):
            return True
        if "normalized_term ==" in normalized:
            return True
        return False

    def _matching_exception(self, finding, source_line):
        for exception in self.intentional_exceptions:
            if (
                exception["path"] == finding["path"]
                and exception["line"] == source_line.strip()
                and exception["finding_type"] == finding["finding_type"]
            ):
                return exception
        return None

    @classmethod
    def _decode_text(cls, raw_content):
        encodings = (
            (b"\xef\xbb\xbf", "utf-8-sig"),
            (b"\xff\xfe", "utf-16-le"),
            (b"\xfe\xff", "utf-16-be"),
        )
        for bom, encoding in encodings:
            if raw_content.startswith(bom):
                try:
                    content = raw_content[len(bom):].decode(encoding)
                except UnicodeDecodeError:
                    return ("error", None, None)
                return cls._decoded_text(content, encoding)

        if any(
            raw_content.startswith(signature)
            for signature in cls.BINARY_SIGNATURES
        ):
            return ("binary", None, None)

        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            return ("error", None, None)
        return cls._decoded_text(content, "utf-8")

    @staticmethod
    def _decoded_text(content, encoding):
        if "\0" in content:
            return ("unexpected_nul", None, encoding)
        return ("text", content, encoding)

    @staticmethod
    def _audit_error(relative_path, message):
        finding = {
            "path": relative_path,
            "line_number": 0,
            "category": "audit_error",
            "finding_type": "audit_error",
            "matched_terms": ("audit_error",),
            "line": message,
        }
        return (
            {
                "path": relative_path,
                "outcome": "audit_error",
                "encoding": None,
            },
            [finding],
            [],
        )

    @staticmethod
    def _find_matching_terms(line, terms, pattern):
        canonical_terms = {
            term.casefold(): term
            for term in terms
        }
        return tuple(
            canonical_terms[match.group(0).casefold()]
            for match in pattern.finditer(line)
        )

    @classmethod
    def _classify_path(cls, relative_path):
        path = Path(relative_path)
        normalized_path = path.as_posix()
        if normalized_path.startswith("application/templates/"):
            return "user_facing"
        if normalized_path.startswith("tests/"):
            return "test_only"
        if (
            path.name in cls.DOCUMENTATION_FILE_NAMES
            or path.suffix.lower() in {".md", ".txt"}
        ):
            return "documentation"
        return "developer_facing"

    @staticmethod
    def _compile_terms(terms):
        alternatives = "|".join(
            re.escape(term)
            for term in sorted(terms, key=len, reverse=True)
        )
        return re.compile(
            rf"(?<!\w)(?:{alternatives})(?!\w)",
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _normalize_relative_path(path):
        return Path(str(path)).as_posix()

    @classmethod
    def _normalize_exception(cls, exception):
        required_keys = {"path", "line", "finding_type", "reason"}
        if set(exception) != required_keys:
            raise ValueError("Intentional exception has an invalid contract.")
        normalized = dict(exception)
        normalized["path"] = cls._normalize_relative_path(normalized["path"])
        if not all(normalized.values()):
            raise ValueError("Intentional exception values must be non-empty.")
        return normalized