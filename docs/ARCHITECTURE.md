# Architecture

## System Overview

```mermaid
graph TB
    A[AI Agent] -->|x402 header| B[FastAPI Server]
    B -->|create escrow| C[Casper Network]
    B -->|sandbox mode| D[In-Memory Store]
    C -->|CEP-88 events| E[Event Monitor]
    E -->|status updates| B

    subgraph Smart Contract
        C --> F[Escrow Logic]
        C --> G[Reputation]
        C --> H[Insurance Pool]
        C --> I[Dispute Resolution]
    end

    J[LangChain Agent] -->|EscrowPaymentTool| A
```

## Payment Flow

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant Server as Payment Server
    participant Contract as Escrow Contract

    Agent->>Server: POST /service (no payment)
    Server-->>Agent: 402 Payment Required

    Agent->>Server: POST /escrow {receiver, amount, ttl}
    Server->>Contract: create_escrow(sender, receiver, amount, ttl)
    Contract-->>Server: service_hash

    Agent->>Server: POST /service + X-Payment header
    Server->>Server: verify x402 header
    Server-->>Agent: 200 OK + service result

    Agent->>Server: POST /release {service_hash}
    Server->>Contract: release(service_hash)
    Contract-->>Server: funds transferred to receiver
```

## Dispute Resolution

The arbiter pool is 5 registered accounts; `resolve()` requires a quorum of at least 3 valid,
deduplicated Ed25519 arbiter signatures over the verdict payload (3-of-5 multi-sig).

```mermaid
sequenceDiagram
    participant P as Party
    participant S as Server
    participant C as Contract
    participant A1 as Arbiter 1
    participant A2 as Arbiter 2
    participant A3 as Arbiter 3
    participant A4 as Arbiter 4
    participant A5 as Arbiter 5

    P->>S: POST /dispute {service_hash, reason}
    S->>C: dispute(service_hash)
    Note over C: Status = DISPUTED

    Note over A1,A5: Off-chain: arbiters sign the verdict (RELEASE or REFUND)
    A1->>S: sign(RELEASE)
    A2->>S: sign(RELEASE)
    A3->>S: sign(RELEASE)
    S->>C: resolve(hash, RELEASE, [sig_A1, sig_A2, sig_A3])
    Note over C: verify_arbiter_quorum: 3 valid signatures >= threshold (3-of-5)
    C->>C: transfer funds to receiver
```

## Module Dependencies

```mermaid
graph LR
    app[app.py] --> middleware[middleware.py]
    app --> casper[casper_client.py]
    app --> sandbox[sandbox.py]
    app --> models[models.py]
    app --> monitor[event_monitor.py]
    monitor --> casper
    sdk_client[sdk/client.py] --> app
    langchain[sdk/langchain_tool.py] --> sdk_client
```
