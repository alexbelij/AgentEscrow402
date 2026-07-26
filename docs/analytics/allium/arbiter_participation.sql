-- Arbiter participation: who has voted, how often, and on which
-- disputes. Feeds the "arbiter panel health" widget.
--
-- Parameters:
--   :contract_hash — on-chain address of the challenge-arbiter contract
--   :days_back      — window (default 30)
--
-- Result columns:
--   arbiter_hash    — account_hash of the arbiter
--   votes_cast      — how many votes they submitted in the window
--   distinct_cases  — how many unique disputes they touched
--   abstain_rate    — fraction of their votes that were "abstain"

SELECT
    t.args ->> 'arbiter_hash' AS arbiter_hash,
    COUNT(*) AS votes_cast,
    COUNT(DISTINCT t.args ->> 'dispute_id') AS distinct_cases,
    AVG(CASE WHEN t.args ->> 'verdict' = 'abstain' THEN 1.0 ELSE 0.0 END) AS abstain_rate
FROM casper.contract_calls t
WHERE t.contract_hash = :contract_hash
  AND t.entry_point = 'submit_vote'
  AND t.block_timestamp >= extract(epoch FROM now()) - (:days_back * 86400)
GROUP BY 1
ORDER BY votes_cast DESC;
