# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import typing

TREASURY = Address("0xbB6a1151729AF0F941137782E247b0045D49ee13")


class ZeitgeistAI(gl.Contract):
    question:       str
    category:       str
    resolution_url: str
    option_a:       str
    option_b:       str
    pool_a:         u256
    pool_b:         u256
    resolved:       bool
    flagged:        bool
    winner:         str
    reasoning:      str
    creator:        Address
    bettor_bonus:   u256

    def __init__(self, question: str, category: str, resolution_url: str, option_a: str, option_b: str) -> None:
        assert len(question) > 10, "Question too short"
        assert category in ("crypto", "politics", "sports", "tech", "culture"), "Invalid category"
        self.question       = question
        self.category       = category
        self.resolution_url = resolution_url
        self.option_a       = option_a
        self.option_b       = option_b
        self.pool_a         = u256(0)
        self.pool_b         = u256(0)
        self.resolved       = False
        self.flagged        = False
        self.winner         = ""
        self.reasoning      = ""
        self.creator        = gl.message.sender_address
        self.bettor_bonus   = u256(0)

    @gl.public.write.payable
    def place_bet(self, option: str) -> None:
        assert not self.resolved, "Market already resolved"
        assert not self.flagged,  "Market flagged as spam"
        assert option in ("A", "B"), "Option must be A or B"
        amount = gl.message.value
        assert amount > u256(0), "Must stake positive amount"
        if option == "A":
            self.pool_a = u256(int(self.pool_a) + int(amount))
        else:
            self.pool_b = u256(int(self.pool_b) + int(amount))

    @gl.public.write
    def flag_spam(self) -> None:
        assert not self.resolved, "Market already resolved"
        assert not self.flagged,  "Already flagged"
        self.flagged      = True
        self.bettor_bonus = u256(15 * 10**18)
        gl.message.sender_address.transfer(u256(10 * 10**18))
        TREASURY.transfer(u256(5 * 10**18))

    @gl.public.write
    def resolve_market(self) -> typing.Any:
        assert not self.resolved, "Already resolved"
        assert not self.flagged,  "Market flagged as spam"

        resolution_url = self.resolution_url
        question       = self.question
        option_a       = self.option_a
        option_b       = self.option_b

        def get_result() -> typing.Any:
            web_data = gl.nondet.web.get(resolution_url)
            excerpt  = web_data.body.decode("utf-8", errors="replace")[:3000]
            prompt   = f"""You are an impartial judge resolving a prediction market.

QUESTION: {question}

OPTIONS:
A: {option_a}
B: {option_b}

EVIDENCE:
{excerpt}

Reply ONLY with valid JSON:
{{"winner": "A" or "B", "reasoning": "<one sentence>"}}

If insufficient evidence:
{{"winner": "UNDETERMINED", "reasoning": "<why>"}}"""
            raw = gl.nondet.exec_prompt(prompt).replace("```json","").replace("```","")
            return json.loads(raw)

        result = gl.eq_principle.prompt_comparative(
            get_result,
            principle="The `winner` field must be exactly the same. Reasoning may differ."
        )
        self.resolved  = True
        self.winner    = result["winner"]
        self.reasoning = result["reasoning"]
        return result

    @gl.public.write
    def claim_winnings(self, staked_amount: u256, option: str) -> None:
        assert self.resolved, "Market not resolved yet"
        assert self.winner != "UNDETERMINED", "Outcome undetermined"
        assert option == self.winner, "You bet on the losing option"
        winning_pool = self.pool_a if self.winner == "A" else self.pool_b
        total_pool   = u256(int(self.pool_a) + int(self.pool_b) + int(self.bettor_bonus))
        assert int(winning_pool) > 0, "Winning pool empty"
        payout = (int(staked_amount) * int(total_pool)) // int(winning_pool)
        gl.message.sender_address.transfer(u256(payout))

    @gl.public.view
    def get_info(self) -> dict:
        return {
            "question":     self.question,
            "category":     self.category,
            "option_a":     self.option_a,
            "option_b":     self.option_b,
            "pool_a":       int(self.pool_a),
            "pool_b":       int(self.pool_b),
            "total_volume": int(self.pool_a) + int(self.pool_b),
            "resolved":     self.resolved,
            "flagged":      self.flagged,
            "winner":       self.winner,
            "reasoning":    self.reasoning,
            "creator":      str(self.creator),
        }
