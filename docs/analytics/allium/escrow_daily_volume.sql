-- Escrow daily volume by AE402
--
-- Parameters:
--   :contract_hash — on-chain address of the AE402 escrow-manager
--   :days_back      — window (default 30)
--
-- Result columns:
--   day             — UTC calendar day (YYYY-MM-DD)
--   escrows_created — count of create_escrow txs that day
--   total_motes     — sum of amount_motes across those escrows
--   unique_agents   — distinct sender+receiver addresses touched

SELECT
    date_trunc('day', to_timestamp(t.block_timestamp)) AS day,
    COUNT(*) AS escrows_created,
    SUM(CAST(t.args ->> 'amount_motes' AS BIGINT)) AS total_motes,
    COUNT(DISTINCT t.args ->> 'sender') +
        COUNT(DISTINCT t.args ->> 'receiver') AS unique_agents
FROM casper.contract_calls t
WHERE t.contract_hash = :contract_hash
  AND t.entry_point = 'create_escrow'
  AND t.block_timestamp >= extract(epoch FROM now()) - (:days_back * 86400)
GROUP BY 1
ORDER BY 1 DESC;
