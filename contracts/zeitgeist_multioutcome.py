# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import typing


class ZeitgeistAI(gl.Contract):
    """
    Zeitgeist AI — Multi-market, multi-outcome prediction market on GenLayer.

    - One contract, unlimited markets
    - 2 to 8 outcomes per market (Yes/No OR Brazil/France/Argentina/...)
    - LLM validators resolve using live web evidence
    - Winners claim proportional payouts
    """

    market_count: u32

    # Per-market data (market_id → value)
    questions:       TreeMap[u32, str]
    categories:      TreeMap[u32, str]
    resolution_urls: TreeMap[u32, str]
    outcomes_json:   TreeMap[u32, str]   # JSON array e.g. '["Brazil","France","Argentina"]'
    outcome_counts:  TreeMap[u32, u32]
    resolved:        TreeMap[u32, bool]
    winner_indexes:  TreeMap[u32, str]   # "" = unresolved, "-1" = undetermined, "0".."7" = winner
    reasonings:      TreeMap[u32, str]
    creators:        TreeMap[u32, Address]
    deadlines:       TreeMap[u32, u256]

    # Pools: "marketid:outcomeindex" → total staked
    pools: TreeMap[str, u256]

    # Bets: "marketid:address" → amount / outcome index / claimed
    bet_amounts: TreeMap[str, u256]
    bet_indexes: TreeMap[str, u32]
    bet_claimed: TreeMap[str, bool]

    def __init__(self) -> None:
        self.market_count = u32(0)

    # ── Create market ─────────────────────────────────────────────────────────

    @gl.public.write
    def create_market(
        self,
        question:       str,
        category:       str,
        resolution_url: str,
        outcomes:       str,    # JSON array string: '["Yes","No"]'
        deadline:       u256,
    ) -> u32:
        assert len(question) > 10, "Question too short"
        assert category in ("crypto", "politics", "sports", "tech", "culture"), "Invalid category"

        parsed = json.loads(outcomes)
        assert isinstance(parsed, list), "Outcomes must be a JSON array"
        assert 2 <= len(parsed) <= 8, "Need 2 to 8 outcomes"
        for o in parsed:
            assert isinstance(o, str) and len(o) > 0, "Each outcome must be a non-empty string"

        mid = self.market_count
        self.questions[mid]       = question
        self.categories[mid]      = category
        self.resolution_urls[mid] = resolution_url
        self.outcomes_json[mid]   = outcomes
        self.outcome_counts[mid]  = u32(len(parsed))
        self.resolved[mid]        = False
        self.winner_indexes[mid]  = ""
        self.reasonings[mid]      = ""
        self.creators[mid]        = gl.message.sender_address
        self.deadlines[mid]       = deadline

        for i in range(len(parsed)):
            self.pools[f"{int(mid)}:{i}"] = u256(0)

        self.market_count = u32(int(mid) + 1)
        return mid

    # ── Betting ───────────────────────────────────────────────────────────────

    @gl.public.write.payable
    def place_bet(self, market_id: u32, outcome_index: u32) -> None:
        assert int(market_id) < int(self.market_count), "Market does not exist"
        assert not self.resolved.get(market_id, False), "Market already resolved"
        assert int(outcome_index) < int(self.outcome_counts[market_id]), "Invalid outcome index"

        amount = gl.message.value
        assert amount > u256(0), "Must stake positive amount"

        key = f"{int(market_id)}:{str(gl.message.sender_address).lower()}"
        assert int(self.bet_amounts.get(key, u256(0))) == 0, "Already bet on this market"

        self.bet_amounts[key] = amount
        self.bet_indexes[key] = outcome_index
        self.bet_claimed[key] = False

        pool_key = f"{int(market_id)}:{int(outcome_index)}"
        self.pools[pool_key] = u256(int(self.pools.get(pool_key, u256(0))) + int(amount))

    # ── AI Resolution ─────────────────────────────────────────────────────────

    @gl.public.write
    def resolve_market(self, market_id: u32) -> typing.Any:
        assert int(market_id) < int(self.market_count), "Market does not exist"
        assert not self.resolved.get(market_id, False), "Already resolved"

        resolution_url = self.resolution_urls[market_id]
        question       = self.questions[market_id]
        outcomes_list  = json.loads(self.outcomes_json[market_id])
        outcomes_str   = "\n".join(f"{i}. {o}" for i, o in enumerate(outcomes_list))
        max_index      = len(outcomes_list) - 1

        def get_result() -> typing.Any:
            web_data = gl.nondet.web.get(resolution_url)
            excerpt  = web_data.body.decode("utf-8", errors="replace")[:3000]
            prompt   = f"""You are an impartial judge resolving a prediction market.

QUESTION: {question}

POSSIBLE OUTCOMES (choose one by index):
{outcomes_str}

EVIDENCE:
{excerpt}

Reply ONLY with valid JSON:
{{"winner_index": <integer 0 to {max_index}>, "reasoning": "<one sentence>"}}

If insufficient evidence:
{{"winner_index": -1, "reasoning": "<why>"}}"""
            raw = gl.nondet.exec_prompt(prompt).replace("```json","").replace("```","")
            result = json.loads(raw)
            assert isinstance(result.get("winner_index"), int), "winner_index must be int"
            assert -1 <= result["winner_index"] <= max_index, "winner_index out of range"
            return result

        result = gl.eq_principle.prompt_comparative(
            get_result,
            principle="The `winner_index` field must be exactly the same. Reasoning may differ."
        )

        self.resolved[market_id]       = True
        self.winner_indexes[market_id] = str(result["winner_index"])
        self.reasonings[market_id]     = result["reasoning"]
        return result

    # ── Claim winnings ────────────────────────────────────────────────────────

    @gl.public.write
    def claim_winnings(self, market_id: u32) -> None:
        assert self.resolved.get(market_id, False), "Market not resolved yet"
        winner_str = self.winner_indexes[market_id]
        assert winner_str != "-1" and winner_str != "", "Outcome undetermined"

        key = f"{int(market_id)}:{str(gl.message.sender_address).lower()}"
        amount = int(self.bet_amounts.get(key, u256(0)))
        assert amount > 0, "No bet found"
        assert not self.bet_claimed.get(key, False), "Already claimed"
        assert int(self.bet_indexes[key]) == int(winner_str), "You bet on the losing outcome"

        winning_pool = int(self.pools.get(f"{int(market_id)}:{winner_str}", u256(0)))
        total_pool = 0
        for i in range(int(self.outcome_counts[market_id])):
            total_pool += int(self.pools.get(f"{int(market_id)}:{i}", u256(0)))
        assert winning_pool > 0, "Winning pool empty"

        payout = (amount * total_pool) // winning_pool
        self.bet_claimed[key] = True
        gl.message.sender_address.transfer(u256(payout))

    # ── Views ─────────────────────────────────────────────────────────────────

    @gl.public.view
    def get_market_count(self) -> int:
        return int(self.market_count)

    @gl.public.view
    def get_market(self, market_id: u32) -> dict:
        assert int(market_id) < int(self.market_count), "Market does not exist"
        outcomes_list = json.loads(self.outcomes_json[market_id])
        pools_list = []
        total = 0
        for i in range(len(outcomes_list)):
            p = int(self.pools.get(f"{int(market_id)}:{i}", u256(0)))
            pools_list.append(p)
            total += p
        winner_str = self.winner_indexes.get(market_id, "")
        return {
            "id":            int(market_id),
            "question":      self.questions[market_id],
            "category":      self.categories[market_id],
            "outcomes":      outcomes_list,
            "outcome_pools": pools_list,
            "total_volume":  total,
            "resolved":      self.resolved.get(market_id, False),
            "winning_index": int(winner_str) if winner_str != "" else -1,
            "reasoning":     self.reasonings.get(market_id, ""),
            "creator":       str(self.creators[market_id]),
            "deadline":      int(self.deadlines.get(market_id, u256(0))),
            "resolution_url": self.resolution_urls[market_id],
        }

    @gl.public.view
    def get_my_bet(self, market_id: u32, addr: str) -> dict:
        key = f"{int(market_id)}:{addr.lower()}"
        amount = int(self.bet_amounts.get(key, u256(0)))
        if amount == 0:
            return {"has_bet": False}
        return {
            "has_bet":       True,
            "outcome_index": int(self.bet_indexes.get(key, u32(0))),
            "amount":        amount,
            "claimed":       self.bet_claimed.get(key, False),
        }
