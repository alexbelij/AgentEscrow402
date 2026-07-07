/**
 * query_agent.mjs — Read an agent-identity-registry record straight from
 * chain via state_get_dictionary_item (not via a deploy). Env:
 *   CONTRACT_HASH, OWNER_HEX, CASPER_RPC, CSPR_CLOUD_API_KEY
 */
const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const OWNER_HEX = process.env.OWNER_HEX;

const headers = {
  'Content-Type': 'application/json',
  ...(process.env.CSPR_CLOUD_API_KEY ? { Authorization: process.env.CSPR_CLOUD_API_KEY } : {}),
};

const rootRes = await fetch(RPC, {
  method: 'POST', headers,
  body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'chain_get_state_root_hash', params: {} }),
});
const rootJson = await rootRes.json();
const stateRootHash = rootJson.result.state_root_hash;

const rpcRes = await fetch(RPC, {
  method: 'POST',
  headers,
  body: JSON.stringify({
    jsonrpc: '2.0', id: 1, method: 'state_get_dictionary_item',
    params: {
      state_root_hash: stateRootHash,
      dictionary_identifier: {
        ContractNamedKey: {
          key: `hash-${CONTRACT_HASH}`,
          dictionary_name: 'agents',
          dictionary_item_key: OWNER_HEX,
        },
      },
    },
  }),
});
const json = await rpcRes.json();
console.log(JSON.stringify(json, null, 2));
