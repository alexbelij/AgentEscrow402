/**
 * cep78_mint.mjs — Call the CEP-78 `mint` entry point, to verify real
 * on-chain NFT minting for AE402 B1.
 *
 * Env vars:
 *   CONTRACT_HASH  — 64-char hex CEP-78 contract hash
 *   OWNER_HEX      — 64-char hex account hash of the initial token owner
 *   NAME/TOKEN_URI/CHECKSUM — CEP78-schema metadata fields (name, token_uri,
 *                             checksum required by the built-in CEP78 schema
 *                             -- note: despite the name, this is NOT symbol)
 *   PEM_PATH       — deployer/minter PEM private key
 *   KEY_ALGO       — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC     — RPC URL
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue, Key } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const OWNER_HEX = process.env.OWNER_HEX;
const NAME = process.env.NAME || 'AE402 Test NFT #1';
const TOKEN_URI = process.env.TOKEN_URI || 'https://agentescrow402.example/nft/1';
const CHECKSUM = process.env.CHECKSUM || '0000000000000000000000000000000000000000000000000000000000000000';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing/invalid');
  if (!OWNER_HEX || OWNER_HEX.length !== 64) fail('OWNER_HEX missing/invalid');
  if (!PEM_PATH) fail('PEM_PATH missing');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const ownerKey = CLValue.newCLKey(Key.newKey(`account-hash-${OWNER_HEX}`));
  const metadata = JSON.stringify({ name: NAME, token_uri: TOKEN_URI, checksum: CHECKSUM });

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('mint')
    .runtimeArgs(Args.fromMap({
      token_owner: ownerKey,
      token_meta_data: CLValue.newCLString(metadata),
    }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(30_000_000_000) // 30 CSPR
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);
  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
