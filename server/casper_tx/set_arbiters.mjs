import fs from 'fs';
import sdk from 'casper-js-sdk';
const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const PEM_PATH = process.env.PEM_PATH;
const ARBITERS = JSON.parse(process.env.ARBITERS_JSON);

const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), KeyAlgorithm.SECP256K1);

const args = Args.fromMap({
  arbiters: CLValue.newCLList(CLTypeString, ARBITERS.map(a => CLValue.newCLString(a))),
});

const tx = new ContractCallBuilder()
  .byHash(CONTRACT_HASH)
  .entryPoint('set_arbiters')
  .runtimeArgs(args)
  .from(sk.publicKey)
  .chainName('casper-test')
  .payment(10_000_000_000)
  .build();

await tx.sign(sk);
const client = new RpcClient(new HttpHandler(RPC));
const res = await client.putTransaction(tx);
console.log(JSON.stringify({ hash: res.transactionHash?.toHex?.() || res.transactionHash }));
