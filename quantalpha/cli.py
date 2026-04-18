"""
QuantAlpha CLI — Generate and distribute tier-specific market briefs.

Usage:
    python -m quantalpha.cli --tier free [--post-discord]
    python -m quantalpha.cli --tier premium [--output file.html]
    python -m quantalpha.cli --tier institutional [--output file.json]
"""

import argparse
import json
import os
import sys

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from quantalpha.formatter import (
    format_free_brief,
    format_premium_brief,
    format_institutional_feed,
    FREE_COINS,
)


def generate_report_data(coins=None):
    """Generate full report data using the daily brief engine."""
    from skills.brief_engine.daily_brief import generate_brief
    
    # Get JSON format for programmatic use
    json_brief = generate_brief(format="json", coins=coins)
    try:
        return json.loads(json_brief)
    except (json.JSONDecodeError, TypeError):
        # Fallback: generate markdown and parse what we can
        return {"composite_scores": {}, "prices": {}, "smart_money": {}}


def main():
    parser = argparse.ArgumentParser(description="QuantAlpha Market Intelligence CLI")
    parser.add_argument(
        "--tier",
        choices=["free", "premium", "institutional"],
        default="free",
        help="Output tier (default: free)",
    )
    parser.add_argument(
        "--coins",
        nargs="+",
        default=None,
        help="Specific coins to analyze (default: tier-dependent)",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use cached data only (no live API calls)",
    )
    parser.add_argument(
        "--post-discord",
        action="store_true",
        help="Post to Discord after generation (requires channel config)",
    )
    
    args = parser.parse_args()
    
    # Determine coins based on tier
    coins = args.coins
    if coins is None and args.tier == "free":
        coins = FREE_COINS
    
    print(f"🚀 Generating QuantAlpha {args.tier} brief...")
    
    try:
        report_data = generate_report_data(coins)
    except Exception as e:
        print(f"❌ Error generating report data: {e}")
        # Generate minimal fallback
        report_data = {
            "composite_scores": {},
            "prices": {},
            "smart_money": {},
            "error": str(e),
        }
    
    # Format based on tier
    if args.tier == "free":
        output = format_free_brief(report_data, coins)
    elif args.tier == "premium":
        output = format_premium_brief(report_data, coins)
    elif args.tier == "institutional":
        feed = format_institutional_feed(report_data, coins)
        output = json.dumps(feed, indent=2, default=str)
    
    # Output
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"✅ Brief saved to {args.output}")
    else:
        print(output)
    
    # Discord posting would be handled by OpenClaw cron
    if args.post_discord:
        print("\n📡 Discord posting is handled by OpenClaw cron — output is ready to post")
    
    print(f"\n✅ QuantAlpha {args.tier} brief generated")


if __name__ == "__main__":
    main()
