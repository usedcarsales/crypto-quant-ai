"""
QuantAlpha Discord Posting Module

Posts the daily brief to Discord via:
1. OpenClaw message tool (preferred — no webhook needed)
2. Discord webhook fallback (direct HTTP POST)

Supports free-tier (top 3 coins) with upgrade CTA and disclaimer.
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

from quantalpha.discord_formatter import format_discord_embed, format_discord_message, FREE_COINS

# ─── Configuration ────────────────────────────────────────────────────────────

QUANTALPHA_CHANNEL_ID = "1494919968595120158"
DISCLAIMER = "⚠️ Not financial advice. Signals for educational purposes only. Always DYOR."
CTA_TEXT = "🔒 **Want the full picture?** Premium: 20-coin matrix, whale alerts, RSI notifications — $29/mo\n👉 [Subscribe](https://particulatellc.com/quantalpha)"


# ─── Posting Functions ────────────────────────────────────────────────────────

def post_brief_to_discord(report_data: Dict, channel_id: str = QUANTALPHA_CHANNEL_ID,
                          coins: List[str] = None, dry_run: bool = False) -> Dict:
    """
    Post the QuantAlpha daily brief to Discord.
    
    Uses OpenClaw message tool for posting (runs via subprocess).
    Falls back to webhook if OpenClaw not available.
    
    Args:
        report_data: The full report data dict from generate_brief()
        channel_id: Discord channel ID to post to
        coins: List of coin IDs (default: FREE_COINS for free tier)
        dry_run: If True, simulate posting without actually sending
    
    Returns:
        Dict with status, channel_id, and message_id (or simulation info)
    """
    if coins is None:
        coins = FREE_COINS
    
    # Build the Discord embed
    embed = format_discord_embed(report_data, coins)
    
    # Build the text message (fallback)
    text_message = format_discord_message(report_data, coins)
    
    if dry_run:
        return {
            "status": "simulated",
            "channel_id": channel_id,
            "embed": embed,
            "message_preview": text_message[:500] + "..." if len(text_message) > 500 else text_message,
            "dry_run": True,
            "note": "Dry-run mode — no message posted to Discord",
        }
    
    # Try OpenClaw message tool (subprocess call)
    result = _post_via_openclaw(embed, text_message, channel_id)
    if result.get("ok"):
        return {
            "status": "posted",
            "channel_id": channel_id,
            "message_id": result.get("message_id"),
            "method": "openclaw_message",
        }
    
    # Fallback: webhook
    webhook_result = _post_via_webhook(embed, text_message, channel_id)
    if webhook_result.get("ok"):
        return {
            "status": "posted",
            "channel_id": channel_id,
            "message_id": webhook_result.get("message_id"),
            "method": "webhook",
        }
    
    return {
        "status": "failed",
        "channel_id": channel_id,
        "error": result.get("error", "All posting methods failed"),
        "attempted_methods": ["openclaw_message", "webhook"],
    }


def _post_via_openclaw(embed: Dict, text_fallback: str, channel_id: str) -> Dict:
    """
    Post via OpenClaw CLI message tool.
    Uses subprocess to call the OpenClaw API.
    """
    import subprocess
    
    # Use the text message as the payload — Discord embeds via OpenClaw
    # are posted using the message tool's embed support
    try:
        # Build the message as a simple text post with embed data
        # OpenClaw message tool handles Discord posting
        message_text = text_fallback
        
        # Try using openclaw CLI to send
        cmd = [
            "openclaw", "message", "send",
            "--channel", "discord",
            "--target", channel_id,
            "--message", message_text,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode == 0:
            return {"ok": True, "message_id": "openclaw_sent"}
        else:
            return {"ok": False, "error": f"OpenClaw CLI failed: {result.stderr[:200]}"}
    
    except FileNotFoundError:
        return {"ok": False, "error": "openclaw CLI not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "OpenClaw CLI timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _post_via_webhook(embed: Dict, text_fallback: str, channel_id: str) -> Dict:
    """
    Post via Discord webhook.
    Looks for QUANTALPHA_WEBHOOK_URL environment variable.
    """
    import requests
    
    webhook_url = os.environ.get("QUANTALPHA_WEBHOOK_URL", "")
    if not webhook_url:
        return {"ok": False, "error": "QUANTALPHA_WEBHOOK_URL not set"}
    
    payload = {
        "embeds": [embed],
        "username": "QuantAlpha",
        "avatar_url": "https://particulatellc.com/quantalpha/icon.png",
    }
    
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            return {"ok": True, "message_id": "webhook_sent"}
        else:
            return {"ok": False, "error": f"Webhook returned {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Python API for Direct Embed ─────────────────────────────────────────────

def post_embed_directly(embed: Dict, channel_id: str = QUANTALPHA_CHANNEL_ID) -> Dict:
    """
    Post a pre-built Discord embed directly.
    Use this when called from within OpenClaw agent context
    (has direct access to message tool via the runtime).
    
    This function returns the embed payload — the calling agent
    should use its message tool to actually post it.
    """
    return {
        "channel_id": channel_id,
        "embed": embed,
        "disclaimer": DISCLAIMER,
        "cta": CTA_TEXT,
        "ready_to_post": True,
    }


# ─── Free-Tier Formatting ────────────────────────────────────────────────────

def format_free_tier_post(report_data: Dict, coins: List[str] = None) -> str:
    """
    Format a complete free-tier Discord post.
    Includes: brief content + disclaimer + upgrade CTA.
    """
    if coins is None:
        coins = FREE_COINS
    
    # Use the formatter module
    from quantalpha.formatter import format_free_brief
    brief = format_free_brief(report_data, coins)
    
    # Ensure disclaimer and CTA are present
    if DISCLAIMER not in brief:
        brief += f"\n\n{DISCLAIMER}"
    if "Subscribe" not in brief and "Upgrade" not in brief:
        brief += f"\n\n{CTA_TEXT}"
    
    return brief


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Post QuantAlpha brief to Discord")
    parser.add_argument("--channel", default=QUANTALPHA_CHANNEL_ID, help="Discord channel ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate posting without sending")
    parser.add_argument("--coins", nargs="+", default=FREE_COINS, help="Coins to include (free tier: max 3)")
    parser.add_argument("--input", help="JSON file with report data (from generate_brief --format json)")
    args = parser.parse_args()
    
    # Load report data
    if args.input:
        with open(args.input) as f:
            report_data = json.load(f)
    else:
        # Generate a brief first
        from skills.brief_engine.daily_brief import generate_brief
        print("📊 Generating brief...")
        brief_json = generate_brief(format="json", coins=args.coins, dry_run=args.dry_run)
        report_data = json.loads(brief_json)
    
    print(f"🚀 Posting QuantAlpha brief to channel {args.channel}...")
    result = post_brief_to_discord(
        report_data=report_data,
        channel_id=args.channel,
        coins=args.coins,
        dry_run=args.dry_run,
    )
    
    if result["status"] == "posted":
        print(f"✅ Posted! Message ID: {result.get('message_id')}")
    elif result["status"] == "simulated":
        print(f"📦 Dry-run — post simulated (not sent)")
        print(f"Preview:\n{result.get('message_preview', '')}")
    else:
        print(f"❌ Posting failed: {result.get('error')}")
    
    print(json.dumps(result, indent=2, default=str))