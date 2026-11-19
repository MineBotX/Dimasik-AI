import unittest
from pathlib import Path
from unittest.mock import patch

from assistant.image_generator import (
    LocalImageGenerator,
    MODEL_SHA256,
    MODEL_SIZE,
    MODEL_URL,
    ENGINE_CPU_SHA256,
    ENGINE_VULKAN_SHA256,
    clean_image_prompt,
    is_image_request,
)


class ImageRequestTests(unittest.TestCase):
    def test_recognizes_russian_image_requests(self):
        prompts = (
            "Нарисуй кофейню в стиле киберпанк",
            "Изобрази рыжего кота на подоконнике",
            "Создай картинку с космическим кораблём",
            "Сделай логотип для моего канала",
            "Сгенерируй иллюстрацию зимнего леса",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(is_image_request(prompt))

    def test_recognizes_english_image_requests(self):
        self.assertTrue(is_image_request("Draw a cozy coffee shop"))
        self.assertTrue(is_image_request("Generate an image of a red fox"))

    def test_does_not_hijack_normal_chat_or_code_requests(self):
        for prompt in (
            "Как дела?",
            "Напиши код калькулятора на Python",
            "Создай сайт для кофейни",
            "Расскажи про Stable Diffusion",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(is_image_request(prompt))

    def test_cleans_command_prefixes(self):
        self.assertEqual(
            clean_image_prompt("Нарисуй картинку: уютная кофейня"),
            "уютная кофейня",
        )
        self.assertEqual(
            clean_image_prompt("Draw an image of a mountain"),
            "an image of a mountain",
        )

    def test_model_download_is_pinned_and_hash_checked(self):
        self.assertIn("huggingface.co/gpustack/", MODEL_URL)
        self.assertEqual(MODEL_SIZE, 1_747_190_784)
        self.assertEqual(len(MODEL_SHA256), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in MODEL_SHA256))
        self.assertEqual(len(ENGINE_CPU_SHA256), 64)
        self.assertEqual(len(ENGINE_VULKAN_SHA256), 64)

    def test_selects_vulkan_when_a_vulkan_device_is_listed(self):
        generator = LocalImageGenerator(Path("."))
        def find(backend):
            return Path("vulkan/sd-cli.exe") if backend == "vulkan" else Path("cpu/sd-cli.exe")
        with patch.object(generator, "_find_executable", side_effect=find):
            with patch.object(generator, "_list_devices", return_value="Vulkan0\\tGPU"):
                executable, backend = generator._select_runtime()
        self.assertEqual(executable, Path("vulkan/sd-cli.exe"))
        self.assertEqual(backend, "auto")

    def test_selects_cpu_when_vulkan_is_unavailable(self):
        generator = LocalImageGenerator(Path("."))
        def find(backend):
            return Path("cpu/sd-cli.exe") if backend == "cpu" else None
        with patch.object(generator, "_find_executable", side_effect=find):
            executable, backend = generator._select_runtime()
        self.assertEqual(executable, Path("cpu/sd-cli.exe"))
        self.assertEqual(backend, "cpu")

    def test_model_state_is_false_when_missing(self):
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            generator = LocalImageGenerator(Path(directory))
            self.assertFalse(generator.model_installed)


if __name__ == "__main__":
    unittest.main()
