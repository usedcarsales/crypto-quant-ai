#!/bin/bash
# QuantAlpha — Create Stripe Products
# Requires: STRIPE_SECRET_KEY env var
# Usage: STRIPE_SECRET_KEY=sk_live_... bash create_stripe_products.sh

set -e

if [ -z "$STRIPE_SECRET_KEY" ]; then
    echo "❌ STRIPE_SECRET_KEY not set. Usage: STRIPE_SECRET_KEY=sk_live_... bash $0"
    exit 1
fi

BASE="https://api.stripe.com/v1"
AUTH="-u $STRIPE_SECRET_KEY:"

echo "🚀 Creating QuantAlpha Premium product..."
PREMIUM=$(curl -s $BASE/products $AUTH -d name="QuantAlpha Premium" \
  -d description="Full 20-coin signal matrix, whale alerts, RSI pullback notifications, trade journal access, email delivery" \
  -d "metadata[tier]=premium" \
  -d "metadata[product]=quantalpha")
PREMIUM_ID=$(echo "$PREMIUM" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "✅ Product ID: $PREMIUM_ID"

echo "💰 Creating Premium price ($29/mo)..."
PREMIUM_PRICE=$(curl -s $BASE/prices $AUTH \
  -d "product]=$PREMIUM_ID" \
  -d nickname="QuantAlpha Premium Monthly" \
  -d unit_amount=2900 \
  -d currency=usd \
  -d "recurring[interval]=month" \
  -d "recurring[interval_count]=1")
PREMIUM_PRICE_ID=$(echo "$PREMIUM_PRICE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "✅ Price ID: $PREMIUM_PRICE_ID"

echo "🚀 Creating QuantAlpha Institutional product..."
INST=$(curl -s $BASE/products $AUTH -d name="QuantAlpha Institutional" \
  -d description="Everything in Premium plus custom watchlist, API access, historical archive, weekly strategy review, priority support" \
  -d "metadata[tier]=institutional" \
  -d "metadata[product]=quantalpha")
INST_ID=$(echo "$INST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "✅ Product ID: $INST_ID"

echo "💰 Creating Institutional price ($199/mo)..."
INST_PRICE=$(curl -s $BASE/prices $AUTH \
  -d "product]=$INST_ID" \
  -d nickname="QuantAlpha Institutional Monthly" \
  -d unit_amount=19900 \
  -d currency=usd \
  -d "recurring[interval]=month" \
  -d "recurring[interval_count]=1")
INST_PRICE_ID=$(echo "$INST_PRICE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "✅ Price ID: $INST_PRICE_ID"

echo ""
echo "📊 QUANTALPHA STRIBE PRODUCT IDS — ADD TO TOOLS.MD:"
echo "  Premium $29/mo → price_XXX: $PREMIUM_PRICE_ID"
echo "  Institutional $199/mo → price_XXX: $INST_PRICE_ID"
