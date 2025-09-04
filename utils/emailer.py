# utils/emailer.py
from __future__ import annotations

import os, smtplib, mimetypes
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from dotenv import load_dotenv, dotenv_values

# --- .env robust laden (unabhängig vom Startpfad) ---
THIS_FILE = os.path.abspath(__file__)
BASE_DIR  = os.path.dirname(os.path.dirname(THIS_FILE))  # Projekt-Root
ENV_PATH  = os.path.join(BASE_DIR, ".env")

print("[emailer] BASE_DIR =", BASE_DIR)
print("[emailer] ENV_PATH =", ENV_PATH)
print("[emailer] .env existiert? ->", os.path.exists(ENV_PATH))

parsed = dotenv_values(ENV_PATH) if os.path.exists(ENV_PATH) else {}
print("[emailer] dotenv_values(.env) ->", parsed if parsed else "<leer/fehlt>")

loaded = load_dotenv(dotenv_path=ENV_PATH, override=True)
print("[emailer] load_dotenv ->", loaded)

def _cfg() -> dict:
    # Host-Alias kompatibel machen (SMTP_HOST oder SMTP_SERVER)
    host = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER") or "smtp.gmail.com"
    # Wenn EMAIL_TO fehlt, auf SMTP_USER fallen (wie im anderen Repo)
    email_to = os.getenv("EMAIL_TO") or os.getenv("SMTP_USER")
    return {
        "EMAIL_TO":  email_to,
        "SMTP_USER": os.getenv("bouardjaa@gmail.com"),
        "SMTP_PASS": os.getenv("zwqdwuyxdzydtaqu"),
        "SMTP_HOST": host,
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
    }

# Debug der geladenen Werte
_cfg0 = _cfg()
print("[emailer] Geladene Konfiguration:")
print("  EMAIL_TO  =", _cfg0["EMAIL_TO"])
print("  SMTP_USER =", _cfg0["SMTP_USER"])
print("  SMTP_PASS =", "***gesetzt***" if _cfg0["SMTP_PASS"] else "FEHLT")
print("  SMTP_HOST =", _cfg0["SMTP_HOST"])
print("  SMTP_PORT =", _cfg0["SMTP_PORT"])

def _attach_files(msg: MIMEMultipart, attachments: Optional[List[str]]) -> None:
    if not attachments: 
        return
    for path in attachments:
        if not path or not os.path.isfile(path):
            print(f"[emailer] Anhang übersprungen (nicht gefunden): {path}")
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
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            print(f"[mailer] Login als {cfg['SMTP_USER']} …")
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.send_message(msg)
        print(f"[mailer] Mail erfolgreich an {cfg['EMAIL_TO']} gesendet.")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print("[mailer] SMTPAuthenticationError – Login abgelehnt. Details:", e)
        print("         Prüfe: 16-stelliges Gmail-App-Passwort, korrekte Adresse, 2FA aktiv.")
        return False
    except smtplib.SMTPException as e:
        print("[mailer] SMTP Fehler:", e); return False
    except Exception as e:
        print("[mailer] Unerwarteter Fehler:", e); return False
