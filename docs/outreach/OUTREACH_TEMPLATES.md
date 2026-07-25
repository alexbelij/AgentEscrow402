# Outreach templates

**Rule of thumb:** ≤ 4 sentences, one clear ask, one specific hook per
person. Never blast-send. Personalize the [BRACKETS] before firing.

## Channel 1 — LangChain Discord (or forum)

**Where:** #showcase, #general, or DM after a relevant post.
**When:** you saw them ship an agent that pays / rewards / disputes.

```
Hey [name] — saw your [agent name / project] handle [specific thing,
e.g. "multi-step reward payouts to workers"] this week. We just
open-sourced an escrow SDK (AgentEscrow402) that gives your agent
programmatic dispute + refund on top of Casper — 5 lines of Python,
no wallet UX. Would you try it against one of your flows this weekend
and tell me where it hurts? Repo: https://github.com/alexbelij/AgentEscrow402
```

## Channel 2 — X / Twitter DM

**When:** they've tweeted about agent payments, AI wallets, or dispute
resolution.

```
Hey — your tweet about [specific: "agents needing to argue their
receipts"] is exactly the problem we solved. AgentEscrow402: a
disputable escrow layer that agents call in one line. Pilot-testing
this weekend; can I hand you a $50 testnet credit + a 15-min setup?
```

## Channel 3 — AutoGen / CrewAI Discord

**When:** they're building a multi-agent workflow with monetary flows.

```
[name] — noticed your [workflow name] passes value between
[agent A] and [agent B]. If either one flakes, the other one has no
recourse. We just shipped AgentEscrow402 — the escrow FSM sits
between them, and either side can trigger dispute + arbitration
(there's a real LLM arbiter, not a mock). One-liner install, works
in your existing loop. Want a 15-min pair to wire it in?
```

## Warm referral (from Casper community / hackathon org)

**When:** someone in the Casper community intros you to their contact.

```
Hey [name] — [referrer] said you're the right person to talk to about
agent-to-agent payments. We built AgentEscrow402 for the Casper
hackathon — it's the escrow + dispute layer your agents can call in
one API call. If you can spare 15 minutes this week I'd love to walk
through it, and if it clicks, we'll pilot it against your flow with
testnet credits on us.
```

## Follow-up (day 3, no response)

```
Bumping this in case it got buried — no pressure if you're heads-down.
Two lines below to make the "why bother" obvious:

  - You call `client.create_escrow(receiver=..., amount=...)`.
  - If the receiver flakes, you call `client.dispute(...)` — a real
    LLM arbiter (not a mock) rules and refunds.

Repo: https://github.com/alexbelij/AgentEscrow402  ·  Runs on Casper testnet,
no gas cost to you.
```

## Anti-patterns — don't do

- "Hey — checking if you got my message" (dead on arrival).
- Sending the same DM to 20 people (spam filter + community reputation).
- Leading with the tech ("bulletproof range proofs on secp256k1..." —
  they don't care yet).
- Asking for a testimonial before they've used it.
