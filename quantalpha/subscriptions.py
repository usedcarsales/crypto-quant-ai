"""
QuantAlpha Subscription Manager

Handles:
- Subscriber registration and tracking
- Discord role assignment for premium access
- Subscription lifecycle (create, active, cancel, expire)
- Tier validation for brief delivery

Storage: JSON file (simple — upgrade to DB later if needed)
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

SUBSCRIBER_FILE = "/tmp/quantalpha-subscribers.json"


class SubscriptionManager:
    def __init__(self, subscriber_file: str = SUBSCRIBER_FILE):
        self.subscriber_file = subscriber_file
        self.subscribers = self._load()
    
    def _load(self) -> Dict:
        if os.path.exists(self.subscriber_file):
            with open(self.subscriber_file) as f:
                return json.load(f)
        return {"subscribers": {}, "created_at": datetime.now(timezone.utc).isoformat()}
    
    def _save(self):
        with open(self.subscriber_file, "w") as f:
            json.dump(self.subscribers, f, indent=2, default=str)
    
    def add_subscriber(
        self,
        user_id: str,
        tier: str,
        discord_id: str = None,
        email: str = None,
        stripe_customer_id: str = None,
        stripe_subscription_id: str = None,
    ) -> Dict:
        """Register a new subscriber."""
        if tier not in ("premium", "institutional"):
            raise ValueError(f"Invalid tier: {tier}. Must be 'premium' or 'institutional'")
        
        sub = {
            "user_id": user_id,
            "tier": tier,
            "status": "active",
            "discord_id": discord_id,
            "email": email,
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "cancelled_at": None,
        }
        
        self.subscribers["subscribers"][user_id] = sub
        self._save()
        
        return sub
    
    def get_subscriber(self, user_id: str) -> Optional[Dict]:
        """Get subscriber by user ID."""
        return self.subscribers.get("subscribers", {}).get(user_id)
    
    def cancel_subscription(self, user_id: str) -> Optional[Dict]:
        """Cancel a subscription (remains active until expiry)."""
        sub = self.get_subscriber(user_id)
        if sub:
            sub["status"] = "cancelled"
            sub["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
        return sub
    
    def expire_subscriptions(self) -> List[str]:
        """Mark expired subscriptions. Returns list of expired user IDs."""
        now = datetime.now(timezone.utc)
        expired = []
        
        for uid, sub in self.subscribers.get("subscribers", {}).items():
            if sub["status"] == "active":
                expires = datetime.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
                if now > expires:
                    sub["status"] = "expired"
                    expired.append(uid)
        
        if expired:
            self._save()
        
        return expired
    
    def get_active_subscribers(self, tier: str = None) -> List[Dict]:
        """Get all active subscribers, optionally filtered by tier."""
        active = []
        for sub in self.subscribers.get("subscribers", {}).values():
            if sub["status"] == "active":
                if tier is None or sub["tier"] == tier:
                    active.append(sub)
        return active
    
    def get_tier(self, user_id: str) -> str:
        """Get the tier for a user (returns 'free' if not subscribed)."""
        sub = self.get_subscriber(user_id)
        if sub and sub["status"] == "active":
            return sub["tier"]
        return "free"
    
    def get_subscriber_count(self) -> Dict[str, int]:
        """Get subscriber counts by tier."""
        counts = {"free": 0, "premium": 0, "institutional": 0}
        for sub in self.subscribers.get("subscribers", {}).values():
            if sub["status"] == "active":
                counts[sub["tier"]] = counts.get(sub["tier"], 0) + 1
        return counts
    
    def get_discord_ids_for_tier(self, tier: str) -> List[str]:
        """Get Discord IDs of all active subscribers in a tier."""
        ids = []
        for sub in self.get_active_subscribers(tier):
            if sub.get("discord_id"):
                ids.append(sub["discord_id"])
        return ids


# ─── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="QuantAlpha Subscription Manager")
    parser.add_argument("--add", metavar="USER_ID", help="Add a subscriber")
    parser.add_argument("--tier", choices=["premium", "institutional"], default="premium")
    parser.add_argument("--discord-id", help="Discord user ID")
    parser.add_argument("--email", help="Email address")
    parser.add_argument("--cancel", metavar="USER_ID", help="Cancel a subscription")
    parser.add_argument("--list", action="store_true", help="List all subscribers")
    parser.add_argument("--stats", action="store_true", help="Show subscriber stats")
    
    args = parser.parse_args()
    mgr = SubscriptionManager()
    
    if args.add:
        sub = mgr.add_subscriber(args.add, args.tier, args.discord_id, args.email)
        print(f"✅ Added {args.add} as {args.tier}")
        print(json.dumps(sub, indent=2))
    elif args.cancel:
        mgr.cancel_subscription(args.cancel)
        print(f"✅ Cancelled subscription for {args.cancel}")
    elif args.list:
        for sub in mgr.get_active_subscribers():
            print(f"  {sub['user_id']}: {sub['tier']} (expires {sub['expires_at'][:10]})")
    elif args.stats:
        counts = mgr.get_subscriber_count()
        print(f"Subscribers: {counts['premium']} premium, {counts['institutional']} institutional")
        print(f"Potential MRR: ${counts['premium'] * 29 + counts['institutional'] * 199}")
    else:
        parser.print_help()
