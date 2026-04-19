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

from quantalpha.formatter import format_free_brief, format_premium_brief, format_institutional_feed, FREE_COINS
from quantalpha.subscriptions import SubscriptionManager
from quantalpha.email_sender import EmailSender


# ─── Template Renderer ────────────────────────────────────────────────────────

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "premium_email.html")


def render_premium_email(report_data: Dict) -> str:
    """
    Render the premium email HTML template with live data.
    Replaces template placeholders with actual content.
    """
    with open(TEMPLATE_PATH) as f:
        template = f.read()
    
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %d, %Y")
    
    # ── Signal Matrix ──────────────────────────────────────────────────────
    signal_html = render_signal_matrix(report_data)
    
    # ── Whale Alerts ───────────────────────────────────────────────────────
    whale_html = render_whale_alerts(report_data)
    
    # ── RSI Alerts ─────────────────────────────────────────────────────────
    rsi_html = render_rsi_alerts(report_data)
    
    # ── Featured Opportunities ──────────────────────────────────────────────
    opps_html = render_opportunities(report_data)
    
    # ── Trade Journal ──────────────────────────────────────────────────────
    journal_html = render_trade_journal(report_data)
    
    # ── Replace placeholders ───────────────────────────────────────────────
    html = template.replace("{{DATE}}", date_str)
    html = html.replace("{{SIGNAL_MATRIX}}", signal_html)
    html = html.replace("{{WHALE_ALERTS}}", whale_html)
    html = html.replace("{{RSI_ALERTS}}", rsi_html)
    html = html.replace("{{FEATURED_OPPS}}", opps_html)
    html = html.replace("{{TRADE_JOURNAL}}", journal_html)
    
    return html


def render_signal_matrix(report_data: Dict) -> str:
    """Render the signal matrix as an HTML table."""
    scores = report_data.get("composite_scores", {})
    if not scores:
        return "<p><em>No signal data available today.</em></p>"
    
    rows = []
    for symbol, sd in scores.items():
        if not isinstance(sd, dict):
            continue
        
        score = sd.get("composite_score", 0)
        signal = str(sd.get("signal", "N/A")).upper()
        confidence = sd.get("confidence", "N/A")
        rsi = sd.get("rsi", 0)
        ta = sd.get("ta_data", {})
        trend = ta.get("trend", "N/A") if isinstance(ta, dict) else "N/A"
        
        # Color coding
        if "BUY" in signal and "STRONG" in signal:
            signal_class = "buy"
            signal_icon = "🟢🟢"
        elif "BUY" in signal:
            signal_class = "buy"
            signal_icon = "🟢"
        elif "SELL" in signal and "STRONG" in signal:
            signal_class = "sell"
            signal_icon = "🔴🔴"
        elif "SELL" in signal:
            signal_class = "sell"
            signal_icon = "🔴"
        else:
            signal_class = "neutral"
            signal_icon = "⚪"
        
        rows.append(
            f'<tr>'
            f'<td><strong>{symbol}</strong></td>'
            f'<td class="{signal_class}">{signal_icon} {signal}</td>'
            f'<td>{score:.0f}/100</td>'
            f'<td>{confidence}</td>'
            f'<td>{rsi:.0f}</td>'
            f'<td>{trend}</td>'
            f'</tr>'
        )
    
    if not rows:
        return "<p><em>No signal data available today.</em></p>"
    
    return (
        '<table><tr><th>Coin</th><th>Signal</th><th>Score</th><th>Confidence</th><th>RSI</th><th>Trend</th></tr>'
        + "".join(rows)
        + '</table>'
    )


def render_whale_alerts(report_data: Dict) -> str:
    """Render whale alerts as styled boxes."""
    smart_money = report_data.get("smart_money", {})
    flows = smart_money.get("flows", smart_money.get("whale_flows", []))
    
    if not flows or not isinstance(flows, list):
        return '<div class="whale-box"><em>No significant whale activity detected today.</em></div>'
    
    items = []
    for flow in flows[:5]:
        if not isinstance(flow, dict):
            continue
        wallet = flow.get("wallet", flow.get("label", "?"))[:20]
        direction = flow.get("direction", flow.get("action", "?"))
        amount = flow.get("amount_usd", flow.get("value", 0))
        coin = flow.get("coin", flow.get("token", "?"))
        
        if "buy" in str(direction).lower():
            icon = "🟢"
        else:
            icon = "🔴"
        
        items.append(f'<div class="whale-box">{icon} <strong>{wallet}...</strong> {direction} ${amount:,.0f} {coin}</div>')
    
    return "".join(items) if items else '<div class="whale-box"><em>No significant whale activity.</em></div>'


