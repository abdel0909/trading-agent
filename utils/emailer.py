import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()  # <-- lädt .env beim Import

SMTP_USER = os.getenv("bouardjaa@gmail.com")
SMTP_PASS = os.getenv("zwqdwuyxdzydtaqu")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_TO  = os.getenv("bouardjaa@gmail.com")

# Debug-Ausgabe beim Start
print("[emailer] Konfiguration geladen:")
print(f"  SMTP_USER = {SMTP_USER}")
print(f"  SMTP_PASS gesetzt? {'JA' if SMTP_PASS else 'NEIN'}")
print(f"  SMTP_HOST = {SMTP_HOST}")
print(f"  SMTP_PORT = {SMTP_PORT}")
print(f"  EMAIL_TO  = {EMAIL_TO}")


def send_email(subject: str, body: str, attachments: list[str] = None):
    """Sende eine E-Mail mit optionalen Anhängen."""
    if not (SMTP_USER and SMTP_PASS and EMAIL_TO):
        print("[mailer] Email nicht konfiguriert – Überspringe Versand.")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "html"))

        # Verbindung aufbauen
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        print(f"[mailer] Mail erfolgreich an {EMAIL_TO} gesendet.")

    except Exception as e:
        print(f"[mailer] Fehler beim Mailversand: {e}")
