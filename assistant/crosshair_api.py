"""Local crosshair generation API. Standard-library only; binds to loopback by default."""
from __future__ import annotations

import base64
import json
import math
import re
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SIZE = 512
CENTER = SIZE // 2
COLORS = {
    "зелён": "#00ff00", "зелен": "#00ff00", "green": "#00ff00",
    "красн": "#ff3030", "red": "#ff3030",
    "голуб": "#00d9ff", "cyan": "#00ffff", "бирюз": "#00d9c0",
    "син": "#2878ff", "blue": "#2878ff",
    "жёлт": "#ffff00", "желт": "#ffff00", "yellow": "#ffff00",
    "бел": "#ffffff", "white": "#ffffff",
    "фиолет": "#b45cff", "розов": "#ff69b4",
    "оранж": "#ff8c00", "чёрн": "#111111", "черн": "#111111",
}


def _description_to_spec(description: str) -> dict:
    text = str(description or "").strip().lower()
    if not text:
        raise ValueError("Поле description не должно быть пустым.")
    color = "#00ff00"
    for key, value in COLORS.items():
        if key in text:
            color = value
            break
    hex_match = re.search(r"#[0-9a-f]{6}\\b", text)
    if hex_match:
        color = hex_match.group(0)
    thickness = 4 if any(w in text for w in ("толст", "жирн")) else 2
    if any(w in text for w in ("тонк", "маленьк", "тонкий")):
        thickness = 1
    length = 18 if any(w in text for w in ("длинн", "больш", "длинный")) else 12
    if any(w in text for w in ("коротк", "маленьк", "маленький")):
        length = 7
    gap = 5 if any(w in text for w in ("большой промежуток", "широкий промежуток")) else 4
    outline = any(w in text for w in ("обвод", "контур", "чёрн", "черн"))
    if "без обводки" in text or "без контура" in text:
        outline = False
    shape = "cross"
    if any(w in text for w in ("точк", "dot", "точка")):
        shape = "dot"
    if any(w in text for w in ("круг", "кольц")):
        shape = "circle"
    if any(w in text for w in ("четыре точки", "4 точки", "четырёх точ")):
        shape = "four_dots"
    if any(w in text for w in ("крест", "классическ", "линии")):
        shape = "cross"
    return {"color": color, "thickness": thickness, "length": length,
            "gap": gap, "outline": outline, "shape": shape}


def _shapes(spec: dict) -> list[tuple]:
    t, length, gap = spec["thickness"], spec["length"], spec["gap"]
    cx = cy = CENTER
    result = []
    if spec["shape"] == "dot":
        result.append(("circle", cx, cy, max(2, t + 1)))
    elif spec["shape"] == "circle":
        result.append(("ring", cx, cy, 9, max(1, t)))
    elif spec["shape"] == "four_dots":
        for dx in (-gap - t, gap + t):
            for dy in (-gap - t, gap + t):
                result.append(("circle", cx + dx, cy + dy, max(2, t + 1)))
    else:
        result.extend([
            ("rect", cx - t / 2, cy - gap - length, t, length),
            ("rect", cx - t / 2, cy + gap, t, length),
            ("rect", cx - gap - length, cy - t / 2, length, t),
            ("rect", cx + gap, cy - t / 2, length, t),
        ])
    return result


def make_svg(spec: dict) -> bytes:
    shapes = _shapes(spec)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">']
    for item in shapes:
        kind = item[0]
        if kind == "rect":
            _, x, y, w, h = item
            if spec["outline"]:
                pad = 1.5
                parts.append(f'<rect x="{x-pad}" y="{y-pad}" width="{w+2*pad}" height="{h+2*pad}" fill="#000000"/>')
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{spec["color"]}"/>')
        elif kind == "circle":
            _, x, y, r = item
            if spec["outline"]:
                parts.append(f'<circle cx="{x}" cy="{y}" r="{r+1.5}" fill="#000000"/>')
            parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{spec["color"]}"/>')
        else:
            _, x, y, r, stroke = item
            parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#000000" stroke-width="{stroke+2}" />' if spec["outline"] else "")
            parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{spec["color"]}" stroke-width="{stroke}" />')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def make_png(spec: dict) -> bytes:
    scale = 2
    width = height = SIZE * scale
    pixels = bytearray(width * height * 4)
    shapes = _shapes(spec)
    color = tuple(int(spec["color"][i:i+2], 16) for i in (1, 3, 5))

    def paint(x, y, rgb):
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 4
            pixels[offset:offset+4] = bytes((*rgb, 255))

    def inside(item, x, y, expand=0):
        kind = item[0]
        if kind == "rect":
            _, rx, ry, rw, rh = item
            return rx-expand <= x < rx+rw+expand and ry-expand <= y < ry+rh+expand
        if kind == "circle":
            _, cx, cy, radius = item
            return (x-cx)**2 + (y-cy)**2 <= (radius+expand)**2
        _, cx, cy, radius, stroke = item
        dist = math.hypot(x-cx, y-cy)
        return radius-(stroke/2+expand) <= dist <= radius+(stroke/2+expand)

    for py in range(height):
        y = (py + 0.5) / scale
        for px in range(width):
            x = (px + 0.5) / scale
            for item in shapes:
                if spec["outline"] and inside(item, x, y, 1.25):
                    paint(px, py, (0, 0, 0))
                if inside(item, x, y):
                    paint(px, py, color)
    raw = b"".join(b"\\x00" + bytes(pixels[y*width*4:(y+1)*width*4]) for y in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\\x89PNG\\r\\n\\x1a\\n" +
            chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class CrosshairHandler(BaseHTTPRequestHandler):
    server_version = "DimasikCrosshairAPI/1.0"

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"ok": True, "service": "dimasik-crosshair-api", "version": "1.0"})
        if path == "/":
            return self._json(200, {
                "service": "Dimasik Crosshair API",
                "endpoints": {"GET /health": "Проверка API",
                              "POST /generate-crosshair": "JSON {description, format: png|svg}; возвращает изображение"},
                "example": {"description": "маленький зелёный прицел-крестик с чёрной обводкой", "format": "png"}
            })
        return self._json(404, {"error": "Маршрут не найден"})

    def do_POST(self):
        if urlparse(self.path).path != "/generate-crosshair":
            return self._json(404, {"error": "Маршрут не найден"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 16_384:
                return self._json(413, {"error": "Размер JSON должен быть от 1 до 16384 байт"})
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Ожидается JSON-объект.")
            spec = _description_to_spec(payload.get("description", ""))
            fmt = str(payload.get("format", "png")).lower()
            if fmt not in ("png", "svg"):
                raise ValueError("format должен быть png или svg.")
            body = make_png(spec) if fmt == "png" else make_svg(spec)
            self.send_response(200)
            self.send_header("Content-Type", "image/png" if fmt == "png" else "image/svg+xml; charset=utf-8")
            self.send_header("Content-Disposition", f'inline; filename="dimasik-crosshair.{fmt}"')
            self.send_header("X-Crosshair-Color", spec["color"])
            self.send_header("X-Crosshair-Shape", spec["shape"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        print("[Crosshair API] " + (fmt % args))


def start_server(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, int(port)), CrosshairHandler)
    thread = threading.Thread(target=server.serve_forever, name="DimasikCrosshairAPI", daemon=True)
    thread.start()
    return server
