# utils/emailer.py
from __future__ import annotations
import os, smtplib, mimetypes
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from pathlib import Path

try:
    from dotenv import load_dotenv  # optional
except Exception:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"

def _load_env_if_exists() -> None:
    # .env nur laden, wenn vorhanden – und niemals Secrets aus os.environ überschreiben
    if load_dotenv and ENV_FILE.exists():
        load_dotenv(dotenv_path=str(ENV_FILE), override=False)

def _cfg() -> dict:
    _load_env_if_exists()
    cfg = {
        "EMAIL_TO" : os.getenv("EMAIL_TO"),
        "SMTP_USER": os.getenv("SMTP_USER"),
        "SMTP_PASS": os.getenv("SMTP_PASS"),
        "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
    }
    missing = [k for k in ("EMAIL_TO","SMTP_USER","SMTP_PASS") if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"SMTP env unvollständig: fehlend {', '.join(missing)}")
    return cfg

def _attach(msg: MIMEMultipart, files: Optional[List[str]]) -> None:
    for path in files or []:
        ptype, enc = mimetypes.guess_type(path)
        if enc: ptype = None
        maintype, subtype = (ptype or "application/octet-stream").split("/", 1)
        with open(path, "rb") as f:
            part = MIMEBase(maintype, subtype)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        msg.attach(part)

def send_email(subject: str, html: str, attachments: Optional[List[str]] = None) -> bool:
    cfg = _cfg()
    msg = MIMEMultipart()
    msg["From"] = cfg["SMTP_USER"]
    msg["To"] = cfg["EMAIL_TO"]
    msg["Subject"] = subject
    msg.attach(MIMEText(html or "(leer)", "html", "utf-8"))
    _attach(msg, attachments)

    print("[mailer] EMAIL_TO   =", cfg["EMAIL_TO"])
    print("[mailer] SMTP_USER  =", cfg["SMTP_USER"])
    print("[mailer] SMTP_PASS? =", "JA")
    print("[mailer] HOST/PORT  =", cfg["SMTP_HOST"], cfg["SMTP_PORT"])
    print("[mailer] Attachments:", attachments or "[]")

    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
        server.sendmail(cfg["SMTP_USER"], [cfg["EMAIL_TO"]], msg.as_string())
    print("[mailer] Mail erfolgreich gesendet an", cfg["EMAIL_TO"])
    return True
