-- Insurance pool state: premiums in, claims out, per day.
-- Together with the pool's own /insurance/pool-stats endpoint this
-- gives the operator a full solvency picture at a glance.
--
-- Parameters:
--   :contract_hash — on-chain address of the insurance-pool contract
--
-- Result columns:
--   day               — UTC calendar day
--   premiums_motes    — sum of deposit() amounts
--   claims_motes      — sum of successful claim() payouts
--   net_motes         — premiums - claims
--   running_balance   — cumulative sum of net over time

WITH events AS (
    SELECT
        date_trunc('day', to_timestamp(t.block_timestamp)) AS day,
        SUM(CASE WHEN t.entry_point = 'deposit'
                 THEN CAST(t.args ->> 'amount_motes' AS BIGINT) ELSE 0 END) AS premiums_motes,
        SUM(CASE WHEN t.entry_point = 'claim'
                 THEN CAST(t.args ->> 'amount_motes' AS BIGINT) ELSE 0 END) AS claims_motes
    FROM casper.contract_calls t
    WHERE t.contract_hash = :contract_hash
      AND t.entry_point IN ('deposit', 'claim')
    GROUP BY 1
)
SELECT
    day,
    premiums_motes,
    claims_motes,
    premiums_motes - claims_motes AS net_motes,
    SUM(premiums_motes - claims_motes) OVER (ORDER BY day) AS running_balance
FROM events
ORDER BY day DESC;
