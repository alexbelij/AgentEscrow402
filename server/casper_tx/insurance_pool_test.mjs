import fs from 'fs';
import sdk from 'casper-js-sdk';
const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC;
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT; // deposit|withdraw|claim|set_arbiters
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1');
const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

let argsMap = {};
if (ENTRY_POINT === 'deposit') {
  const mainPurse = sk.publicKey.accountHash(); // not actually purse; use session for real deposit instead
}
if (ENTRY_POINT === 'set_arbiters') {
  const arbiters = JSON.parse(process.env.ARBITERS_JSON);
  argsMap = { arbiters: CLValue.newCLList(CLTypeString, arbiters.map(a => CLValue.newCLString(a))) };
}
if (ENTRY_POINT === 'withdraw') {
  argsMap = {
    amount: CLValue.newCLUInt512(process.env.AMOUNT_MOTES),
    arbiter_pubkeys: CLValue.newCLList(CLTypeString, JSON.parse(process.env.ARBITER_PUBKEYS_JSON || '[]').map(a => CLValue.newCLString(a))),
    arbiter_signatures: CLValue.newCLList(CLTypeString, JSON.parse(process.env.ARBITER_SIGNATURES_JSON || '[]').map(a => CLValue.newCLString(a))),
  };
}
if (ENTRY_POINT === 'claim') {
  argsMap = {
    escrow_id: CLValue.newCLString(process.env.ESCROW_ID),
    amount: CLValue.newCLUInt512(process.env.AMOUNT_MOTES),
    evidence: CLValue.newCLString(process.env.EVIDENCE || 'test'),
    arbiter_pubkeys: CLValue.newCLList(CLTypeString, JSON.parse(process.env.ARBITER_PUBKEYS_JSON || '[]').map(a => CLValue.newCLString(a))),
    arbiter_signatures: CLValue.newCLList(CLTypeString, JSON.parse(process.env.ARBITER_SIGNATURES_JSON || '[]').map(a => CLValue.newCLString(a))),
  };
}

const args = Args.fromMap(argsMap);
const tx = new ContractCallBuilder()
  .byHash(CONTRACT_HASH)
  .entryPoint(ENTRY_POINT)
  .runtimeArgs(args)
  .from(sk.publicKey)
  .chainName('casper-test')
  .payment(Number(process.env.PAYMENT_MOTES || '10000000000'))
  .build();
await tx.sign(sk);
const handler = new HttpHandler(RPC);
if (process.env.CSPR_CLOUD_API_KEY) handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
const client = new RpcClient(handler);
try {
  const res = await client.putTransaction(tx);
  console.log(JSON.stringify({ success: true, hash: res.transactionHash?.toHex?.() || res.transactionHash }));
} catch (e) {
  console.log(JSON.stringify({ success: false, error: String(e) }));
}
