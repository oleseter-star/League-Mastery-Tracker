import unittest

from application.services import match_catalog as catalog


class PatchNameTests(unittest.TestCase):
    def test_patch_comes_from_major_and_minor_of_the_game_version(self):
        self.assertEqual(catalog.patch_from_game_version("16.18.712.3456"), "16.18")
        self.assertEqual(catalog.patch_from_game_version("15.1.1"), "15.1")
        self.assertIsNone(catalog.patch_from_game_version(""))
        self.assertIsNone(catalog.patch_from_game_version(None))
        self.assertIsNone(catalog.patch_from_game_version("Version"))

    def test_patches_are_shown_the_way_riot_announces_them(self):
        self.assertEqual(catalog.display_patch("16.18"), "26.18")
        self.assertEqual(catalog.display_patch("15.21"), "25.21")
        self.assertEqual(catalog.display_patch("14.23"), "14.23")
        self.assertEqual(catalog.display_patch(None), "Unknown")

    def test_typed_patches_accept_both_names(self):
        self.assertEqual(catalog.parse_patch("26.18"), "16.18")
        self.assertEqual(catalog.parse_patch("16.18"), "16.18")
        self.assertEqual(catalog.parse_patch("26.03"), "16.3")
        self.assertEqual(catalog.parse_patch("14.23"), "14.23")

        for text in ("26", "26.S1", "", "latest"):
            with self.assertRaises(ValueError, msg=text):
                catalog.parse_patch(text)

    def test_patch_selection_supports_lists_and_ranges(self):
        available = ["16.18", "16.17", "16.9", "15.24"]

        self.assertEqual(catalog.parse_patch_selection(["26.18"], available), ("16.18",))
        self.assertEqual(catalog.parse_patch_selection(["26.17,26.18"], available), ("16.18", "16.17"))
        self.assertEqual(catalog.parse_patch_selection(["26.9-26.18"], available), ("16.18", "16.17", "16.9"))
        self.assertEqual(catalog.parse_patch_selection(["26.18-25.24"], available), ("16.18", "16.17", "16.9", "15.24"))
        self.assertEqual(catalog.parse_patch_selection(["26.18", "16.18"], available), ("16.18",))


class ModeTests(unittest.TestCase):
    def test_ranked_modes_map_to_queue_ids(self):
        self.assertEqual(catalog.queue_id_for_mode("solo"), 420)
        self.assertEqual(catalog.queue_id_for_mode("Flex"), 440)
        self.assertEqual(catalog.queue_id_for_mode("clash"), 700)
        self.assertEqual(catalog.queue_id_for_mode("5s"), 710)
        self.assertEqual(catalog.queue_id_for_mode("fives"), 710)
        self.assertEqual(catalog.queue_label(710), "Ranked 5s")

    def test_unknown_modes_list_the_known_ones(self):
        with self.assertRaises(ValueError) as raised:
            catalog.queue_id_for_mode("aram")

        self.assertIn("5s, clash, flex, solo", str(raised.exception))

    def test_queue_labels(self):
        self.assertEqual(catalog.queue_label(420), "Ranked Solo/Duo")
        self.assertEqual(catalog.queue_label(4242), "Queue 4242")


if __name__ == "__main__":
    unittest.main()
