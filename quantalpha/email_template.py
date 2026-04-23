"""
QuantAlpha Email Template Renderer

Renders the premium HTML email from template + live brief data.
Used by email_distributor.py — not called directly.

Usage:
    from email_template import render_premium_email
    html = render_premium_email(report_data)
"""

import os
from datetime import datetime, timezone
from typing import Dict

# ─── Template Path ────────────────────────────────────────────────────────────

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "templates",
    "premium_email.html",
)


# ─── Renderer ─────────────────────────────────────────────────────────────────

def render_premium_email(report_data: Dict) -> str:
    """
    Render the premium email HTML template with live data.
    Replaces all {{PLACEHOLDER}} blocks with formatted content.
    """
    with open(TEMPLATE_PATH) as f:
        html = f.read()

    now = datetime.now(timezone.utc)
    html = html.replace("{{DATE}}", now.strftime("%A, %B %d, %Y"))

    # Render each content block
    html = html.replace("{{SIGNAL_MATRIX}}", _render_signal_matrix(report_data))
    html = html.replace("{{WHALE_ALERTS}}", _render_whale_alerts(report_data))
    html = html.replace("{{RSI_ALERTS}}", _render_rsi_alerts(report_data))
    html = html.replace("{{FEATURED_OPPS}}", _render_opportunities(report_data))
    html = html.replace("{{TRADE_JOURNAL}}", _render_trade_journal(report_data))

    return html


# ─── Section Renderers ────────────────────────────────────────────────────────

def _render_signal_matrix(report_data: Dict) -> str:
    """Signal matrix as an HTML table with color-coded signals."""
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
            f"<tr>"
            f"<td><strong>{symbol}</strong></td>"
            f"<td class=\"{signal_class}\">{signal_icon} {signal}</td>"
            f"<td>{score:.0f}/100</td>"
            f"<td>{confidence}</td>"
            f"<td>{rsi:.0f}</td>"
            f"<td>{trend}</td>"
            f"</tr>"
        )

    if not rows:
        return "<p><em>No signal data available today.</em></p>"

    return (
        "<table>"
        "<tr><th>Coin</th><th>Signal</th><th>Score</th><th>Confidence</th><th>RSI</th><th>Trend</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _render_whale_alerts(report_data: Dict) -> str:
    """Whale alerts as styled alert boxes."""
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

        icon = "🟢" if "buy" in str(direction).lower() else "🔴"
        items.append(
            f"<div class=\"whale-box\">{icon} <strong>{wallet}...</strong> "
            f"{direction} ${amount:,.0f} {coin}</div>"
        )

    return "".join(items) if items else '<div class="whale-box"><em>No significant whale activity.</em></div>'


def _render_rsi_alerts(report_data: Dict) -> str:
    """RSI pullback alerts with overbought/oversold signals."""
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
                f"<div class=\"alert-box\">🟢 <strong>{symbol}</strong>: "
                f"RSI {rsi:.0f} — OVERSOLD, potential bounce setup</div>"
            )
        elif rsi > 70:
            alerts.append(
                f"<div class=\"alert-box\">🔴 <strong>{symbol}</strong>: "
                f"RSI {rsi:.0f} — OVERBOUGHT, potential pullback</div>"
            )

    if not alerts:
        return "<p><em>No RSI pullback alerts triggered today.</em></p>"

    return "".join(alerts)


def _render_opportunities(report_data: Dict) -> str:
    """Top BUY-signaled opportunities sorted by score."""
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
                f"<div class=\"alert-box\">⭐ <strong>{symbol}</strong>: "
                f"{signal} (Score {score:.0f}/100) — {reason_str}</div>"
            )

    if not opps:
        return "<p><em>No high-conviction opportunities identified today.</em></p>"

    # Sort by score descending, limit to 3
    def get_score(opp):
        try:
            return float(opp.split("Score ")[1].split("/")[0])
        except Exception:
            return 0

    return "".join(sorted(opps, key=get_score, reverse=True)[:3])


def _render_trade_journal(report_data: Dict) -> str:
    """Paper trading journal from portfolio.json."""
    import json as _json

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    portfolio_path = os.path.join(project_root, "data", "portfolio.json")

    if os.path.exists(portfolio_path):
        try:
            with open(portfolio_path) as f:
                portfolio = _json.load(f)

            trades = portfolio.get("trades", portfolio.get("closed_trades", []))
            balance = portfolio.get("balance", portfolio.get("cash", 10000))
            total_value = portfolio.get("total_value", balance)

            if trades:
                trade_rows = []
                for t in trades[-5:]:
                    side = t.get("side", "?").upper()
                    symbol = t.get("symbol", "?")
                    pnl = t.get("pnl", t.get("realized_pnl", 0))
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                    pnl_class = "buy" if pnl >= 0 else "sell"
                    trade_rows.append(
                        f"<tr><td>{side}</td><td><strong>{symbol}</strong></td>"
                        f"<td class=\"{pnl_class}\">{pnl_str}</td></tr>"
                    )

                return (
                    f"<p>Portfolio Value: <strong>${total_value:,.2f}</strong> | "
                    f"Cash: ${balance:,.2f}</p>"
                    "<table><tr><th>Side</th><th>Asset</th><th>P&L</th></tr>"
                    + "".join(trade_rows)
                    + "</table>"
                )
        except (Exception):
            pass

    return (
        "<p><em>Trade journal will populate after 7 days of tracking. "
        "Paper trading is active.</em></p>"
    )