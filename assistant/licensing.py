"""Offline license verification for Dimasik (Ed25519)."""
from __future__ import annotations
import base64, hashlib, json, os, platform, sys, time
from pathlib import Path
from typing import Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
PUBLIC_KEY = ROOT / "license_public.pem"
DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "Dimasik"
LICENSE = DATA / "license.dimalic"
STATE = DATA / "license.state"

class LicenseError(Exception):
    pass

def device_id() -> str:
    value = ""
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                value = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            pass
    value = value or platform.node() or platform.machine()
    return hashlib.sha256(("dimasik|" + value).encode()).hexdigest()

def validate_license(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else LICENSE
    try:
        envelope = json.loads(target.read_text(encoding="utf-8"))
        payload = envelope["payload"]
        signature = base64.b64decode(envelope["signature"], validate=True)
        public = serialization.load_pem_public_key(PUBLIC_KEY.read_bytes())
        if not isinstance(public, Ed25519PublicKey):
            raise ValueError("Invalid public key")
        message = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        public.verify(signature, message)
    except FileNotFoundError as exc:
        raise LicenseError("Не найдена лицензия или публичный ключ.") from exc
    except Exception as exc:
        raise LicenseError("Подпись лицензии недействительна или файл повреждён.") from exc
    if payload.get("product") != "dimasik" or payload.get("status") != "active":
        raise LicenseError("Лицензия недействительна или отключена.")
    if payload.get("device_id") != device_id():
        raise LicenseError("Лицензия выдана для другого компьютера.")
    expires = payload.get("expires_at")
    now = int(time.time())
    if expires is not None and (not isinstance(expires, int) or now > expires):
        raise LicenseError("Срок действия лицензии истёк.")
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        previous = int(STATE.read_text(encoding="ascii"))
        if now + 300 < previous:
            raise LicenseError("Обнаружен перевод системных часов назад.")
    except FileNotFoundError:
        previous = now
    except (OSError, ValueError) as exc:
        raise LicenseError("Не удалось проверить локальное состояние лицензии.") from exc
    STATE.write_text(str(max(now, previous)), encoding="ascii")
    return payload

def activate_license(source: str | Path) -> dict[str, Any]:
    payload = validate_license(source)
    DATA.mkdir(parents=True, exist_ok=True)
    LICENSE.write_bytes(Path(source).read_bytes())
    return payload

def create_transfer_request(output: str | Path) -> Path:
    try:
        current = validate_license()
        license_id = current["license_id"]
    except LicenseError:
        license_id = ""
    request = {"product": "dimasik", "license_id": license_id, "device_id": device_id(),
               "device_name": platform.node(), "requested_at": int(time.time())}
    target = Path(output)
    target.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    return target

def current_license() -> dict[str, Any]:
    """Return the active signed license, or the built-in Free entitlement."""
    try:
        return validate_license()
    except LicenseError:
        return {"plan": "free", "status": "free", "license_id": "free"}


def feature_allowed(feature: str) -> bool:
    return plan_allows(current_license().get("plan", "free"), feature)


def plan_allows(plan: str, feature: str) -> bool:
    access = {"free": {"chat", "basic_tools"},
              "pro": {"chat", "basic_tools", "granite", "code", "files"},
              "ultimate": {"chat", "basic_tools", "granite", "code", "files", "image", "api", "priority"}}
    return feature in access.get(str(plan).lower(), set())
