"""Почтовый клиент IMAP/SMTP. Секреты хранятся в системном хранилище Windows."""
import imaplib
import smtplib
import email
from email.header import decode_header
from email.message import EmailMessage
import keyring

SERVICE = "Dimasik-Mail"


class EmailManager:
    def save_account(self, address, password, imap_host, smtp_host, smtp_port=587):
        address = address.strip().lower()
        if not address or not password or not imap_host or not smtp_host:
            raise ValueError("Заполни адрес, пароль приложения и серверы IMAP/SMTP.")
        keyring.set_password(SERVICE, address, password)
        return {"address": address, "imap_host": imap_host, "smtp_host": smtp_host,
                "smtp_port": int(smtp_port)}

    def disconnect(self, address):
        keyring.delete_password(SERVICE, address.lower())

    @staticmethod
    def _decode(value):
        parts = decode_header(value or "")
        return "".join((part.decode(enc or "utf-8", errors="replace")
                        if isinstance(part, bytes) else part) for part, enc in parts)

    def list_messages(self, account, limit=20):
        address = account["address"].lower()
        password = keyring.get_password(SERVICE, address)
        if not password:
            raise RuntimeError("Пароль приложения не найден. Подключи почту заново.")
        client = imaplib.IMAP4_SSL(account["imap_host"])
        try:
            client.login(address, password)
            client.select("INBOX", readonly=True)
            status, data = client.search(None, "ALL")
            if status != "OK":
                raise RuntimeError("Не удалось получить список писем.")
            ids = data[0].split()[-max(1, min(int(limit), 50)):]
            result = []
            for msg_id in reversed(ids):
                status, chunks = client.fetch(msg_id, "(RFC822)")
                if status != "OK" or not chunks or not isinstance(chunks[0], tuple):
                    continue
                msg = email.message_from_bytes(chunks[0][1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain" and not part.get_filename():
                            raw = part.get_payload(decode=True)
                            if raw:
                                body = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
                                break
                elif msg.get_content_type() == "text/plain":
                    raw = msg.get_payload(decode=True)
                    if raw:
                        body = raw.decode(msg.get_content_charset() or "utf-8", errors="replace")
                result.append({"from": self._decode(msg.get("From")), "subject": self._decode(msg.get("Subject")),
                               "date": msg.get("Date", ""), "body": body[:12000]})
            return result
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def send_message(self, account, recipient, subject, body):
        address = account["address"].lower()
        password = keyring.get_password(SERVICE, address)
        if not password:
            raise RuntimeError("Почтовый пароль приложения не найден.")
        message = EmailMessage()
        message["From"] = address
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(account["smtp_host"], int(account.get("smtp_port", 587)), timeout=20) as smtp:
            smtp.starttls()
            smtp.login(address, password)
            smtp.send_message(message)
