-- Time between escrow creation and dispute opening.
-- Answers: are people disputing quickly (real disagreement) or
-- shopping (long tail)?
--
-- Parameters:
--   :contract_hash — on-chain address of the AE402 escrow-manager
--
-- Result columns:
--   service_hash    — escrow id
--   created_at      — Unix ts of create_escrow
--   dispute_at      — Unix ts of dispute() call
--   lag_seconds     — dispute_at - created_at

WITH creates AS (
    SELECT
        t.args ->> 'service_hash' AS service_hash,
        MIN(t.block_timestamp) AS created_at
    FROM casper.contract_calls t
    WHERE t.contract_hash = :contract_hash
      AND t.entry_point = 'create_escrow'
    GROUP BY 1
),
disputes AS (
    SELECT
        t.args ->> 'service_hash' AS service_hash,
        MIN(t.block_timestamp) AS dispute_at
    FROM casper.contract_calls t
    WHERE t.contract_hash = :contract_hash
      AND t.entry_point = 'dispute'
    GROUP BY 1
)
SELECT
    c.service_hash,
    c.created_at,
    d.dispute_at,
    d.dispute_at - c.created_at AS lag_seconds
FROM creates c
JOIN disputes d USING (service_hash)
ORDER BY lag_seconds ASC;
