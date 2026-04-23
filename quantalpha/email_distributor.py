"""
QuantAlpha Email Distributor

Orchestrates the full email distribution pipeline:
1. Generate brief data from the daily brief engine
2. Format into HTML using the premium email template
3. Look up subscribers from the subscription manager
4. Send via the email sender with delivery tracking
5. Log results for monitoring

Usage:
    python -m quantalpha.email_distributor --tier premium --send
    python -m quantalpha.email_distributor --tier premium --dry-run
    python -m quantalpha.email_distributor --tier premium --preview
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from quantalpha.email_template import render_premium_email
from quantalpha.formatter import format_free_brief, FREE_COINS
from quantalpha.subscriptions import SubscriptionManager
from quantalpha.email_sender import EmailSender


# ─── Template Renderer (delegated to email_template.py) ─────────────────────

# render_premium_email is now imported from quantalpha.email_template
# The email_distributor orchestrates; email_template handles rendering

# ─── Distribution Orchestrator ─────────────────────────────────────────────────

class EmailDistributor:
    """Orchestrates the full email distribution pipeline."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.subscription_mgr = SubscriptionManager()
        self.email_sender = EmailSender()
    
    def generate_report_data(self, coins=None) -> Dict:
        """Generate brief data using the daily brief engine."""
        try:
            from skills.brief_engine.daily_brief import generate_brief
            json_brief = generate_brief(format="json", coins=coins)
            return json.loads(json_brief)
        except Exception as e:
            print(f"⚠️  Error generating report data: {e}")
            # Fallback: try to load cached data
            return self._load_cached_data()
    
    def _load_cached_data(self) -> Dict:
        """Load the most recent cached brief data."""
        cache_dir = os.path.join(PROJECT_ROOT, "data", "brief_cache")
        if not os.path.exists(cache_dir):
            return {"composite_scores": {}, "prices": {}, "smart_money": {}}
        
        files = sorted([f for f in os.listdir(cache_dir) if f.endswith(".json")], reverse=True)
        if not files:
            return {"composite_scores": {}, "prices": {}, "smart_money": {}}
        
        try:
            with open(os.path.join(cache_dir, files[0])) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"composite_scores": {}, "prices": {}, "smart_money": {}}
    
    def distribute_premium(self, coins=None, test_recipient: str = None) -> Dict:
        """
        Distribute the premium brief to all premium subscribers.
        
        Args:
            coins: Optional list of coins to analyze
            test_recipient: If provided, send only to this address (for testing)
        
        Returns:
            Distribution report dict
        """
        print("📊 Generating QuantAlpha Premium brief...")
        report_data = self.generate_report_data(coins)
        
        if not report_data.get("composite_scores"):
            print("⚠️  No composite scores in report data. Brief may be empty.")
        
        # Generate HTML
        html_content = render_premium_email(report_data)
        
        # Generate subject
        subject = EmailSender.generate_subject(report_data)
        print(f"📧 Subject: {subject}")
        
        # Determine recipients
        if test_recipient:
            recipients = [test_recipient]
        else:
            subscribers = self.subscription_mgr.get_active_subscribers(tier="premium")
            recipients = [s["email"] for s in subscribers if s.get("email")]
        
        if not recipients:
            print("ℹ️  No premium subscribers to email yet.")
            if self.dry_run:
                print("   (dry run — would send to 0 recipients)")
            return {
                "status": "no_recipients",
                "recipients": 0,
                "success": 0,
                "failures": 0,
            }
        
        print(f"📬 Sending to {len(recipients)} premium subscriber(s)...")
        
        if self.dry_run:
            # Save preview
            preview_path = os.path.join(PROJECT_ROOT, "reports", f"premium_preview_{datetime.now(timezone.utc).strftime('%Y%m%d')}.html")
            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
            with open(preview_path, "w") as f:
                f.write(html_content)
            print(f"💾 DRY RUN: Preview saved to {preview_path}")
            print(f"   Subject: {subject}")
            print(f"   Would send to: {', '.join(recipients)}")
            return {
                "status": "dry_run",
                "recipients": len(recipients),
                "preview_path": preview_path,
                "subject": subject,
            }
        
        # Send
        success, failures = self.email_sender.send_brief(
            recipients=recipients,
            html_content=html_content,
            subject=subject,
            tier="premium",
        )
        
        return {
            "status": "sent",
            "recipients": len(recipients),
            "success": success,
            "failures": failures,
            "subject": subject,
        }
    
    def distribute_free_discord(self, coins=None) -> str:
        """Generate the free-tier brief for Discord posting (handled by cron)."""
        report_data = self.generate_report_data(coins)
        return format_free_brief(report_data, coins or FREE_COINS)


# ─── CLI ────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="QuantAlpha Email Distributor")
    parser.add_argument("--tier", choices=["premium", "institutional"], default="premium")
    parser.add_argument("--send", action="store_true", help="Actually send emails (default: preview only)")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't send")
    parser.add_argument("--preview", action="store_true", help="Save HTML preview to file")
    parser.add_argument("--test", metavar="EMAIL", help="Send a test email to this address")
    parser.add_argument("--coins", nargs="+", help="Specific coins to analyze")
    
    args = parser.parse_args()
    
    distributor = EmailDistributor(dry_run=not args.send)
    
    if args.test:
        # Send test email
        result = distributor.distribute_premium(coins=args.coins, test_recipient=args.test)
        print(f"\n📊 Result: {json.dumps(result, indent=2)}")
    elif args.preview or args.dry_run:
        # Generate preview
        result = distributor.distribute_premium(coins=args.coins)
        print(f"\n📊 Result: {json.dumps(result, indent=2)}")
    elif args.send:
        # Actually send
        result = distributor.distribute_premium(coins=args.coins)
        print(f"\n📊 Result: {json.dumps(result, indent=2)}")
    else:
        # Default: generate preview
        result = distributor.distribute_premium(coins=args.coins)
        print(f"\n📊 Result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()