"""Private, offline text-to-image generation through stable-diffusion.cpp."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import requests


MODEL_NAME = "Stable Diffusion 1.5 Q4_0"
MODEL_SIZE = 1_747_190_784
MODEL_SHA256 = "c2f6e92f9d08d69cc673a1003528ac8199274b3c0eaec88d5fbefe5af67bd42b"
MODEL_URL = (
    "https://huggingface.co/gpustack/stable-diffusion-v1-5-GGUF/resolve/"
    "dcac270609fffc0ce7c7d41a3c0e752721859f7c/stable-diffusion-v1-5-Q4_0.gguf"
)
ENGINE_RELEASE = "master-1106-532d2c1"
ENGINE_ASSET = "sd-master-532d2c1-bin-win-vulkan-x64.zip"

_IMAGE_START = re.compile(
    r"^\s*(нарисуй|изобрази|рисуй|draw)\b|"
    r"^\s*(сгенерируй|создай|сделай)\b.*\b("
    r"картин\w*|изображен\w*|рисунк\w*|иллюстрац\w*|арт\b|"
    r"обо\w*|логотип\w*|постер\w*|аватар\w*|иконк\w*|"
    r"picture|image|illustration|logo|wallpaper|poster|avatar)\b|"
    r"^\s*(generate|create|make)\b.*\b("
    r"image|picture|illustration|logo|wallpaper|poster|avatar)\b",
    re.IGNORECASE,
)
_IMAGE_PREFIX = re.compile(
    r"^\s*(нарисуй|изобрази|рисуй|сгенерируй|создай|сделай|draw|generate|create|make)\s+",
    re.IGNORECASE,
)
_IMAGE_NOUN = re.compile(
    r"^(картинку|картину|изображение|рисунок|иллюстрацию|арт|"
    r"image|picture|illustration)\b[,: -]*",
    re.IGNORECASE,
)


def is_image_request(prompt: str) -> bool:
    """Recognize explicit text-to-image requests without hijacking normal chat."""
    text = str(prompt or "").strip()
    return bool(text and _IMAGE_START.search(text))


def clean_image_prompt(prompt: str) -> str:
    """Remove the command verb while preserving the user's visual description."""
    text = _IMAGE_PREFIX.sub("", str(prompt or "").strip(), count=1)
    text = _IMAGE_NOUN.sub("", text, count=1).strip(" \t:,-")
    return text or str(prompt or "").strip()


