from __future__ import annotations

import base64
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    raise SystemExit("Install dependency: py -m pip install cryptography")

APP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "DimasikLicenseManager"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "licenses.sqlite3"
PRIVATE_KEY = APP_DIR / "signing_key.pem"
PUBLIC_KEY = APP_DIR / "signing_public.pem"
UTC = timezone.utc


def now():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds")


def load_or_create_key():
    if PRIVATE_KEY.exists():
        key = serialization.load_pem_private_key(PRIVATE_KEY.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError("Неверный формат ключа подписи")
        return key
    key = Ed25519PrivateKey.generate()
    PRIVATE_KEY.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    try:
        os.chmod(PRIVATE_KEY, 0o600)
    except OSError:
        pass
    PUBLIC_KEY.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return key


class LicenseManager:
    def __init__(self, root):
        self.root = root
        self.key = load_or_create_key()
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS licenses(
            id TEXT PRIMARY KEY, customer TEXT NOT NULL, plan TEXT NOT NULL,
            expires_at TEXT, device_id TEXT NOT NULL, created_at TEXT NOT NULL,
            last_transfer_at TEXT, revoked INTEGER NOT NULL DEFAULT 0)""")
        self.db.commit()
        self.build()

    def build(self):
        self.root.title("Dimasik License Manager")
        self.root.geometry("920x600")
        self.root.minsize(760, 480)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=27)
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="DIMASIK LICENSE MANAGER", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Button(top, text="Экспорт публичного ключа", command=self.export_public).pack(side="right")
        form = ttk.LabelFrame(self.root, text="Новая лицензия", padding=10)
        form.pack(fill="x", padx=12, pady=5)
        self.customer = tk.StringVar()
        self.plan = tk.StringVar(value="Pro")
        self.days = tk.StringVar(value="30")
        self.device = tk.StringVar()
        for col, (label, var, width) in enumerate([
            ("Пользователь", self.customer, 22), ("Тариф", self.plan, 12),
            ("Дней", self.days, 8), ("Device ID", self.device, 34)]):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=4)
            if label == "Тариф":
                ttk.Combobox(form, textvariable=var, values=("Free", "Pro", "Ultimate"), width=width, state="readonly").grid(row=1, column=col, padx=4, sticky="ew")
            else:
                ttk.Entry(form, textvariable=var, width=width).grid(row=1, column=col, padx=4, sticky="ew")
        ttk.Button(form, text="Создать и сохранить лицензию", command=self.create_license).grid(row=1, column=4, padx=8)
        form.columnconfigure(0, weight=1)
        table_frame = ttk.Frame(self.root, padding=(12, 8))
        table_frame.pack(fill="both", expand=True)
        cols = ("id", "customer", "plan", "expires", "device", "status")
        self.table = ttk.Treeview(table_frame, columns=cols, show="headings")
        for c, title, width in zip(cols, ("ID", "Пользователь", "Тариф", "Действует до", "Device ID", "Статус"), (190, 150, 90, 165, 170, 80)):
            self.table.heading(c, text=title)
            self.table.column(c, width=width, anchor="w")
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        actions = ttk.Frame(self.root, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Импорт запроса переноса", command=self.import_transfer).pack(side="left")
        ttk.Button(actions, text="Отозвать выбранную", command=self.revoke).pack(side="left", padx=8)
        ttk.Button(actions, text="Обновить", command=self.refresh).pack(side="left")
        ttk.Label(self.root, text=f"Данные и закрытый ключ хранятся локально: {APP_DIR}", foreground="#666").pack(anchor="w", padx=14, pady=(0, 8))
        self.refresh()

    def signed(self, payload):
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        sig = self.key.sign(raw)
        return {"payload": payload, "signature": base64.b64encode(sig).decode(), "algorithm": "Ed25519"}

    def save_license(self, payload, suggested):
        data = self.signed(payload)
        path = filedialog.asksaveasfilename(defaultextension=".dimalic", initialfile=suggested,
            filetypes=[("Dimasik license", "*.dimalic"), ("JSON", "*.json")])
        if path:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("Готово", f"Лицензия сохранена:\n{path}")

    def create_license(self):
        customer = self.customer.get().strip()
        device = self.device.get().strip().lower()
        if not customer or not device:
            messagebox.showwarning("Не хватает данных", "Укажи пользователя и Device ID.")
            return
        try:
            days = int(self.days.get())
            if days not in (7, 30, 90, 180, 365, 0):
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Срок", "Допустимо: 7, 30, 90, 180, 365 или 0 (бессрочно).")
            return
        created = now()
        lid = str(uuid.uuid4())
        expiry = None if days == 0 else iso(created + timedelta(days=days))
        payload = {"schema": 1, "license_id": lid, "customer": customer,
                   "plan": self.plan.get(), "issued_at": iso(created),
                   "expires_at": expiry, "device_id": device}
        self.db.execute("INSERT INTO licenses(id,customer,plan,expires_at,device_id,created_at) VALUES(?,?,?,?,?,?)",
                        (lid, customer, self.plan.get(), expiry, device, iso(created)))
        self.db.commit()
        self.save_license(payload, f"Dimasik-{lid[:8]}.dimalic")
        self.refresh()

    def export_public(self):
        path = filedialog.asksaveasfilename(defaultextension=".pem", initialfile="dimasik_license_public.pem")
        if path:
            Path(path).write_bytes(self.key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
            messagebox.showinfo("Публичный ключ", "Экспортирован. Его можно встроить в приложение Димасик. Закрытый ключ никому не отправляй.")

    def import_transfer(self):
        path = filedialog.askopenfilename(filetypes=[("Transfer request", "*.dimareq"), ("JSON", "*.json")])
        if not path:
            return
        try:
            req = json.loads(Path(path).read_text(encoding="utf-8"))
            lid, new_device = req["license_id"], req["new_device_id"].lower()
            row = self.db.execute("SELECT * FROM licenses WHERE id=?", (lid,)).fetchone()
            if not row or row["revoked"]:
                raise ValueError("Лицензия не найдена или отозвана.")
            last = datetime.fromisoformat(row["last_transfer_at"]) if row["last_transfer_at"] else None
            if last and now() - last < timedelta(days=7):
                allowed = last + timedelta(days=7)
                raise ValueError("Перенос пока недоступен. Следующая дата: " + iso(allowed))
            self.db.execute("UPDATE licenses SET device_id=?, last_transfer_at=? WHERE id=?", (new_device, iso(now()), lid))
            self.db.commit()
            payload = {"schema": 1, "license_id": lid, "customer": row["customer"],
                       "plan": row["plan"], "issued_at": row["created_at"],
                       "expires_at": row["expires_at"], "device_id": new_device}
            self.save_license(payload, f"Dimasik-{lid[:8]}-transfer.dimalic")
            self.refresh()
        except Exception as e:
            messagebox.showerror("Перенос не выполнен", str(e))

    def revoke(self):
        selected = self.table.selection()
        if not selected:
            return
        lid = selected[0]
        if messagebox.askyesno("Отзыв", "Отозвать лицензию? Клиенту нужно передать обновлённый статус отдельно."):
            self.db.execute("UPDATE licenses SET revoked=1 WHERE id=?", (lid,))
            self.db.commit()
            self.refresh()

    def refresh(self):
        for item in self.table.get_children():
            self.table.delete(item)
        for r in self.db.execute("SELECT * FROM licenses ORDER BY created_at DESC"):
            status = "Отозвана" if r["revoked"] else "Активна"
            self.table.insert("", "end", iid=r["id"], values=(r["id"], r["customer"], r["plan"], r["expires_at"] or "Бессрочно", r["device_id"], status))


if __name__ == "__main__":
    root = tk.Tk()
    app = LicenseManager(root)
    root.mainloop()
