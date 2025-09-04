# utils/emailer.py
from __future__ import annotations

import os
import smtplib
import mimetypes
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders

from dotenv import load_dotenv

# --------------------------------------------------------------------
# .env robust und pfadsicher laden (utils/ -> Projektroot -> .env)
# --------------------------------------------------------------------
THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
load_dotenv(dotenv_path=ENV_PATH)

def _get_env():
    return {
        "EMAIL_TO": os.getenv("bouardjaa@gmail.com"),
        "SMTP_USER": os.getenv("bouardjaa@gmail.com"),
        "SMTP_PASS": os.getenv("zwqdwuyxdzydtaqu"),
        "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
    }

# Debug: zeige geladene Konfiguration (Passwort natürlich nur maskiert)
_cfg = _get_env()
print("[emailer] Konfiguration geladen (env):")
print(f"  EMAIL_TO  = {_cfg['EMAIL_TO']}")
print(f"  SMTP_USER = {_cfg['SMTP_USER']}")
print(f"  SMTP_PASS gesetzt? {'JA' if _cfg['SMTP_PASS'] else 'NEIN'}")
print(f"  SMTP_HOST = {_cfg['SMTP_HOST']}")
print(f"  SMTP_PORT = {_cfg['SMTP_PORT']}")
print(f"  .env Pfad = {ENV_PATH}")


def _attach_files(msg: MIMEMultipart, attachments: Optional[List[str]]) -> None:
    if not attachments:
        return
    for path in attachments:
        if not path or not os.path.isfile(path):
            print(f"[emailer] Anhang übersprungen (nicht gefunden): {path}")
            continue
        ctype, encoding = mimetypes.guess_type(path)
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)

        with open(path, "rb") as fp:
            part = MIMEBase(maintype, subtype)
            part.set_payload(fp.read())
            encoders.encode_base64(part)
        filename = os.path.basename(path)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)


def send_email(subject: str, body_html: str, attachments: Optional[List[str]] = None) -> bool:
    """
    Sendet eine HTML-Mail (optional mit Attachments).
    Gibt True/False zurück, je nach Erfolg.
    """
    cfg = _get_env()
    missing = [k for k in ("EMAIL_TO", "SMTP_USER", "SMTP_PASS") if not cfg.get(k)]
    if missing:
        print(f"[mailer] Email nicht konfiguriert (fehlt: {', '.join(missing)}) – Überspringe Versand.")
        return False

    msg = MIMEMultipart()
    msg["From"] = cfg["SMTP_USER"]
    msg["To"] = cfg["EMAIL_TO"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    _attach_files(msg, attachments)

    try:
        print(f"[mailer] Verbinde zu {cfg['SMTP_HOST']}:{cfg['SMTP_PORT']} …")
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as server:
            # STARTTLS für Port 587
            server.ehlo()
            server.starttls()
            server.ehlo()
            print(f"[mailer] Login als {cfg['SMTP_USER']} …")
            server.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            server.send_message(msg)
        print(f"[mailer] Mail erfolgreich an {cfg['EMAIL_TO']} gesendet.")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print("[mailer] SMTPAuthenticationError – Login fehlgeschlagen.")
        print("         Prüfe bitte: Gmail-App-Passwort, SMTP_USER, 2FA aktiv, "
              "und dass App-Passwort genau kopiert wurde.")
        print(f"         Details: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"[mailer] SMTP Fehler: {e}")
        return False
    except Exception as e:
        print(f"[mailer] Unerwarteter Fehler: {e}")
        return False
