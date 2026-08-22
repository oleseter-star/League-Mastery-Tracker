from urllib.parse import quote

import requests

from application.services.riot_api_key_service import (
    RiotApiKeyService,
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

    def __init__(self):
        self.timeout_seconds = 10

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

        regional_route = self.get_regional_route(
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