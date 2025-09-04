#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from dotenv import load_dotenv

def main():
    # .env im Projekt-Root laden
    load_dotenv(dotenv_path=".env")

    print("===== ENV TEST =====")
    print("EMAIL_TO =", os.getenv("EMAIL_TO", "NICHT GESETZT"))
    print("SMTP_USER =", os.getenv("SMTP_USER", "NICHT GESETZT"))

    pw = os.getenv("SMTP_PASS")
    if pw:
        print("SMTP_PASS =", pw[:4] + "******** (gesetzt)")
    else:
        print("SMTP_PASS = NICHT GESETZT")

    print("SMTP_HOST =", os.getenv("SMTP_HOST", "NICHT GESETZT"))
    print("SMTP_PORT =", os.getenv("SMTP_PORT", "NICHT GESETZT"))
    print("TZ =", os.getenv("TZ", "NICHT GESETZT"))
    print("====================")

if __name__ == "__main__":
    main()
