"""
Zeitgeist AI — Auto Resolver Bot

Checks all markets on the Zeitgeist AI contract. For any market whose
deadline has passed and is not yet resolved, calls resolve_market()
which triggers the 5 LLM validators to reach consensus on the outcome.

Runs via GitHub Actions on a schedule (see .github/workflows/resolver.yml)
"""

import os
import sys
import time
import json
import urllib.request

RPC_URL = "https://studio.genlayer.com/api"
CONTRACT_ADDRESS = "0xDcb5dB0D44E8e860172d301eEb0F444Efdc306B7"

# Private key of the bot's wallet (set as a GitHub Secret, never commit this!)
BOT_PRIVATE_KEY = os.environ.get("BOT_PRIVATE_KEY", "")


def rpc_call(method, params):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }).encode("utf-8")

    req = urllib.request.Request(
        RPC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Zeitgeist-AI-Resolver-Bot/1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["result"]


def gen_call(function_name, args):
    """Read-only contract call."""
    raw = rpc_call("gen_call", [{
        "to": CONTRACT_ADDRESS,
        "data": json.dumps({"method": function_name, "args": args}),
    }, "latest"])
    return json.loads(raw)


def main():
    print("🤖 Zeitgeist AI Resolver Bot starting...")

    if not BOT_PRIVATE_KEY:
        print("⚠️  BOT_PRIVATE_KEY not set — running in DRY RUN mode (read-only).")

    count = gen_call("get_market_count", [])
    print(f"Found {count} markets total.")

    now = int(time.time())
    resolved_count = 0

    for market_id in range(count):
        market = gen_call("get_market", [market_id])

        if market["resolved"]:
            continue

        deadline = int(market["deadline"])
        if now < deadline:
            print(f"⏳ Market {market_id} '{market['question'][:50]}...' — not yet due "
                  f"(deadline {deadline}, now {now})")
            continue

        print(f"🔔 Market {market_id} '{market['question'][:50]}...' is past deadline. Resolving...")

        if not BOT_PRIVATE_KEY:
            print("   (dry run — skipping actual resolve_market call)")
            continue

        try:
            # NOTE: Sending a write transaction requires signing with the bot's
            # private key. This uses the genlayer-py SDK for proper signing.
            from genlayer_py import create_account, create_client
            from genlayer_py.chains import studionet

            account = create_account(BOT_PRIVATE_KEY)
            client = create_client(chain=studionet, account=account)

            tx_hash = client.write_contract(
                address=CONTRACT_ADDRESS,
                function_name="resolve_market",
                args=[market_id],
            )
            print(f"   ✅ resolve_market tx sent: {tx_hash}")
            resolved_count += 1

            # Wait a bit between resolutions to avoid overloading validators
            time.sleep(5)

        except Exception as e:
            print(f"   ❌ Failed to resolve market {market_id}: {e}")

    print(f"\nDone. Resolved {resolved_count} market(s) this run.")


if __name__ == "__main__":
    main()
