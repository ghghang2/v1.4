"""
Simple script to send an email notification via Gmail SMTP.

Prerequisites:
- Enable "App passwords" in your Google Account and create an app password for
  this script (or use a regular password if you have "Less secure apps" turned
  on – though that is not recommended).
- The script uses the Gmail SMTP server: smtp.gmail.com on port 587.

Usage:
    python send_email.py

Replace the placeholder values in the ``main`` function with your own
credentials and message details.
"""

import smtplib
from email.message import EmailMessage
import os

def send_email(
    smtp_server: str,
    smtp_port: int,
    login: str,
    password: str,
    subject: str,
    body: str,
    to_addr: str,
) -> None:
    """Send a plain‑text email via the specified SMTP server.

    Parameters
    ----------
    smtp_server: str
        SMTP host (e.g., "smtp.gmail.com").
    smtp_port: int
        SMTP port (587 for TLS, 465 for SSL).
    login: str
        Email address used to authenticate.
    password: str
        Password or app password for the account.
    subject: str
        Subject line of the email.
    body: str
        Plain‑text body of the email.
    to_addr: str
        Recipient email address.
    """
    msg = EmailMessage()
    msg['From'] = login
    msg['To'] = to_addr
    msg['Subject'] = subject
    msg.set_content(body)

    # Connect to the Gmail SMTP server using TLS
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(login, password)
        server.send_message(msg)
        print("Email sent successfully to", to_addr)


def main():
    # Replace these values with your own credentials and message
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    LOGIN = "ghghang2@gmail.com"
    PASSWORD = os.getenv("GHG_APP_PASSWORD")
    TO_ADDR = "ghghang2@gmail.com"
    SUBJECT = "Test Email"
    BODY = "This is a test email sent from a minimal Python script."

    send_email(
        smtp_server=SMTP_SERVER,
        smtp_port=SMTP_PORT,
        login=LOGIN,
        password=PASSWORD,
        subject=SUBJECT,
        body=BODY,
        to_addr=TO_ADDR,
    )


if __name__ == "__main__":
    main()
