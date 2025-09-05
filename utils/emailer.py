# utils/emailer.py
import os, smtplib, mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def send_email(subject: str, html: str, attachments=None) -> bool:
    attachments = attachments or []
    user = os.getenv("SMTP_USER")
    pw   = os.getenv("SMTP_PASS")
    to   = os.getenv("EMAIL_TO")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))

    print("[mailer] Konfiguration:")
    print("  EMAIL_TO   =", to or "None")
    print("  SMTP_USER  =", user or "None")
    print("  SMTP_PASS? =", "JA" if pw else "NEIN")
    print("  HOST/PORT  =", host, port)
    print("  Attachments:", attachments if attachments else "[]")

    # Harte Validierung, sonst explizit fehlschlagen
    if not (user and pw and to):
        raise RuntimeError("SMTP env unvollständig: USER/PASS/EMAIL_TO erforderlich")

    try:
        msg = MIMEMultipart()
        msg["From"] = user           # Gmail erwartet die eigene Adresse hier
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html or "(leer)", "html"))

        for path in attachments:
            try:
                ctype, _ = mimetypes.guess_type(path)
                maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
                with open(path, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
                msg.attach(part)
            except Exception as e:
                print(f"[mailer] Anhang übersprungen ({path}): {e!r}")

        print(f"[mailer] Verbinde zu {host}:{port} …")
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(user, pw)
            server.sendmail(user, [to], msg.as_string())
        print(f"[mailer] Mail erfolgreich gesendet an {to}")
        return True

    except Exception as e:
        print("[mailer] FEHLER beim Senden:", repr(e))
        # Wichtig: False zurückgeben ODER Exception werfen; wir werfen weiter:
        raise
