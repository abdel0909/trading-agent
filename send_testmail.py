#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, smtplib, ssl
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def main():
    # .env laden
    load_dotenv(".env")

    sender = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    receiver = os.getenv("EMAIL_TO")

    # Mail bauen
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = "Testmail vom Trading-Agent"
    msg.attach(MIMEText("✅ Diese Testmail bestätigt, dass SMTP funktioniert.", "plain"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls(context=context)
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())

        print("[OK] Testmail gesendet an", receiver)

    except Exception as e:
        print("[FEHLER] Konnte Mail nicht senden:", e)

if __name__ == "__main__":
    main()
