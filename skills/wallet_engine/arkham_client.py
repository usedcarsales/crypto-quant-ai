"""
Arkham Intelligence API Client
Phase 1.1, Task 1.4 — Named Entity Wallet Tracking

Provides labeled entity intelligence for any blockchain address.
Upgrades wallet tracking from "anonymous addresses" to named entities
(e.g., "Galaxy Digital", "Jump Trading", "Binance cold wallet").

API Docs: https://intel.arkm.com/api/docs
Base URL: https://api.arkm.com
Auth: API-Key header
"""

import os
import requests
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

# ─── Configuration ────────────────────────────────────────────────────────────

ARKHAM_BASE = "https://api.arkm.com"
ARKHAM_KEY  = os.environ.get("ARKHAM_API_KEY", "")

# Rate limiting — Arkham standard: ~10 req/sec, transfers: 1 req/sec
_LAST_CALL = 0
_MIN_INTERVAL = 0.15  # 150ms between calls
_TRANSFERS_INTERVAL = 1.1  # 1.1s for transfer endpoint


def _get_key() -> str:
    """Resolve API key from env, .env file, or return empty."""
    if ARKHAM_KEY:
        return ARKHAM_KEY
    # Try loading from .env file in project root
    try:
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ARKHAM_API_KEY="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
    except Exception:
        pass
    return ""


def _headers() -> dict:
    """Build auth headers for Arkham API."""
    key = _get_key()
    return {
        "API-Key": key,
        "Accept": "application/json",
    }


def _throttle(is_transfers: bool = False):
    """Rate limiter — stricter for transfers endpoint."""
    global _LAST_CALL
    interval = _TRANSFERS_INTERVAL if is_transfers else _MIN_INTERVAL
    elapsed = time.time() - _LAST_CALL
    if elapsed < interval:
        time.sleep(interval - elapsed)
    _LAST_CALL = time.time()


def _get(endpoint: str, params: dict = None, timeout: int = 20, is_transfers: bool = False) -> dict:
    """Generic GET request to Arkham API."""
    _throttle(is_transfers=is_transfers)
    url = f"{ARKHAM_BASE}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return {"status": "ok", "data": data, "code": 200}
        elif resp.status_code == 401:
            return {"status": "error", "code": 401, "message": "Unauthorized — check ARKHAM_API_KEY"}
        elif resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "2")
            return {"status": "error", "code": 429, "message": f"Rate limited — retry after {retry}s"}
        else:
            return {
                "status": "error",
                "code": resp.status_code,
                "message": resp.text[:500] if resp.text else f"HTTP {resp.status_code}",
            }
    except requests.exceptions.Timeout:
        return {"status": "error", "code": 0, "message": "Request timed out"}
    except Exception as e:
        return {"status": "error", "code": 0, "message": str(e)}


# ─── Search ──────────────────────────────────────────────────────────────────

