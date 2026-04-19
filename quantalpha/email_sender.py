"""
QuantAlpha Email Sender

Sends HTML email briefs to subscribers via SMTP (Gmail/Google Workspace).
Supports:
- HTML email with inline styles (email client compatible)
- Subject line generation based on market conditions
- Rate-limited sending (avoid SMTP throttling)
- Delivery tracking and error handling
- BCC batch sending for privacy

Usage:
    sender = EmailSender()
    sender.send_brief(recipients=["user@example.com"], html_content="...", subject="...")
    sender.send_brief_batch(recipients=[...], html_content="...", subject="...")
"""

import json
import os
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─── Configuration ──────────────────────────────────────────────────────────────

SMTP_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "use_tls": True,
    # Credentials from environment or config
    "user_env": "QUANTALPHA_SMTP_USER",
    "pass_env": "QUANTALPHA_SMTP_PASS",
    "from_env": "QUANTALPHA_FROM_EMAIL",
}

# Rate limiting: max emails per batch, delay between sends
BATCH_SIZE = 50  # Gmail BCC limit
SEND_DELAY_SECONDS = 2  # Delay between individual sends
BATCH_DELAY_SECONDS = 10  # Delay between batches

# ─── Delivery Log ──────────────────────────────────────────────────────────────

DELIVERY_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "email_logs")
os.makedirs(DELIVERY_LOG_DIR, exist_ok=True)


