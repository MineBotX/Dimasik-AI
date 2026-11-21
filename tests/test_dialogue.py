import unittest

from assistant.dialogue import conversational_reply


class DialogueTests(unittest.TestCase):
    def test_identity_question_gets_offline_reply(self):
        answer = conversational_reply("Кто ты")
        self.assertIsNotNone(answer)
        self.assertIn("Я Димасик", answer)

    def test_social_questions_get_offline_replies(self):
        self.assertIn("всё отлично", conversational_reply("Как дела").lower())
        self.assertIn("рад тебя слышать", conversational_reply("Привет").lower())

    def test_non_social_questions_remain_for_search_or_model(self):
        self.assertIsNone(conversational_reply("Как устроен двигатель внутреннего сгорания?"))


    def test_roast_mode_adds_levelled_banter_to_social_reply(self):
        answer = conversational_reply("Привет", roast_enabled=True, roast_level="strong")
        self.assertIn("ходячий пиздец", answer)

    def test_roast_mode_does_not_change_serious_support_reply(self):
        normal = conversational_reply("Мне грустно")
        roast = conversational_reply("Мне грустно", roast_enabled=True, roast_level="strong")
        self.assertEqual(roast, normal)

    def test_roast_mode_is_off_by_default(self):
        self.assertEqual(
            conversational_reply("Как дела"),
            conversational_reply("Как дела", roast_enabled=False),
        )

    def test_follow_up_uses_previous_user_turn(self):
        answer = conversational_reply(
            "А ты?",
            history=[{"role": "user", "content": "Как у тебя дела?"}],
        )
        self.assertIn("У меня всё хорошо", answer)


if __name__ == "__main__":
    unittest.main()
