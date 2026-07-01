---- MODULE EscrowSpec ----
\* Formal specification of AgentEscrow402 state machine.
\* Status: initial stub — full verification planned for Phase 4.

EXTENDS Naturals, Sequences

CONSTANTS MaxAmount, MaxParties

VARIABLES state, balance, obligations, reputation

States == {"Created", "Funded", "Delivered", "Disputed", "Completed", "Refunded", "Expired"}

TypeOK ==
    /\ state \in States
    /\ balance \in Nat
    /\ balance >= obligations
    /\ obligations \in Nat
    /\ reputation \in 0..100

Init ==
    /\ state = "Created"
    /\ balance = 0
    /\ obligations = 0
    /\ reputation = 50

\* Invariant: escrow balance always covers obligations
BalanceSolvency == balance >= obligations

\* Invariant: only valid state transitions
ValidTransitions ==
    /\ (state = "Created")   => (state' \in {"Funded"})
    /\ (state = "Funded")    => (state' \in {"Delivered", "Disputed", "Expired"})
    /\ (state = "Delivered") => (state' \in {"Completed"})
    /\ (state = "Disputed")  => (state' \in {"Completed", "Refunded"})
    /\ (state = "Expired")   => (state' \in {"Refunded"})
    /\ (state \in {"Completed", "Refunded"}) => UNCHANGED state

\* Invariant: reputation in range
ReputationRange == reputation \in 0..100

\* Invariant: VRF fairness (arbiter not party to dispute)
\* Modeled abstractly: arbiter_id /= buyer_id /\ arbiter_id /= seller_id

SafetyInvariant == BalanceSolvency /\ ReputationRange

====
