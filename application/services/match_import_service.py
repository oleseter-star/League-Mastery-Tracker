import json
import zlib
from datetime import datetime, timezone

import requests

from application.database.database import db
from application.database.models import (
    Match,
    MatchImportState,
    MatchParticipant,
    RiotAccount,
)
from application.services.riot_service import RiotService


class MatchImportError(RuntimeError):
    """
    Raised when a match history import stops early.

    Games imported before the failure stay committed.
    """


class MatchImportService:
    """
    Imports Riot match history for tracked Riot Accounts.

    Imports run only when requested. Each game is stored once, shared by
    every tracked Riot Account in it, and committed on its own so an
    interrupted import keeps its progress.
    """

    # Ranked Solo/Duo, Ranked Flex, Normal Draft, Normal Blind,
    # Quickplay, and ARAM. League Classic and other modes are excluded.
    DEFAULT_QUEUE_IDS = (
        420,
        440,
        400,
        430,
        490,
        450,
    )

    # Guards against endless paging if Riot keeps returning full pages.
    MAX_MATCH_IDS_PER_QUEUE = 10000

    def __init__(
        self,
        riot_service=None,
        clock=None,
    ):
        self.riot_service = riot_service
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).replace(tzinfo=None)
        )

    def _get_riot_service(self):
        if self.riot_service is None:
            self.riot_service = RiotService()

        return self.riot_service

    def import_account(
        self,
        riot_account_id,
        max_new_matches=None,
        queue_ids=DEFAULT_QUEUE_IDS,
        progress=None,
    ):
        """
        Import new games for one Riot Account.

        max_new_matches limits how many games are downloaded in this run.
        progress, when given, is called as progress(done, total).
        """

        account = db.session.get(
            RiotAccount,
            riot_account_id,
        )

        if account is None:
            raise ValueError(
                f"Riot Account with ID {riot_account_id} was not found."
            )

        state = self._get_or_create_state(
            account
        )

        result = {
            "riot_account_id": account.id,
            "imported": 0,
            "linked_existing": 0,
            "unavailable": 0,
            "remaining": 0,
            "puuid_refreshed": False,
            "history_complete": False,
        }

        try:
            new_match_ids, history_reached_end = self._collect_new_match_ids(
                account,
                state,
                tuple(queue_ids),
                result,
            )

            selected_ids = new_match_ids

            if max_new_matches is not None:
                selected_ids = new_match_ids[:max(0, max_new_matches)]

            result["remaining"] = len(new_match_ids) - len(selected_ids)
            tracked_accounts = self._tracked_accounts_by_puuid()

            for done, riot_match_id in enumerate(selected_ids, start=1):
                outcome = self._import_match(
                    account,
                    riot_match_id,
                    tuple(queue_ids),
                    tracked_accounts,
                )
                result[outcome] += 1

                if progress is not None:
                    progress(done, len(selected_ids))

        except requests.RequestException as error:
            db.session.rollback()
            raise MatchImportError(
                self._describe_request_error(error)
            ) from error

        except Exception:
            db.session.rollback()
            raise

        state.last_import_at = self.clock()
        state.history_complete = (
            state.history_complete
            or (history_reached_end and result["remaining"] == 0)
        )
        result["history_complete"] = state.history_complete
        db.session.commit()

        return result

    def import_all_accounts(
        self,
        max_new_matches_per_account=None,
        queue_ids=DEFAULT_QUEUE_IDS,
        progress=None,
    ):
        """
        Import every tracked Riot Account.

        A failure for one account does not stop the others, except a
        rejected API key, which would fail for every account.
        """

        results = []

        for account in RiotAccount.query.order_by(RiotAccount.id).all():
            label = f"{account.game_name}#{account.tag_line}"

            try:
                result = self.import_account(
                    account.id,
                    max_new_matches=max_new_matches_per_account,
                    queue_ids=queue_ids,
                    progress=(
                        None if progress is None
                        else lambda done, total, label=label: progress(label, done, total)
                    ),
                )
                result["riot_id"] = label
                results.append(result)

            except MatchImportError as error:
                results.append({
                    "riot_account_id": account.id,
                    "riot_id": label,
                    "error": str(error),
                })

                if self._is_key_error(error.__cause__):
                    break

        return results

    def _collect_new_match_ids(
        self,
        account,
        state,
        queue_ids,
        result,
    ):
        """
        Return unimported match IDs newest first, and whether every queue
        was listed to its end.
        """

        known_ids = {
            riot_match_id
            for (riot_match_id,) in (
                db.session.query(Match.riot_match_id)
                .join(MatchParticipant)
                .filter(MatchParticipant.riot_account_id == account.id)
            )
        }

        new_ids = set()
        reached_end = True

        for queue_id in queue_ids:
            start = 0

            while start < self.MAX_MATCH_IDS_PER_QUEUE:
                page = self._get_match_id_page(
                    account,
                    queue_id,
                    start,
                    result,
                )

                new_ids.update(
                    riot_match_id
                    for riot_match_id in page
                    if riot_match_id not in known_ids
                )

                if len(page) < RiotService.MATCH_ID_PAGE_SIZE:
                    break

                if state.history_complete and known_ids.intersection(page):
                    break

                start += len(page)

            else:
                reached_end = False

        return (
            sorted(new_ids, key=self._match_sort_key, reverse=True),
            reached_end,
        )

    def _get_match_id_page(
        self,
        account,
        queue_id,
        start,
        result,
    ):
        riot_service = self._get_riot_service()

        try:
            return riot_service.get_match_ids(
                account.puuid,
                account.platform_region,
                start=start,
                count=RiotService.MATCH_ID_PAGE_SIZE,
                queue=queue_id,
            )

        except requests.HTTPError as error:
            if self._status_code(error) != 400 or result["puuid_refreshed"]:
                raise

        # Riot answers 400 for a PUUID encrypted by another API key
        # project. Look the Riot ID up again and retry once.
        self._refresh_puuid(account)
        result["puuid_refreshed"] = True

        return riot_service.get_match_ids(
            account.puuid,
            account.platform_region,
            start=start,
            count=RiotService.MATCH_ID_PAGE_SIZE,
            queue=queue_id,
        )

    def _refresh_puuid(self, account):
        account_data = self._get_riot_service().get_account_by_riot_id(
            account.game_name,
            account.tag_line,
            account.platform_region,
        )

        account.puuid = account_data["puuid"]
        db.session.commit()

    def _import_match(
        self,
        account,
        riot_match_id,
        queue_ids,
        tracked_accounts,
    ):
        existing_match = Match.query.filter_by(
            riot_match_id=riot_match_id
        ).one_or_none()

        if existing_match is not None:
            linked = self._link_existing_match(
                account,
                existing_match,
            )
            db.session.commit()
            return "linked_existing" if linked else "unavailable"

        match_data = self._get_riot_service().get_match(
            riot_match_id,
            account.platform_region,
        )

        if (
            match_data is None
            or match_data.get("info", {}).get("queueId") not in queue_ids
        ):
            return "unavailable"

        match = self._build_match(
            riot_match_id,
            match_data,
            tracked_accounts,
            imported_at=self.clock(),
        )

        db.session.add(match)
        db.session.commit()

        return "imported"

    def _link_existing_match(self, account, match):
        """
        Link this account to a game that another account already stored.

        Returns whether the account's participant was found.
        """

        participant = next(
            (p for p in match.participants if p.puuid == account.puuid),
            None,
        )

        if participant is None:
            # Stored under another API key project: the PUUIDs differ,
            # but Riot's participant slot does not.
            match_data = self._get_riot_service().get_match(
                match.riot_match_id,
                account.platform_region,
            )
            participant_id = self._participant_id_for_puuid(
                match_data,
                account.puuid,
            )
            participant = next(
                (p for p in match.participants if p.participant_id == participant_id),
                None,
            )

        if participant is None:
            return False

        participant.riot_account_id = account.id
        return True

    @classmethod
    def _build_match(
        cls,
        riot_match_id,
        match_data,
        tracked_accounts,
        imported_at,
    ):
        info = match_data["info"]

        match = Match(
            riot_match_id=riot_match_id,
            platform_id=str(info.get("platformId") or riot_match_id.split("_", 1)[0]),
            queue_id=int(info["queueId"]),
            game_mode=info.get("gameMode"),
            map_id=info.get("mapId"),
            game_version=info.get("gameVersion"),
            game_creation=cls._utc_from_milliseconds(info["gameCreation"]),
            game_duration_seconds=cls._duration_seconds(info),
            raw_data=zlib.compress(
                json.dumps(match_data, separators=(",", ":")).encode("utf-8")
            ),
            imported_at=imported_at,
        )

        for index, participant in enumerate(info.get("participants", [])):
            puuid = participant.get("puuid")
            match.participants.append(
                MatchParticipant(
                    participant_id=int(participant.get("participantId") or index + 1),
                    puuid=puuid,
                    riot_id_game_name=(
                        participant.get("riotIdGameName")
                        or participant.get("summonerName")
                    ),
                    riot_id_tagline=participant.get("riotIdTagline"),
                    riot_champion_id=int(participant["championId"]),
                    team_id=int(participant["teamId"]),
                    team_position=participant.get("teamPosition") or "",
                    win=bool(participant.get("win")),
                    kills=int(participant.get("kills") or 0),
                    deaths=int(participant.get("deaths") or 0),
                    assists=int(participant.get("assists") or 0),
                    riot_account_id=tracked_accounts.get(puuid),
                )
            )

        return match

    @staticmethod
    def decode_raw_data(match):
        """
        Return the stored Match-V5 document of a Match.
        """

        if match.raw_data is None:
            return None

        return json.loads(zlib.decompress(match.raw_data).decode("utf-8"))

    @staticmethod
    def _duration_seconds(info):
        # Before patch 11.20 gameDuration was in milliseconds; games
        # since then carry gameEndTimestamp and report seconds.
        duration = int(info.get("gameDuration") or 0)

        if "gameEndTimestamp" in info:
            return duration

        return duration // 1000

    @staticmethod
    def _utc_from_milliseconds(milliseconds):
        return datetime.fromtimestamp(
            int(milliseconds) / 1000,
            tz=timezone.utc,
        ).replace(tzinfo=None)

    @staticmethod
    def _participant_id_for_puuid(match_data, puuid):
        participants = (match_data or {}).get("info", {}).get("participants", [])

        for index, participant in enumerate(participants):
            if participant.get("puuid") == puuid:
                return int(participant.get("participantId") or index + 1)

        return None

    @staticmethod
    def _match_sort_key(riot_match_id):
        # Match IDs are PLATFORM_NUMBER, and the number grows over time.
        _, _, number = riot_match_id.partition("_")
        return int(number) if number.isdigit() else 0

    @staticmethod
    def _tracked_accounts_by_puuid():
        return {
            puuid: account_id
            for account_id, puuid in db.session.query(RiotAccount.id, RiotAccount.puuid)
        }

    @staticmethod
    def _get_or_create_state(account):
        if account.match_import_state is None:
            account.match_import_state = MatchImportState(
                history_complete=False
            )
            db.session.commit()

        return account.match_import_state

    @staticmethod
    def _status_code(error):
        response = getattr(error, "response", None)
        return getattr(response, "status_code", None)

    @classmethod
    def _is_key_error(cls, error):
        return cls._status_code(error) in (401, 403)

    @classmethod
    def _describe_request_error(cls, error):
        status_code = cls._status_code(error)

        if status_code in (401, 403):
            return (
                "Riot rejected the API key. Development keys expire after "
                "24 hours; save a new key in Settings and import again."
            )

        if status_code == 404:
            return "Riot could not find this Riot ID. Check the account's Riot ID."

        if status_code == 429:
            return "Riot's rate limit was reached. Wait two minutes and import again."

        if status_code is not None:
            return f"Riot returned HTTP {status_code}. Games imported so far are kept."

        return "Riot could not be reached. Games imported so far are kept."
