# utils/emailer.py
from __future__ import annotations

import os, smtplib, mimetypes
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from dotenv import load_dotenv

# --- .env robust laden (fester Pfad für Codespaces/Repo) ---
ENV_PATH = "/workspaces/trading-agent/.env"
load_dotenv(dotenv_path=ENV_PATH)

def _cfg():
    return {
        "EMAIL_TO": os.getenv("bouardjaa@gmail.com"),
        "SMTP_USER": os.getenv("bouardjaa@gmail.com"),
        "SMTP_PASS": os.getenv("zwqdwuyxdzydtaqu"),
        "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
    }

# Debug
_cfg_now = _cfg()
print("[emailer] Konfiguration:")
print(f"  EMAIL_TO  = {_cfg_now['EMAIL_TO']}")
print(f"  SMTP_USER = {_cfg_now['SMTP_USER']}")
print(f"  SMTP_PASS gesetzt? {'JA' if _cfg_now['SMTP_PASS'] else 'NEIN'}")
print(f"  SMTP_HOST = {_cfg_now['SMTP_HOST']}")
print(f"  SMTP_PORT = {_cfg_now['SMTP_PORT']}")
print(f"  .env Pfad = {ENV_PATH}")

def _attach(msg: MIMEMultipart, files: Optional[List[str]]):
    if not files: return
    for path in files:
        if not path or not os.path.isfile(path):
            print(f"[emailer] Anhang fehlt/übersprungen: {path}")
            continue
        ctype, enc = mimetypes.guess_type(path)
        if ctype is None or enc is not None:
            ctype = "application/octet-stream"
        mt, st = ctype.split("/", 1)
        with open(path, "rb") as f:
            part = MIMEBase(mt, st)
            part.set_payload(f.read())
            encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=os.path.basename(path))
        msg.attach(part)

def send_email(subject: str, body_html: str, attachments: Optional[List[str]] = None) -> bool:
    cfg = _cfg()
    missing = [k for k in ("EMAIL_TO", "SMTP_USER", "SMTP_PASS") if not cfg[k]]
    if missing:
        print(f"[mailer] Email nicht konfiguriert (fehlt: {', '.join(missing)}) – Überspringe Versand.")
        return False

    msg = MIMEMultipart()
    msg["From"] = cfg["SMTP_USER"]
    msg["To"] = cfg["EMAIL_TO"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))
    _attach(msg, attachments)

    try:
        print(f"[mailer] Verbinde zu {cfg['SMTP_HOST']}:{cfg['SMTP_PORT']} …")
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            print(f"[mailer] Login als {cfg['SMTP_USER']} …")
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.send_message(msg)
        print(f"[mailer] Mail erfolgreich an {cfg['EMAIL_TO']} gesendet.")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print("[mailer] SMTPAuthenticationError – Login abgelehnt (App-Passwort/Account prüfen).")
        print("         Gmail-App-Passwort (16-stellig), richtige Adresse, 2FA aktiv.")
        print(f"         Details: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"[mailer] SMTP Fehler: {e}")
        return False
    except Exception as e:
        print(f"[mailer] Unerwarteter Fehler: {e}")
        return False
