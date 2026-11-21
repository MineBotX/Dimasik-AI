import unittest

from assistant.personality import build_personality


class PersonalityTests(unittest.TestCase):
    def test_disabled_mode_preserves_personality(self):
        self.assertEqual(
            build_personality("Отвечай кратко", roast_enabled=False),
            "Отвечай кратко",
        )

    def test_disabled_mode_with_empty_personality_is_empty(self):
        self.assertEqual(build_personality(None), "")

    def test_enabled_mode_adds_friendly_profanity_style(self):
        result = build_personality("Будь дружелюбным", roast_enabled=True)
        self.assertIn("Будь дружелюбным", result)
        self.assertIn("дружеские подколы", result)
        self.assertIn("Не используй угрозы", result)

    def test_levels_change_the_style(self):
        light = build_personality("", roast_enabled=True, roast_level="light")
        medium = build_personality("", roast_enabled=True, roast_level="medium")
        strong = build_personality("", roast_enabled=True, roast_level="strong")
        self.assertIn("мягкие", light)
        self.assertIn("Регулярно", medium)
        self.assertIn("крепкий", strong)

    def test_unknown_level_falls_back_to_medium(self):
        self.assertEqual(
            build_personality("", roast_enabled=True, roast_level="unknown"),
            build_personality("", roast_enabled=True, roast_level="medium"),
        )


if __name__ == "__main__":
    unittest.main()