def search_entities(query: str, entity_limit: int = 10, token_limit: int = 10) -> dict:
    """
    Full-text search across addresses, entities, and tokens.
    
    Args:
        query: Search term (e.g., "Galaxy Digital", "Binance", "0x28C6...")
        entity_limit: Max entity results
        token_limit: Max token results
    
    Returns:
        Matching entities, addresses, tokens, ENS names, etc.
    """
    filter_limits = {
        "arkhamAddresses": 5,
        "arkhamEntities": entity_limit,
        "ens": 3,
        "opensea": 1,
        "services": 3,
        "tags": 5,
        "tokens": token_limit,
        "twitter": 1,
        "types": 1,
        "userAddresses": 1,
        "userEntities": 1,
    }
    import json
    result = _get(
        "/intelligence/search",
        params={"query": query, "filterLimits": json.dumps(filter_limits)},
    )
    if result["status"] != "ok":
        return {"query": query, "results": {}, "error": result.get("message", "unknown error")}
    
    raw = result["data"]
    
    # Parse search result categories
    entities = []
    for ent in raw.get("arkhamEntities", []):
        entities.append({
            "entity_id":  ent.get("id", ""),
            "name":       ent.get("name", ""),
            "type":       ent.get("type", ""),
            "description": ent.get("description", ""),
            "logo":       ent.get("logo", ""),
        })
    
    addresses = []
    for addr in raw.get("arkhamAddresses", []):
        addresses.append({
            "address": addr.get("address", ""),
            "entity":  addr.get("arkhamEntity", {}).get("name", "") if isinstance(addr.get("arkhamEntity"), dict) else "",
            "label":   addr.get("arkhamLabel", {}).get("name", "") if isinstance(addr.get("arkhamLabel"), dict) else "",
            "chain":   addr.get("chain", ""),
        })
    
    tokens = []
    for tok in raw.get("tokens", []):
        tokens.append({
            "id":     tok.get("id", ""),
            "name":   tok.get("name", ""),
            "symbol": tok.get("symbol", ""),
            "chain":  tok.get("chain", ""),
        })
    
    return {
        "query":     query,
        "entities":  entities,
        "addresses": addresses,
        "tokens":    tokens,
        "raw":       raw,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Address Intelligence ────────────────────────────────────────────────────

def get_address_intelligence(address: str, chain: str = None) -> dict:
    """
    Get intelligence about a blockchain address.
    
    Returns entity associations, labels, contract status, and more.
    Auto-detects chain if not specified.
    
    Args:
        address: Blockchain address (ETH, BTC, SOL, etc.)
        chain: Optional chain filter (e.g., "ethereum", "bitcoin")
    
    Returns:
        Entity name, label, type, contract status, predicted entity, etc.
    """
    params = {}
    if chain:
        params["chain"] = chain
    
    result = _get(f"/intelligence/address/{address}", params=params)
    if result["status"] != "ok":
        return {"address": address, "error": result.get("message", "unknown error")}
    
    raw = result["data"]
    
    # Extract entity info from nested structures
    arkham_entity = raw.get("arkhamEntity", {}) or {}
    arkham_label = raw.get("arkhamLabel", {}) or {}
    predicted_entity = raw.get("predictedEntity", {}) or {}
    user_entity = raw.get("userEntity", {}) or {}
    user_label = raw.get("userLabel", {}) or {}
    
    # Primary entity resolution (priority: arkham > predicted > user)
    primary_entity_name = (
        arkham_entity.get("name", "") or
        predicted_entity.get("name", "") or
        user_entity.get("name", "") or
        ""
    )
    primary_entity_id = (
        arkham_entity.get("id", "") or
        predicted_entity.get("id", "") or
        user_entity.get("id", "") or
        ""
    )
    
    # Label info
    label_name = arkham_label.get("name", "") or user_label.get("name", "") or ""
    label_type = arkham_label.get("type", "") or user_label.get("type", "") or ""
    
    # Entity type from tags
    entity_type = "unknown"
    tags = arkham_entity.get("tags", []) or []
    if tags and isinstance(tags, list) and len(tags) > 0:
        first_tag = tags[0]
        if isinstance(first_tag, dict):
            entity_type = first_tag.get("name", first_tag.get("id", "unknown"))
        elif isinstance(first_tag, str):
            entity_type = first_tag
    
    return {
        "address":            address,
        "chain":              raw.get("chain", ""),
        "is_contract":        raw.get("contract", False),
        "is_service":         raw.get("service", False),
        "is_shielded":        raw.get("isShielded", False),
        "is_user_address":    raw.get("isUserAddress", False),
        "primary_entity":     primary_entity_name,
        "primary_entity_id":  primary_entity_id,
        "label":              label_name,
        "label_type":         label_type,
        "entity_type":        entity_type,
        "deposit_service":    raw.get("depositServiceID", ""),
        "arkham_entity":      arkham_entity,
        "arkham_label":       arkham_label,
        "predicted_entity":   predicted_entity,
        "tags":               tags,
        "is_labeled":         bool(primary_entity_name or label_name),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }


# ─── Entity Intelligence ─────────────────────────────────────────────────────

def get_entity_intelligence(entity: str) -> dict:
    """
    Get intelligence about an entity (exchange, fund, protocol, etc.).
    
    Returns associated tags, social links, and metadata.
    
    Args:
        entity: Entity ID (e.g., "binance", "galaxy-digital")
    """
    result = _get(f"/intelligence/entity/{entity}")
    if result["status"] != "ok":
        return {"entity": entity, "error": result.get("message", "unknown error")}
    
    raw = result["data"]
    
    tags = []
    for tag in raw.get("tags", []):
        if isinstance(tag, dict):
            tags.append({
                "id":   tag.get("id", ""),
                "name": tag.get("name", ""),
                "type": tag.get("type", ""),
            })
        elif isinstance(tag, str):
            tags.append({"name": tag})
    
    socials = raw.get("socials", {}) or {}
    
    return {
        "entity_id":    raw.get("id", entity),
        "name":         raw.get("name", ""),
        "description":  raw.get("description", ""),
        "type":         raw.get("type", ""),
        "logo":         raw.get("logo", ""),
        "tags":         tags,
        "socials":      socials,
        "website":      raw.get("website", ""),
        "raw":          raw,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }


# ─── Transfer Tracking ───────────────────────────────────────────────────────

def get_transfers(
    base: str = None,
    from_entity: str = None,
    to_entity: str = None,
    counterparties: str = None,
    tokens: str = None,
    chains: str = None,
    flow: str = None,
    time_last: str = None,
    time_gte: str = None,
    time_lte: str = None,
    usd_gte: float = None,
    usd_lte: float = None,
    sort_key: str = "time",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Get transfers between entities/addresses with rich filtering.
    
    Note: This endpoint has a 1 req/sec rate limit.
    
    Args:
        base: Entity or address to track (e.g., "binance")
        from_entity: From filter (address, entity, or "deposit:binance")
        to_entity: To filter
        counterparties: Strict counterparty filter
        tokens: Token filter (e.g., "ethereum", "usd-coin")
        chains: Chain filter (e.g., "ethereum,bsc")
        flow: Direction ("in", "out", "self", "all")
        time_last: Duration filter (e.g., "24h", "7d")
        time_gte: Start time ISO
        time_lte: End time ISO
        usd_gte: Min USD value filter
        usd_lte: Max USD value filter
        sort_key: Sort field ("time", "value", "usd")
        sort_dir: Sort direction ("asc", "desc")
        limit: Max results (default 50)
        offset: Pagination offset
    
    Returns:
        List of enriched transfers with entity labels and USD values.
    """
    params = {}
    if base:
        params["base"] = base
    if from_entity:
        params["from"] = from_entity
    if to_entity:
        params["to"] = to_entity
    if counterparties:
        params["counterparties"] = counterparties
    if tokens:
        params["tokens"] = tokens
    if chains:
        params["chains"] = chains
    if flow:
        params["flow"] = flow
    if time_last:
        params["timeLast"] = time_last
    if time_gte:
        params["timeGte"] = time_gte
    if time_lte:
        params["timeLte"] = time_lte
    if usd_gte is not None:
        params["usdGte"] = str(usd_gte)
    if usd_lte is not None:
        params["usdLte"] = str(usd_lte)
    if sort_key:
        params["sortKey"] = sort_key
    if sort_dir:
        params["sortDir"] = sort_dir
    params["limit"] = limit
    params["offset"] = offset
    
    result = _get("/transfers", params=params, is_transfers=True)
    if result["status"] != "ok":
        return {"transfers": [], "error": result.get("message", "unknown error")}
    
    raw = result["data"]
    # Response: {"transfers": [...]}
    xfers = raw.get("transfers", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    
    parsed = []
    for xf in xfers[:limit]:
        if not isinstance(xf, dict):
            continue
        
        # Extract from/to with entity labels
        from_addr = xf.get("fromAddress", {}) or {}
        to_addr = xf.get("toAddress", {}) or {}
        
        parsed.append({
            "tx_hash":     xf.get("transactionHash", ""),
            "blockchain":  xf.get("chain", ""),
            "block":       xf.get("blockNumber", ""),
            "from": {
                "address": from_addr.get("address", ""),
                "entity":  from_addr.get("arkhamEntity", {}).get("name", "") if isinstance(from_addr.get("arkhamEntity"), dict) else "",
                "label":   from_addr.get("arkhamLabel", {}).get("name", "") if isinstance(from_addr.get("arkhamLabel"), dict) else "",
            },
            "to": {
                "address": to_addr.get("address", ""),
                "entity":  to_addr.get("arkhamEntity", {}).get("name", "") if isinstance(to_addr.get("arkhamEntity"), dict) else "",
                "label":   to_addr.get("arkhamLabel", {}).get("name", "") if isinstance(to_addr.get("arkhamLabel"), dict) else "",
            },
            "token":       xf.get("tokenSymbol", xf.get("tokenId", "")),
            "token_name":  xf.get("tokenName", ""),
            "token_id":    xf.get("tokenId", ""),
            "amount":      xf.get("unitValue", xf.get("rawValue", 0)),
            "amount_usd":  xf.get("historicalUSD", xf.get("usdValue", None)),
            "timestamp":   xf.get("blockTimestamp", xf.get("timestamp", "")),
        })
    
    return {
        "total":      len(parsed),
        "transfers":  parsed,
        "offset":     offset,
        "has_more":   len(parsed) >= limit,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }


# ─── High-Level Intelligence ──────────────────────────────────────────────────

def identify_wallet(address: str) -> dict:
    """
    Full wallet identification pipeline.
    
    Takes any address and returns:
    - Entity name (who owns this wallet)
    - Wallet type classification (exchange, fund, whale, etc.)
    - Risk assessment
    - Associated entity details
    
    Main entry point for upgrading anonymous addresses to named entities.
    """
    intel = get_address_intelligence(address)
    
    if "error" in intel and "primary_entity" not in intel:
        return intel
    
    # Classify based on entity info
    wallet_type = "unknown"
    risk_level = "medium"
    tags = []
    primary_entity = intel.get("primary_entity", "")
    entity_type = intel.get("entity_type", "")
    label = intel.get("label", "")
    deposit_service = intel.get("deposit_service", "")
    
    if primary_entity:
        entity_lower = primary_entity.lower()
        
        # Exchange detection
        exchange_keywords = ["binance", "coinbase", "kraken", "okx", "bybit", "bitfinex",
                           "gate.io", "huobi", "kucoin", "gemini", "cex", "exchange"]
        if any(kw in entity_lower for kw in exchange_keywords) or deposit_service:
            wallet_type = "exchange"
            risk_level = "low"
            tags.append("exchange")
            if deposit_service:
                tags.append(f"deposit:{deposit_service}")
        
        # Institutional / fund detection
        fund_keywords = ["galaxy", "jump", "paradigm", "a16z", "dragonfly", "multicoin",
                        "polychain", "alameda", "three arrows", "dcg", "grayscale",
                        "fund", "capital", "ventures", "partners", "asset management"]
        if any(kw in entity_lower for kw in fund_keywords):
            wallet_type = "institutional"
            risk_level = "low"
            tags.append("institutional")
        
        # Protocol / DeFi detection
        defi_keywords = ["uniswap", "aave", "compound", "maker", "curve", "lido",
                        "balancer", "sushiswap", "1inch", "protocol", "dao"]
        if any(kw in entity_lower for kw in defi_keywords):
            wallet_type = "defi_protocol"
            risk_level = "medium"
            tags.append("defi")
        
        # MEV / Arb detection
        mev_keywords = ["flashbots", "mev", "arbitrage", "sandwich", "builder"]
        if any(kw in entity_lower for kw in mev_keywords):
            wallet_type = "mev"
            risk_level = "high"
            tags.append("mev")
    
    # Check for contract/service
    if intel.get("is_contract"):
        tags.append("contract")
    if intel.get("is_service"):
        tags.append("service")
        if wallet_type == "unknown":
            wallet_type = "service"
    if intel.get("is_shielded"):
        tags.append("shielded")
        risk_level = "high"
    
    # Entity type tag
    if entity_type and entity_type != "unknown":
        tags.append(entity_type)
    
    return {
        "address":        address,
        "primary_entity": primary_entity,
        "primary_entity_id": intel.get("primary_entity_id", ""),
        "label":          label,
        "label_type":     intel.get("label_type", ""),
        "wallet_type":    wallet_type,
        "risk_level":     risk_level,
        "tags":           tags,
        "is_labeled":     intel.get("is_labeled", False),
        "is_contract":    intel.get("is_contract", False),
        "is_service":     intel.get("is_service", False),
        "deposit_service": deposit_service,
        "chain":          intel.get("chain", ""),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


def track_entity_flows(
    entity: str,
    flow: str = "all",
    tokens: str = None,
    chains: str = None,
    time_last: str = "24h",
    usd_gte: float = 100000,
    limit: int = 20,
) -> dict:
    """
    Track recent capital flows for a named entity.
    
    Args:
        entity: Arkham entity ID (e.g., "binance", "galaxy-digital")
        flow: Direction ("in", "out", "all")
        tokens: Token filter
        chains: Chain filter
        time_last: Duration (e.g., "24h", "7d")
        usd_gte: Min USD value (default $100k for significant moves)
        limit: Max results
    
    Returns:
        Recent transfers with flow analysis, net direction, and top counterparties.
    """
    xfers = get_transfers(
        base=entity,
        flow=flow if flow != "all" else None,
        tokens=tokens,
        chains=chains,
        time_last=time_last,
        usd_gte=usd_gte,
        sort_key="usd",
        sort_dir="desc",
        limit=limit,
    )
    
    # Aggregate flow analysis
    inflows = 0
    outflows = 0
    inflow_usd = 0.0
    outflow_usd = 0.0
    counterparties = {}
    
    for xf in xfers.get("transfers", []):
        amount_usd = xf.get("amount_usd") or 0
        if isinstance(amount_usd, str):
            try:
                amount_usd = float(amount_usd)
            except (ValueError, TypeError):
                amount_usd = 0
        
        from_entity = xf.get("from", {}).get("entity", "")
        to_entity = xf.get("to", {}).get("entity", "")
        
        if to_entity.lower() == entity.lower() or (not to_entity and not from_entity.lower() == entity.lower()):
            inflows += 1
            inflow_usd += amount_usd
            cp = from_entity or xf.get("from", {}).get("address", "")[:12] + "..."
        else:
            outflows += 1
            outflow_usd += amount_usd
            cp = to_entity or xf.get("to", {}).get("address", "")[:12] + "..."
        
        if cp:
            counterparties[cp] = counterparties.get(cp, 0) + 1
    
    net_flow_usd = inflow_usd - outflow_usd
    
    return {
        "entity":         entity,
        "flow":           flow,
        "time_window":    time_last,
        "inflows":        inflows,
        "outflows":       outflows,
        "inflow_usd":     round(inflow_usd, 2),
        "outflow_usd":    round(outflow_usd, 2),
        "net_flow_usd":   round(net_flow_usd, 2),
        "top_counterparties": dict(sorted(counterparties.items(), key=lambda x: -x[1])[:10]),
        "transfers":      xfers.get("transfers", []),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


# ─── Batch Processing ────────────────────────────────────────────────────────

def batch_identify(addresses: List[str]) -> List[dict]:
    """
    Identify multiple wallets in batch (sequential, rate-limited).
    
    Args:
        addresses: List of blockchain addresses
    
    Returns:
        List of identification results.
    """
    results = []
    for addr in addresses:
        result = identify_wallet(addr)
        results.append(result)
        time.sleep(0.2)
    return results


# ─── Formatters ───────────────────────────────────────────────────────────────

def format_entity_search(results: dict) -> str:
    """Format entity search results for Discord/terminal."""
    entities = results.get("entities", [])
    addresses = results.get("addresses", [])
    tokens = results.get("tokens", [])
    
    if not entities and not addresses and not tokens:
        return f"No results found for '{results.get('query', '')}'"
    
    lines = [f"**🔍 Arkham Search: '{results['query']}'**\n"]
    
    if entities:
        lines.append(f"**Entities ({len(entities)}):**")
        for i, ent in enumerate(entities[:10], 1):
            lines.append(f"  {i}. **{ent['name']}** — {ent.get('type', '')} | ID: `{ent.get('entity_id', '')}`")
    
    if addresses:
        lines.append(f"\n**Addresses ({len(addresses)}):**")
        for addr in addresses[:5]:
            entity_str = f" → {addr['entity']}" if addr.get("entity") else ""
            lines.append(f"  `{addr['address'][:12]}...` ({addr.get('chain', '')}){entity_str}")
    
    if tokens:
        lines.append(f"\n**Tokens ({len(tokens)}):**")
        for tok in tokens[:5]:
            lines.append(f"  {tok.get('symbol', '')} ({tok.get('name', '')}) — {tok.get('chain', '')}")
    
    return "\n".join(lines)


def format_wallet_id(id_result: dict) -> str:
    """Format wallet identification for Discord/terminal."""
    addr = id_result.get("address", "")
    entity = id_result.get("primary_entity", "Unlabeled")
    wtype = id_result.get("wallet_type", "unknown")
    risk = id_result.get("risk_level", "medium")
    tags = ", ".join(id_result.get("tags", [])) or "none"
    label = id_result.get("label", "")
    
    entity_emoji = {
        "exchange": "🏛️",
        "institutional": "🏦",
        "defi_protocol": "🔄",
        "mev": "⚡",
        "service": "🔧",
        "labeled_unknown": "🏷️",
        "unknown": "❓",
    }.get(wtype, "❓")
    
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
    
    short_addr = f"{addr[:10]}...{addr[-6:]}" if len(addr) > 16 else addr
    
    lines = [
        f"{entity_emoji} **Wallet Identification**",
        f"Address: `{short_addr}`",
        f"Entity: **{entity}**",
    ]
    if label:
        lines.append(f"Label: {label}")
    lines.append(f"Type: {wtype} | Risk: {risk_emoji} {risk}")
    if tags != "none":
        lines.append(f"Tags: {tags}")
    if id_result.get("is_contract"):
        lines.append("📜 Smart Contract")
    if id_result.get("deposit_service"):
        lines.append(f"🏦 Deposit: {id_result['deposit_service']}")
    
    return "\n".join(lines)


def format_entity_flows(flow_data: dict) -> str:
    """Format entity flow tracking for Discord/terminal."""
    entity = flow_data.get("entity", "")
    inflows = flow_data.get("inflows", 0)
    outflows = flow_data.get("outflows", 0)
    in_usd = flow_data.get("inflow_usd", 0)
    out_usd = flow_data.get("outflow_usd", 0)
    net = flow_data.get("net_flow_usd", 0)
    time_window = flow_data.get("time_window", "?")
    
    net_emoji = "🟢" if net > 0 else "🔴" if net < 0 else "⚪"
    direction = "NET INFLOW" if net > 0 else "NET OUTFLOW" if net < 0 else "NEUTRAL"
    
    lines = [
        f"📊 **Capital Flows: {entity}** ({time_window})",
        f"Inflows: {inflows} (${in_usd:,.0f})",
        f"Outflows: {outflows} (${out_usd:,.0f})",
        f"{net_emoji} **{direction}: ${abs(net):,.0f}**",
    ]
    
    cp = flow_data.get("top_counterparties", {})
    if cp:
        lines.append(f"\n**Top Counterparties:**")
        for name, count in list(cp.items())[:5]:
            lines.append(f"  → {name} ({count} txs)")
    
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    key = _get_key()
    if not key:
        print("❌ ARKHAM_API_KEY not set. Set it via environment variable or .env file.")
        sys.exit(1)
    
    print("=== Arkham Intelligence Client ===")
    print(f"API Key: {key[:8]}...{key[-4:]}")
    print(f"Base URL: {ARKHAM_BASE}")
    print()
    
    # Test 1: Search entities
    print("--- Test 1: Entity Search ('Binance') ---")
    result = search_entities("Binance")
    print(format_entity_search(result))
    print()
    
    # Test 2: Identify known wallet (Binance hot wallet)
    print("--- Test 2: Wallet Identification (Binance Hot) ---")
    binance_hot = "0x28C6c06298d514Db089934071355E5743bf21d60"
    id_result = identify_wallet(binance_hot)
    print(format_wallet_id(id_result))
    print()
    
    # Test 3: Entity intelligence
    print("--- Test 3: Entity Intelligence ('binance') ---")
    ent = get_entity_intelligence("binance")
    print(f"Name: {ent.get('name', '?')}")
    print(f"Type: {ent.get('type', '?')}")
    print(f"Tags: {[t.get('name', '') for t in ent.get('tags', [])]}")
    print()
    
    # Test 4: Transfers (last 24h, >$1M)
    print("--- Test 4: Binance Transfers (24h, >$100k) ---")
    xfers = get_transfers(base="binance", time_last="24h", usd_gte=100000, limit=5)
    print(f"Transfers found: {xfers.get('total', 0)}")
    for xf in xfers.get("transfers", [])[:3]:
        from_e = xf.get("from", {}).get("entity", "?")
        to_e = xf.get("to", {}).get("entity", "?")
        usd = xf.get("amount_usd", "?")
        token = xf.get("token", "?")
        print(f"  {from_e} → {to_e} | {token} ${usd}")
    if xfers.get("error"):
        print(f"Error: {xfers['error']}")
    print()
    
    # Test 5: Entity flows
    print("--- Test 5: Entity Flows (Binance, 24h) ---")
    flows = track_entity_flows("binance", time_last="24h", usd_gte=100000, limit=20)
    print(format_entity_flows(flows))
    
    print("\n✅ Arkham client tested")