-- Anomaly flow — feeds the regime-shift detector.
--
-- For every counterparty pair, computes a rolling 7-day mean and std
-- of escrow amounts and returns each new escrow whose amount is
-- > mu + 3*sigma. These outliers are exactly the samples the CUSUM
-- widget on /console/risk consumes as its `samples[]` stream.
--
-- Parameters:
--   :contract_hash — on-chain address of the AE402 escrow-manager
--   :days_back      — window (default 30)
--
-- Result columns:
--   service_hash    — escrow id
--   counterparty    — sender:receiver
--   amount_motes    — escrow amount
--   mu_motes        — rolling 7-day mean of this counterparty
--   sigma_motes     — rolling 7-day std-dev of this counterparty
--   z_score         — (amount - mu) / sigma

WITH escrows AS (
    SELECT
        t.args ->> 'service_hash' AS service_hash,
        t.args ->> 'sender' AS sender,
        t.args ->> 'receiver' AS receiver,
        CAST(t.args ->> 'amount_motes' AS BIGINT) AS amount_motes,
        t.block_timestamp AS ts
    FROM casper.contract_calls t
    WHERE t.contract_hash = :contract_hash
      AND t.entry_point = 'create_escrow'
      AND t.block_timestamp >= extract(epoch FROM now()) - (:days_back * 86400)
),
enriched AS (
    SELECT
        service_hash,
        sender,
        receiver,
        amount_motes,
        ts,
        AVG(amount_motes) OVER (
            PARTITION BY sender, receiver
            ORDER BY ts
            RANGE BETWEEN 7 * 86400 PRECEDING AND 1 PRECEDING
        ) AS mu_motes,
        STDDEV_POP(amount_motes) OVER (
            PARTITION BY sender, receiver
            ORDER BY ts
            RANGE BETWEEN 7 * 86400 PRECEDING AND 1 PRECEDING
        ) AS sigma_motes
    FROM escrows
)
SELECT
    service_hash,
    sender || ':' || receiver AS counterparty,
    amount_motes,
    mu_motes,
    sigma_motes,
    CASE
        WHEN sigma_motes > 0
        THEN (amount_motes - mu_motes) / sigma_motes
        ELSE NULL
    END AS z_score
FROM enriched
WHERE sigma_motes > 0
  AND (amount_motes - mu_motes) / sigma_motes > 3
ORDER BY z_score DESC;
