import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from assistant.knowledge import LocalKnowledge
from assistant.search_backend import normalize_result_url, parse_search_results


DDG_HTML = """
<div class="result">
  <a class="result__a" href="https://example.org/coffee">
    <span>Кофейня <b>у дома</b></span>
  </a>
  <div class="result__snippet">Свежий <b>кофе</b> и десерты каждый день.</div>
</div>
<div class="result">
  <a class="result-link" href="//example.net/menu">Меню кофейни</a>
  <div class="result-snippet">Напитки и выпечка.</div>
</div>
"""

BING_HTML = """
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://example.com/python"><strong>Python</strong> — официальный сайт</a></h2>
    <div class="b_caption"><p>Документация <strong>Python</strong> и руководства.</p></div>
  </li>
  <li class="b_algo">
    <h2><a href="https://docs.example.com/">Документация</a></h2>
    <p>Материалы и примеры.</p>
  </li>
</ol>
"""


class SearchParserTests(unittest.TestCase):
    def test_duckduckgo_titles_snippets_and_nested_markup(self):
        results = parse_search_results(DDG_HTML, "duckduckgo", limit=5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Кофейня у дома")
        self.assertIn("Свежий кофе и десерты", results[0]["snippet"])
        self.assertEqual(results[1]["url"], "https://example.net/menu")
        self.assertIn("Напитки", results[1]["snippet"])

    def test_bing_result_cards(self):
        results = parse_search_results(BING_HTML, "bing", limit=5)
        self.assertEqual(len(results), 2)
        self.assertIn("Python", results[0]["title"])
        self.assertIn("Документация Python", results[0]["snippet"])
        self.assertEqual(results[1]["url"], "https://docs.example.com/")

    def test_unwraps_duckduckgo_redirect_and_rejects_invalid_url(self):
        self.assertEqual(
            normalize_result_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fx"),
            "https://example.com/x",
        )
        self.assertEqual(normalize_result_url("javascript:alert(1)"), "")


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.knowledge = LocalKnowledge(Path(self.temp.name) / "memory.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    @patch("assistant.knowledge.requests.get")
    def test_search_uses_duckduckgo_when_available(self, mock_get):
        response = mock_get.return_value
        response.raise_for_status.return_value = None
        response.text = DDG_HTML

        result = self.knowledge.search_web("кофейня рядом", limit=2)

        self.assertTrue(result["online"])
        self.assertEqual(result["engine"], "DuckDuckGo")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_get.call_args.kwargs["timeout"], (5, 12))

    @patch("assistant.knowledge.requests.get")
    def test_search_falls_back_to_bing_when_duckduckgo_fails(self, mock_get):
        first = requests.Timeout("search timed out")
        bing_response = mock_get.return_value
        bing_response.raise_for_status.return_value = None
        bing_response.text = BING_HTML
        mock_get.side_effect = [first, bing_response]

        result = self.knowledge.search_web("документация Python")

        self.assertTrue(result["online"])
        self.assertEqual(result["engine"], "Bing")
        self.assertGreaterEqual(len(result["results"]), 1)
        self.assertEqual(mock_get.call_count, 2)

    @patch("assistant.knowledge.requests.get")
    def test_empty_query_does_not_call_network(self, mock_get):
        result = self.knowledge.search_web("   ")
        self.assertFalse(result["online"])
        self.assertEqual(mock_get.call_count, 0)


if __name__ == "__main__":
    unittest.main()