class EmailSender:
    """SMTP email sender with rate limiting and delivery tracking."""

    def __init__(
        self,
        smtp_host: str = None,
        smtp_port: int = None,
        smtp_user: str = None,
        smtp_pass: str = None,
        from_email: str = None,
    ):
        self.smtp_host = smtp_host or SMTP_CONFIG["host"]
        self.smtp_port = smtp_port or SMTP_CONFIG["port"]
        self.smtp_user = smtp_user or os.environ.get(SMTP_CONFIG["user_env"], "")
        self.smtp_pass = smtp_pass or os.environ.get(SMTP_CONFIG["pass_env"], "")
        self.from_email = from_email or os.environ.get(SMTP_CONFIG["from_env"], "quantalpha@particulatellc.com")
        self.delivery_log = []

    def _log_delivery(self, recipient: str, subject: str, success: bool, error: str = None):
        """Log a delivery attempt."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recipient": recipient,
            "subject": subject,
            "success": success,
            "error": error,
        }
        self.delivery_log.append(entry)

    def _save_log(self):
        """Save delivery log to disk."""
        if not self.delivery_log:
            return
        
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = os.path.join(DELIVERY_LOG_DIR, f"delivery_{date_str}.json")
        
        # Load existing log if present
        existing = []
        if os.path.exists(log_file):
            try:
                with open(log_file) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        existing.extend(self.delivery_log)
        
        with open(log_file, "w") as f:
            json.dump(existing, f, indent=2, default=str)

    @staticmethod
    def generate_subject(report_data: Dict) -> str:
        """Generate an engaging subject line based on market conditions."""
        scores = report_data.get("composite_scores", {})
        date_str = datetime.now(timezone.utc).strftime("%b %d")
        
        # Find the strongest signal
        best_buy = None
        best_buy_score = 0
        worst_signal = None
        worst_score = 100
        
        for symbol, sd in scores.items():
            if not isinstance(sd, dict):
                continue
            score = sd.get("composite_score", 0)
            signal = str(sd.get("signal", "")).upper()
            
            if "BUY" in signal and score > best_buy_score:
                best_buy = symbol
                best_buy_score = score
            if "SELL" in signal and score < worst_score:
                worst_signal = symbol
                worst_score = score
        
        # Build subject line
        parts = [f"📊 QuantAlpha — {date_str}"]
        
        if best_buy and best_buy_score >= 70:
            parts.append(f"🟢 {best_buy.upper()} Buy Signal ({best_buy_score:.0f})")
        elif worst_signal and worst_score <= 30:
            parts.append(f"🔴 {worst_signal.upper()} Sell Signal ({worst_score:.0f})")
        elif scores:
            # Find top mover
            prices = report_data.get("prices", report_data.get("market", {}).get("prices", {}))
            if prices:
                top_change = 0
                top_coin = ""
                for coin_id, pd in prices.items():
                    if isinstance(pd, dict):
                        change = pd.get("usd_24h_change", 0)
                        if abs(change) > abs(top_change):
                            top_change = change
                            top_coin = pd.get("symbol", coin_id).upper()
                if top_coin and abs(top_change) > 2:
                    emoji = "📈" if top_change > 0 else "📉"
                    parts.append(f"{emoji} {top_coin} {top_change:+.1f}%")
        
        if len(parts) == 1:
            parts.append("Daily Market Intelligence")
        
        return " | ".join(parts)

    def send_brief(
        self,
        recipients: List[str],
        html_content: str,
        subject: str,
        tier: str = "premium",
    ) -> Tuple[int, int]:
        """
        Send a brief to a list of recipients via BCC.
        Returns (success_count, failure_count).
        """
        if not self.smtp_user or not self.smtp_pass:
            print("⚠️  SMTP credentials not configured. Set QUANTALPHA_SMTP_USER and QUANTALPHA_SMTP_PASS.")
            print(f"   Would send to {len(recipients)} recipients: {subject}")
            self._save_log()
            return 0, len(recipients)

        success = 0
        failures = 0

        # Send in batches (BCC for privacy)
        for i in range(0, len(recipients), BATCH_SIZE):
            batch = recipients[i:i + BATCH_SIZE]
            
            try:
                msg = MIMEMultipart("alternative")
                msg["From"] = f"QuantAlpha <{self.from_email}>"
                msg["Subject"] = subject
                msg["Bcc"] = ", ".join(batch)
                
                html_part = MIMEText(html_content, "html")
                msg.attach(html_part)
                
                # Send via SMTP
                if SMTP_CONFIG["use_tls"]:
                    context = ssl.create_default_context()
                    with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                        server.starttls(context=context)
                        server.login(self.smtp_user, self.smtp_pass)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                        server.login(self.smtp_user, self.smtp_pass)
                        server.send_message(msg)
                
                for r in batch:
                    self._log_delivery(r, subject, True)
                success += len(batch)
                print(f"✅ Sent batch {i // BATCH_SIZE + 1}: {len(batch)} recipients")
                
            except smtplib.SMTPAuthenticationError as e:
                print(f"❌ SMTP auth failed: {e}")
                for r in batch:
                    self._log_delivery(r, subject, False, str(e))
                failures += len(batch)
                break  # No point retrying with bad creds
                
            except smtplib.SMTPException as e:
                print(f"❌ SMTP error in batch {i // BATCH_SIZE + 1}: {e}")
                for r in batch:
                    self._log_delivery(r, subject, False, str(e))
                failures += len(batch)
                # Wait and retry next batch
                time.sleep(BATCH_DELAY_SECONDS)
                
            except Exception as e:
                print(f"❌ Unexpected error sending batch {i // BATCH_SIZE + 1}: {e}")
                for r in batch:
                    self._log_delivery(r, subject, False, str(e))
                failures += len(batch)
            
            # Rate limit between batches
            if i + BATCH_SIZE < len(recipients):
                time.sleep(BATCH_DELAY_SECONDS)
        
        self._save_log()
        
        if success > 0:
            print(f"📧 Email delivery complete: {success} sent, {failures} failed")
        
        return success, failures

    def send_test_email(self, recipient: str, html_content: str, subject: str = None) -> bool:
        """Send a test email to a single recipient. Returns True on success."""
        if subject is None:
            subject = f"🧪 QuantAlpha Test — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        
        success, failures = self.send_brief([recipient], html_content, subject)
        return success > 0


# ─── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="QuantAlpha Email Sender")
    parser.add_argument("--test", metavar="EMAIL", help="Send a test email to this address")
    parser.add_argument("--recipients", nargs="+", help="Email addresses to send to")
    parser.add_argument("--subject", help="Email subject line")
    parser.add_argument("--html-file", help="Path to HTML content file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without sending")
    
    args = parser.parse_args()
    sender = EmailSender()
    
    if args.test:
        # Generate a test brief
        html = """
        <div style="max-width:600px;margin:0 auto;font-family:sans-serif;padding:20px;">
            <h1 style="color:#0a0a2e;">📊 QuantAlpha Test Email</h1>
            <p>If you can read this, the email distribution system is working correctly.</p>
            <p>Timestamp: """ + datetime.now(timezone.utc).isoformat() + """</p>
            <hr>
            <p style="color:#666;font-size:12px;">QuantAlpha — Particulate LLC</p>
        </div>
        """
        print(f"🧪 Sending test email to {args.test}...")
        success = sender.send_test_email(args.test, html)
        print("✅ Test email sent!" if success else "❌ Test email failed")
    elif args.html_file:
        with open(args.html_file) as f:
            html = f.read()
        subject = args.subject or "QuantAlpha Premium Brief"
        if args.dry_run:
            print(f"📧 DRY RUN: Would send to {len(args.recipients or [])} recipients")
            print(f"   Subject: {subject}")
        elif args.recipients:
            sender.send_brief(args.recipients, html, subject)
        else:
            print("❌ --recipients required when using --html-file")
    else:
        parser.print_help()