class LocalImageGenerator:
    """Downloads one pinned SD 1.5 GGUF model and generates images offline."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.model_path = (
            self.root / "models" / "images" / "stable-diffusion-v1-5-Q4_0.gguf"
        )
        self.engine_root = self.root / "tools" / "stable-diffusion"
        self.output_dir = self.root / "generated_images"

    @property
    def model_installed(self) -> bool:
        try:
            return (
                self.model_path.is_file()
                and self.model_path.stat().st_size == MODEL_SIZE
            )
        except OSError:
            return False

    def download_model(self, progress=None, cancel_event=None) -> None:
        """Download the pinned GGUF and verify its exact size and SHA-256."""
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        needed = MODEL_SIZE + 1024 * 1024 * 1024
        free = shutil.disk_usage(self.model_path.parent).free
        if free < needed:
            raise RuntimeError(
                "Для модели и временных файлов нужно не менее 2,75 ГБ свободного места."
            )

        if self.model_installed:
            if progress:
                progress(100, MODEL_SIZE, MODEL_SIZE)
            return

        part_path = self.model_path.with_suffix(self.model_path.suffix + ".part")
        try:
            part_path.unlink()
        except FileNotFoundError:
            pass

        digest = hashlib.sha256()
        downloaded = 0
        last_percent = -1
        try:
            with requests.get(
                MODEL_URL,
                stream=True,
                allow_redirects=True,
                headers={"User-Agent": "DimasikAI-local-image-generation/1.0"},
                timeout=(30, 180),
            ) as response:
                response.raise_for_status()
                content_length = int(response.headers.get("Content-Length", "0") or 0)
                if content_length and content_length != MODEL_SIZE:
                    raise RuntimeError(
                        f"Сервер сообщил неожиданный размер модели: {content_length:,} байт."
                    )

                with part_path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                        if cancel_event is not None and cancel_event.is_set():
                            raise RuntimeError("Загрузка модели изображений отменена.")
                        if not chunk:
                            continue
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        percent = min(99, int(downloaded * 100 / MODEL_SIZE))
                        if progress and percent != last_percent:
                            progress(percent, downloaded, MODEL_SIZE)
                            last_percent = percent

            if downloaded != MODEL_SIZE:
                raise RuntimeError(
                    f"Загрузка неполная: {downloaded:,} из {MODEL_SIZE:,} байт."
                )
            if digest.hexdigest().lower() != MODEL_SHA256:
                raise RuntimeError(
                    "Контрольная сумма модели не совпала. Частичный файл удалён."
                )

            os.replace(part_path, self.model_path)
            if progress:
                progress(100, MODEL_SIZE, MODEL_SIZE)
        except Exception:
            try:
                part_path.unlink()
            except OSError:
                pass
            raise

    def _find_executable(self) -> Path:
        preferred = self.engine_root / "sd-cli.exe"
        if preferred.is_file():
            return preferred
        matches = (
            list(self.engine_root.rglob("sd-cli.exe"))
            if self.engine_root.exists()
            else []
        )
        if matches:
            return matches[0]
        raise RuntimeError(
            "Не найден sd-cli.exe. Установи свежую сборку Димасика с движком "
            "локальной генерации изображений."
        )

    def list_backends(self) -> str:
        """Return installed backend/device names for diagnostics."""
        executable = self._find_executable()
        result = subprocess.run(
            [str(executable), "--list-devices"],
            cwd=str(executable.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(
                (result.stderr or result.stdout or "Не удалось определить устройства")[-2500:]
            )
        return result.stdout + "\n" + result.stderr

    def generate(
        self,
        prompt: str,
        *,
        progress=None,
        width: int = 512,
        height: int = 512,
        steps: int = 20,
    ) -> Path:
        """Generate a PNG locally; no prompt or image is sent to a network service."""
        visual_prompt = clean_image_prompt(prompt)
        if not visual_prompt:
            raise ValueError("Опиши, что именно нужно нарисовать.")
        if len(visual_prompt) > 1500:
            raise ValueError("Слишком длинное описание. Сократи запрос до 1500 символов.")
        if not self.model_installed:
            raise RuntimeError(
                "Модель изображений ещё не установлена. Нажми кнопку "
                "«Скачать модель изображений»."
            )

        executable = self._find_executable()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / (
            time.strftime("dimasik_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8] + ".png"
        )

        # Vulkan build automatically chooses a suitable GPU when possible and
        # falls back to the CPU backend when no usable GPU backend is available.
        command = [
            str(executable),
            "-m", str(self.model_path),
            "-p", visual_prompt,
            "-o", str(output_path),
            "-W", str(max(256, min(768, int(width)))),
            "-H", str(max(256, min(768, int(height)))),
            "--steps", str(max(8, min(40, int(steps)))),
            "--sampling-method", "euler_a",
            "--cfg-scale", "7.0",
            "--backend", "auto",
            "--threads", str(max(2, min(16, os.cpu_count() or 4))),
            "--vae-tiling",
        ]
        if progress:
            progress("Создаю изображение локально. Это может занять несколько минут.")

        try:
            result = subprocess.run(
                command,
                cwd=str(executable.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Генерация превысила лимит в 60 минут. Попробуй позже или уменьши нагрузку."
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Не удалось запустить движок изображений: {exc}") from exc

        if result.returncode != 0 or not output_path.is_file():
            details = (result.stderr or "") + "\n" + (result.stdout or "")
            details = details.strip()[-4500:]
            if output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            raise RuntimeError(
                "Движок не смог создать изображение."
                + (("\nПодробности: " + details) if details else "")
            )

        if output_path.stat().st_size < 1024:
            try:
                output_path.unlink()
            except OSError:
                pass
            raise RuntimeError("Получен пустой или повреждённый PNG-файл.")

        return output_path
