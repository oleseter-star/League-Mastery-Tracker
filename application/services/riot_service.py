import time
from urllib.parse import quote

import requests

from application.services.riot_api_key_service import (
    RiotApiKeyService,
)
from application.services.riot_rate_limiter import (
    shared_rate_limiter,
)


class RiotService:
    """
    Handles communication with Riot API services.

    This service retrieves external Riot data only.
    Database persistence is handled by SyncService.
    """

    PLATFORM_TO_REGIONAL = {
        "BR1": "americas",
        "LA1": "americas",
        "LA2": "americas",
        "NA1": "americas",
        "EUN1": "europe",
        "EUW1": "europe",
        "RU": "europe",
        "TR1": "europe",
        "JP1": "asia",
        "KR": "asia",
        "OC1": "sea",
        "PH2": "sea",
        "SG2": "sea",
        "TH2": "sea",
        "TW2": "sea",
        "VN2": "sea",
    }

    MATCH_ID_PAGE_SIZE = 100
    MAX_REQUEST_ATTEMPTS = 5

    def __init__(
        self,
        rate_limiter=None,
        sleep=time.sleep,
    ):
        self.timeout_seconds = 10
        self.rate_limiter = (
            rate_limiter
            or shared_rate_limiter
        )
        self.sleep = sleep

    @classmethod
    def normalize_platform_region(
        cls,
        platform_region,
    ):
        """
        Validate and normalize a Riot platform routing value.
        """

        if not platform_region:
            raise ValueError(
                "Platform region is required."
            )

        normalized_region = (
            platform_region
            .strip()
            .upper()
        )

        if normalized_region not in cls.PLATFORM_TO_REGIONAL:
            raise ValueError(
                f"Unsupported platform region: "
                f"{normalized_region}"
            )

        return normalized_region

    @classmethod
    def get_regional_route(
        cls,
        platform_region,
    ):
        """
        Return the regional route belonging to a platform route.
        """

        normalized_region = (
            cls.normalize_platform_region(
                platform_region
            )
        )

        return cls.PLATFORM_TO_REGIONAL[
            normalized_region
        ]

    @classmethod
    def get_account_regional_route(
        cls,
        platform_region,
    ):
        """
        Return the Account-V1 route for a platform route.

        Account-V1 serves every account from americas, asia, and europe
        but has no sea route, so sea platforms use asia.
        """

        regional_route = cls.get_regional_route(
            platform_region
        )

        if regional_route == "sea":
            return "asia"

        return regional_route

    @staticmethod
    def _headers():
        """
        Return request headers using the currently active API key.

        The key is resolved for every request so a locally saved key
        can be replaced without restarting the application.
        """

        api_key = RiotApiKeyService.get_api_key()

        if not api_key:
            raise RuntimeError(
                "Riot API key is not configured. "
                "Open Settings and add a valid key."
            )

        return {
            "X-Riot-Token": api_key,
            "Accept": "application/json",
        }

    def _request(
        self,
        method,
        url,
        **kwargs,
    ):
        """
        Send one authenticated request to Riot.
        """

        response = requests.request(
            method=method,
            url=url,
            headers=self._headers(),
            timeout=self.timeout_seconds,
            **kwargs,
        )

        response.raise_for_status()

        return response.json()

    def get_account_by_riot_id(
        self,
        game_name,
        tag_line,
        platform_region,
    ):
        """
        Retrieve a Riot Account and its PUUID from a Riot ID.
        """

        clean_game_name = str(
            game_name or ""
        ).strip()

        clean_tag_line = str(
            tag_line or ""
        ).strip()

        if not clean_game_name:
            raise ValueError(
                "Game Name is required."
            )

        if not clean_tag_line:
            raise ValueError(
                "Tag Line is required."
            )

        regional_route = self.get_account_regional_route(
            platform_region
        )

        encoded_game_name = quote(
            clean_game_name,
            safe="",
        )

        encoded_tag_line = quote(
            clean_tag_line,
            safe="",
        )

        url = (
            f"https://{regional_route}.api.riotgames.com"
            f"/riot/account/v1/accounts/by-riot-id/"
            f"{encoded_game_name}/{encoded_tag_line}"
        )

        account_data = self._request(
            "GET",
            url,
        )

        if (
            not isinstance(account_data, dict)
            or not account_data.get("puuid")
        ):
            raise ValueError(
                "Riot returned invalid account data."
            )

        return account_data

    def get_champion_mastery(
        self,
        puuid,
        platform_region,
    ):
        """
        Retrieve all Champion Mastery records for a Riot Account.
        """

        clean_puuid = str(
            puuid or ""
        ).strip()

        if not clean_puuid:
            raise ValueError(
                "PUUID is required."
            )

        platform_route = (
            self.normalize_platform_region(
                platform_region
            )
            .lower()
        )

        url = (
            f"https://{platform_route}.api.riotgames.com"
            f"/lol/champion-mastery/v4/"
            f"champion-masteries/by-puuid/"
            f"{clean_puuid}"
        )

        mastery_data = self._request(
            "GET",
            url,
        )

        if not isinstance(mastery_data, list):
            raise ValueError(
                "Riot returned invalid Champion Mastery data."
            )

        return mastery_data

    def get_match_ids(
        self,
        puuid,
        platform_region,
        start=0,
        count=MATCH_ID_PAGE_SIZE,
        queue=None,
        match_type=None,
    ):
        """
        Retrieve one page of match IDs for a Riot Account, newest first.

        queue filters by queue ID; match_type by Riot's category, such as
        "ranked", which covers every ranked queue.
        """

        clean_puuid = str(
            puuid or ""
        ).strip()

        if not clean_puuid:
            raise ValueError(
                "PUUID is required."
            )

        regional_route = self.get_regional_route(
            platform_region
        )

        params = {
            "start": int(start),
            "count": int(count),
        }

        if queue is not None:
            params["queue"] = int(queue)

        if match_type is not None:
            params["type"] = str(match_type)

        url = (
            f"https://{regional_route}.api.riotgames.com"
            f"/lol/match/v5/matches/by-puuid/"
            f"{quote(clean_puuid, safe='')}/ids"
        )

        match_ids = self._request_with_retry(
            url,
            params=params,
        )

        if match_ids is None:
            return []

        if not isinstance(match_ids, list):
            raise ValueError(
                "Riot returned invalid match ID data."
            )

        return match_ids

    def get_match(
        self,
        match_id,
        platform_region,
    ):
        """
        Retrieve one Match-V5 document, or None when Riot no longer has it.
        """

        clean_match_id = str(
            match_id or ""
        ).strip()

        if not clean_match_id:
            raise ValueError(
                "Match ID is required."
            )

        regional_route = self.get_regional_route(
            platform_region
        )

        url = (
            f"https://{regional_route}.api.riotgames.com"
            f"/lol/match/v5/matches/"
            f"{quote(clean_match_id, safe='')}"
        )

        match_data = self._request_with_retry(
            url
        )

        if match_data is None:
            return None

        if not isinstance(match_data, dict):
            raise ValueError(
                "Riot returned invalid match data."
            )

        return match_data

    def _request_with_retry(
        self,
        url,
        params=None,
    ):
        """
        Send one rate-limited GET request for match history.

        Riot's 429 responses wait for Retry-After, and temporary 5xx
        failures back off before retrying. A 404 returns None.
        """

        for attempt in range(
            1,
            self.MAX_REQUEST_ATTEMPTS + 1,
        ):
            self.rate_limiter.wait()

            response = requests.request(
                method="GET",
                url=url,
                headers=self._headers(),
                params=params,
                timeout=self.timeout_seconds,
            )

            status_code = response.status_code

            if status_code == 404:
                return None

            final_attempt = (
                attempt
                == self.MAX_REQUEST_ATTEMPTS
            )

            if (
                status_code == 429
                and not final_attempt
            ):
                self.sleep(
                    self._retry_after_seconds(
                        response
                    )
                )
                continue

            if (
                status_code >= 500
                and not final_attempt
            ):
                self.sleep(
                    2 ** attempt
                )
                continue

            response.raise_for_status()

            return response.json()

    @staticmethod
    def _retry_after_seconds(
        response,
    ):
        try:
            return max(
                1,
                int(
                    response.headers.get(
                        "Retry-After",
                        "10",
                    )
                ),
            )

        except (TypeError, ValueError):
            return 10
