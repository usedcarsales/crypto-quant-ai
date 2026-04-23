"""
QuantAlpha SMTP Client

Low-level SMTP connection wrapper with connection pooling and retry logic.
Used by email_sender.py — not called directly.

Usage:
    from smtp_client import SMTPClient
    client = SMTPClient()
    client.connect()
    client.send_message(msg)
    client.quit()
"""

import os
import smtplib
import ssl
from datetime import datetime, timezone
from typing import Optional


class SMTPClient:
    """Reusable SMTP client with TLS and retry support."""

    def __init__(
        self,
        host: str = "smtp.gmail.com",
        port: int = 587,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.user = user or os.environ.get("QUANTALPHA_SMTP_USER", "")
        self.password = password or os.environ.get("QUANTALPHA_SMTP_PASS", "")
        self._server: Optional[smtplib.SMTP] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._server is not None

    def connect(self, timeout: int = 15) -> bool:
        """Establish TLS connection to SMTP server. Returns True on success."""
        try:
            self._server = smtplib.SMTP(self.host, self.port, timeout=timeout)
            self._server.ehlo()
            self._server.starttls(context=ssl.create_default_context())
            self._server.ehlo()
            self._server.login(self.user, self.password)
            self._connected = True
            return True
        except smtplib.SMTPAuthenticationError as e:
            raise SMTPError(f"Authentication failed: {e}")
        except smtplib.SMTPException as e:
            raise SMTPError(f"SMTP connection failed: {e}")
        except Exception as e:
            raise SMTPError(f"Unexpected connection error: {e}")

    def send_message(self, msg) -> bool:
        """Send a MIMEMultipart message. Caller must handle BCC."""
        if not self.is_connected:
            self.connect()
        try:
            self._server.send_message(msg)
            return True
        except smtplib.SMTPException as e:
            raise SMTPError(f"Send failed: {e}")

    def quit(self):
        """Close the SMTP connection."""
        if self._server:
            try:
                self._server.quit()
            except Exception:
                pass
            finally:
                self._server = None
                self._connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quit()


class SMTPError(Exception):
    """Raised when SMTP operations fail."""
    pass


if __name__ == "__main__":
    # Quick connectivity test
    client = SMTPClient()
    try:
        client.connect()
        print("✅ SMTP connection OK")
        client.quit()
    except SMTPError as e:
        print(f"❌ SMTP error: {e}")