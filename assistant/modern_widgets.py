"""Lightweight rounded Tk widgets for Dimasik's modern dark interface."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont


def rounded_rectangle_points(x1, y1, x2, y2, radius):
    """Return smooth polygon points for a rounded rectangle."""
    radius = max(0, min(float(radius), (x2 - x1) / 2, (y2 - y1) / 2))
    if radius <= 0:
        return [x1, y1, x2, y1, x2, y2, x1, y2]

    points = []
    corners = (
        (x2 - radius, y1 + radius, -90),
        (x2 - radius, y2 - radius, 0),
        (x1 + radius, y2 - radius, 90),
        (x1 + radius, y1 + radius, 180),
    )
    for cx, cy, start in corners:
        for step in range(7):
            import math
            angle = math.radians(start + step * 90 / 6)
            points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


class RoundedPanel(tk.Canvas):
    """Canvas-backed rounded card with a normal Tk Frame for its children."""

    def __init__(
        self,
        master,
        *,
        fill="#141d30",
        background="#0b1020",
        radius=18,
        padding=10,
        border="#24324b",
        border_width=1,
        height=80,
        **kwargs,
    ):
        super().__init__(
            master,
            bg=background,
            highlightthickness=0,
            borderwidth=0,
            height=height,
            **kwargs,
        )
        self.fill = fill
        self.radius = radius
        self.padding = padding
        self.border = border
        self.border_width = border_width
        self.content = tk.Frame(self, bg=fill, borderwidth=0, highlightthickness=0)
        self._window = self.create_window(
            padding, padding, anchor="nw", window=self.content
        )
        self.bind("<Configure>", self._redraw)
        self._redraw()

    def _redraw(self, _event=None):
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        pad = min(self.padding, max(1, width // 4), max(1, height // 4))
        self.coords(self._window, pad, pad)
        self.itemconfigure(
            self._window,
            width=max(1, width - pad * 2),
            height=max(1, height - pad * 2),
        )
        self.delete("rounded-panel")
        inset = max(1, self.border_width / 2)
        points = rounded_rectangle_points(
            inset, inset, width - inset, height - inset, self.radius
        )
        self.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            fill=self.fill,
            outline=self.border,
            width=self.border_width,
            tags="rounded-panel",
        )
        self.tag_lower("rounded-panel")


class RoundedButton(tk.Canvas):
    """A small rounded Canvas button with hover and disabled states."""

    def __init__(
        self,
        master,
        text,
        command=None,
        *,
        bg="#1d2a43",
        fg="#edf4ff",
        activebackground="#2a3b5b",
        disabledbackground="#202b3c",
        font=("Segoe UI", 9, "bold"),
        padx=13,
        pady=9,
        radius=12,
        border="#2a3a55",
        **kwargs,
    ):
        self._text = str(text)
        self.command = command
        self._bg = bg
        self._fg = fg
        self._active_bg = activebackground
        self._disabled_bg = disabledbackground
        self._font = tkfont.Font(root=master, font=font)
        self._padx = padx
        self._pady = pady
        self._radius = radius
        self._border = border
        self._state = "normal"
        self._hover = False
        width = max(76, self._font.measure(self._text) + padx * 2 + 2)
        height = max(34, self._font.metrics("linespace") + pady * 2)
        super().__init__(
            master,
            width=width,
            height=height,
            bg=kwargs.pop("canvas_bg", master.cget("bg")),
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", self._draw)

    def configure(self, cnf=None, **kwargs):
        if cnf and isinstance(cnf, dict):
            kwargs.update(cnf)
        redraw = False
        mapping = {
            "text": "_text",
            "bg": "_bg",
            "fg": "_fg",
            "activebackground": "_active_bg",
            "disabledbackground": "_disabled_bg",
            "state": "_state",
            "command": "command",
            "border": "_border",
            "radius": "_radius",
            "padx": "_padx",
            "pady": "_pady",
        }
        canvas_options = {}
        for key, value in kwargs.items():
            if key == "font":
                self._font = tkfont.Font(root=self, font=value)
                redraw = True
            elif key in mapping:
                setattr(self, mapping[key], value)
                redraw = True
            else:
                canvas_options[key] = value
        if "text" in kwargs or "font" in kwargs or "padx" in kwargs:
            width = max(76, self._font.measure(self._text) + self._padx * 2 + 2)
            self.configure_canvas_width(width)
        if canvas_options:
            super().configure(**canvas_options)
        if redraw:
            self._draw()
        return None

    config = configure

    def configure_canvas_width(self, width):
        super().configure(width=width)

    def _on_enter(self, _event=None):
        if self._state != "disabled":
            self._hover = True
            self._draw()

    def _on_leave(self, _event=None):
        self._hover = False
        self._draw()

    def _on_click(self, _event=None):
        if self._state == "normal" and callable(self.command):
            self.command()

    def _draw(self, _event=None):
        self.delete("button-shape")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        if self._state == "disabled":
            fill = self._disabled_bg
            text_color = "#8290a6"
        elif self._hover:
            fill = self._active_bg
            text_color = self._fg
        else:
            fill = self._bg
            text_color = self._fg
        points = rounded_rectangle_points(1, 1, width - 1, height - 1, self._radius)
        self.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            fill=fill,
            outline=self._border,
            width=1,
            tags="button-shape",
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self._text,
            fill=text_color,
            font=self._font,
            tags="button-shape",
        )
