import base64, hashlib, json, platform, uuid
from datetime import datetime, timezone
from pathlib import Path
PUBLIC_KEY_PEM = b'PASTE_OWNER_PUBLIC_KEY_PEM_HERE'
def device_id():
    value = platform.node()
    if platform.system() == 'Windows':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\\Microsoft\\Cryptography') as k: value += winreg.QueryValueEx(k, 'MachineGuid')[0]
        except OSError: value += str(uuid.getnode())
    return hashlib.sha256(value.encode()).hexdigest()
def create_transfer_request(license_path, output_path):
    data = json.loads(Path(license_path).read_text(encoding='utf-8'))
    req = {'schema':1,'license_id':data['payload']['license_id'],'new_device_id':device_id(),'requested_at':datetime.now(timezone.utc).isoformat()}
    Path(output_path).write_text(json.dumps(req,ensure_ascii=False,indent=2),encoding='utf-8')
def verify_license(license_path, check_device=True):
    try:
        from cryptography.hazmat.primitives import serialization
        if b'PASTE_OWNER_PUBLIC_KEY' in PUBLIC_KEY_PEM: return False,'Не встроен публичный ключ владельца.',None
        env=json.loads(Path(license_path).read_text(encoding='utf-8')); p=env['payload']
        raw=json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        serialization.load_pem_public_key(PUBLIC_KEY_PEM).verify(base64.b64decode(env['signature'],validate=True),raw)
        if env.get('algorithm')!='Ed25519' or p.get('schema')!=1: return False,'Неподдерживаемый формат.',None
        if check_device and p.get('device_id')!=device_id(): return False,'Лицензия для другого ПК.',p
        if p.get('expires_at') and datetime.now(timezone.utc)>=datetime.fromisoformat(p['expires_at']): return False,'Срок лицензии истёк.',p
        return True,'Лицензия действительна.',p
    except ImportError: return False,'Установи cryptography.',None
    except Exception as e: return False,f'Лицензия недействительна: {e}',None
