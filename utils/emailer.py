from __future__ import annotations
import os, ssl, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

EMAIL_TO  = os.environ.get("EMAIL_TO", "").strip()
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

def send_email(subject: str, html: str, attachments: list[str] | None = None):
    if not (EMAIL_TO and SMTP_USER and SMTP_PASS):
        print("[mailer] Email nicht konfiguriert – Überspringe Versand.")
        return
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"]   = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    for path in attachments or []:
        with open(path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
        msg.attach(part)

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=ctx)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print("[mailer] E-Mail gesendet an", EMAIL_TO)
