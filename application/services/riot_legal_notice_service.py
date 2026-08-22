class RiotLegalNoticeService:
    """
    Supplies the Riot Games legal notice and Data Dragon
    attribution shown by the application.
    """

    PRODUCT_NAME = (
        "League Mastery Tracker"
    )

    BOILERPLATE = (
        "League Mastery Tracker isn't endorsed by "
        "Riot Games and doesn't reflect the views "
        "or opinions of Riot Games or anyone "
        "officially involved in producing or "
        "managing Riot Games properties. Riot Games, "
        "and all associated properties are trademarks "
        "or registered trademarks of Riot Games, Inc."
    )

    ASSET_SOURCE = (
        "Riot Games Data Dragon"
    )

    ASSET_EXPLANATION = (
        "The application uses champion reference data and "
        "champion icons from Riot Games Data Dragon. "
        "The data is stored locally to support offline use."
    )

    POLICY_URL = (
        "https://developer.riotgames.com/"
        "policies/general"
    )

    DATA_DRAGON_URL = (
        "https://developer.riotgames.com/"
        "docs/lol"
    )

    @classmethod
    def get_notice(
        cls,
    ):
        """
        Return an independent mapping containing public legal
        and attribution information.
        """

        return {
            "product_name": (
                cls.PRODUCT_NAME
            ),
            "boilerplate": (
                cls.BOILERPLATE
            ),
            "asset_source": (
                cls.ASSET_SOURCE
            ),
            "asset_explanation": (
                cls.ASSET_EXPLANATION
            ),
            "policy_url": (
                cls.POLICY_URL
            ),
            "data_dragon_url": (
                cls.DATA_DRAGON_URL
            ),
        }