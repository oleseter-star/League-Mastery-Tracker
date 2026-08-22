import unittest

from application.services.riot_legal_notice_service import (
    RiotLegalNoticeService,
)


class RiotLegalNoticeServiceTests(
    unittest.TestCase
):
    def test_notice_uses_product_name(
        self,
    ):
        notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        self.assertEqual(
            notice["product_name"],
            "League Mastery Tracker",
        )

        self.assertTrue(
            notice["boilerplate"].startswith(
                "League Mastery Tracker "
                "isn't endorsed by Riot Games"
            )
        )

    def test_notice_contains_required_boilerplate(
        self,
    ):
        notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        self.assertEqual(
            notice["boilerplate"],
            (
                "League Mastery Tracker isn't endorsed by "
                "Riot Games and doesn't reflect the views "
                "or opinions of Riot Games or anyone "
                "officially involved in producing or "
                "managing Riot Games properties. Riot Games, "
                "and all associated properties are trademarks "
                "or registered trademarks of Riot Games, Inc."
            ),
        )

    def test_notice_identifies_data_dragon_assets(
        self,
    ):
        notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        self.assertEqual(
            notice["asset_source"],
            "Riot Games Data Dragon",
        )

        self.assertIn(
            "champion reference data",
            notice["asset_explanation"].lower(),
        )

        self.assertIn(
            "champion icons",
            notice["asset_explanation"].lower(),
        )

    def test_notice_links_only_to_official_riot_sources(
        self,
    ):
        notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        self.assertEqual(
            notice["policy_url"],
            (
                "https://developer.riotgames.com/"
                "policies/general"
            ),
        )

        self.assertEqual(
            notice["data_dragon_url"],
            (
                "https://developer.riotgames.com/"
                "docs/lol"
            ),
        )

    def test_notice_does_not_claim_riot_endorsement(
        self,
    ):
        notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        combined_text = " ".join(
            (
                notice["boilerplate"],
                notice["asset_explanation"],
            )
        ).lower()

        self.assertNotIn(
            "endorsed by riot games.",
            combined_text.replace(
                "isn't endorsed by riot games.",
                "",
            ),
        )

        self.assertNotIn(
            "official riot product",
            combined_text,
        )

    def test_each_call_returns_independent_mapping(
        self,
    ):
        first_notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        second_notice = (
            RiotLegalNoticeService
            .get_notice()
        )

        first_notice["product_name"] = (
            "Changed"
        )

        self.assertEqual(
            second_notice["product_name"],
            "League Mastery Tracker",
        )


if __name__ == "__main__":
    unittest.main()