def render_rsi_alerts(report_data: Dict) -> str:
    """Render RSI pullback alerts."""
    scores = report_data.get("composite_scores", {})
    alerts = []
    
    for symbol, sd in scores.items():
        if not isinstance(sd, dict):
            continue
        rsi = sd.get("rsi", 50)
        try:
            rsi = float(rsi)
        except (TypeError, ValueError):
            continue
        
        if rsi < 30:
            alerts.append(
                f'<div class="alert-box">🟢 <strong>{symbol}</strong>: RSI {rsi:.0f} — OVERSOLD, potential bounce setup</div>'
            )
        elif rsi > 70:
            alerts.append(
                f'<div class="alert-box">🔴 <strong>{symbol}</strong>: RSI {rsi:.0f} — OVERBOUGHT, potential pullback</div>'
            )
    
    if not alerts:
        return "<p><em>No RSI pullback alerts triggered today.</em></p>"
    
    return "".join(alerts)


def render_opportunities(report_data: Dict) -> str:
    """Render featured opportunities."""
    scores = report_data.get("composite_scores", {})
    opps = []
    
    for symbol, sd in scores.items():
        if not isinstance(sd, dict):
            continue
        score = sd.get("composite_score", 0)
        signal = str(sd.get("signal", "")).upper()
        
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        
        if "BUY" in signal and score > 60:
            reasons = []
            if sd.get("defi_score", 0) > 70:
                reasons.append("strong DeFi metrics")
            if sd.get("social_score", 0) > 70:
                reasons.append("positive sentiment")
            if sd.get("smart_money_score", 0) > 60:
                reasons.append("smart money inflow")
            reason_str = ", ".join(reasons) if reasons else "composite signal alignment"
            
            opps.append(
                f'<div class="alert-box">⭐ <strong>{symbol}</strong>: {signal} (Score {score:.0f}/100) — {reason_str}</div>'
            )
    
    if not opps:
        return "<p><em>No high-conviction opportunities identified today.</em></p>"
    
    return "".join(sorted(opps, key=lambda x: float(x.split("Score ")[1].split("/")[0]), reverse=True)[:3])


def render_trade_journal(report_data: Dict) -> str:
    """Render paper trading journal."""
    # Load paper trading data if available
    portfolio_path = os.path.join(PROJECT_ROOT, "data", "portfolio.json")
    
    if os.path.exists(portfolio_path):
        try:
            with open(portfolio_path) as f:
                portfolio = json.load(f)
            
            trades = portfolio.get("trades", portfolio.get("closed_trades", []))
            balance = portfolio.get("balance", portfolio.get("cash", 10000))
            total_value = portfolio.get("total_value", balance)
            
            if trades:
                trade_rows = []
                for t in trades[-5:]:  # Last 5 trades
                    side = t.get("side", "?").upper()
                    symbol = t.get("symbol", "?")
                    pnl = t.get("pnl", t.get("realized_pnl", 0))
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                    pnl_class = "buy" if pnl >= 0 else "sell"
                    trade_rows.append(
                        f'<tr><td>{side}</td><td><strong>{symbol}</strong></td><td class="{pnl_class}">{pnl_str}</td></tr>'
                    )
                
                return (
                    f'<p>Portfolio Value: <strong>${total_value:,.2f}</strong> | Cash: ${balance:,.2f}</p>'
                    '<table><tr><th>Side</th><th>Asset</th><th>P&L</th></tr>'
                    + "".join(trade_rows)
                    + '</table>'
                )
        except (json.JSONDecodeError, IOError):
            pass
    
    return "<p><em>Trade journal will populate after 7 days of tracking. Paper trading is active.</em></p>"


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