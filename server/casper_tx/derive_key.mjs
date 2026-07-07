/**
 * derive_key.mjs — Print an account's public key hex + account hash from a
 * secp256k1 PEM private key file. Usage: node derive_key.mjs <pem_path>
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';
const { PrivateKey, KeyAlgorithm } = sdk;
const pem = fs.readFileSync(process.argv[2], 'utf8');
const sk = await PrivateKey.fromPem(pem, KeyAlgorithm.SECP256K1);
console.log(JSON.stringify({
  pubkey_hex: sk.publicKey.toHex(),
  account_hash: sk.publicKey.accountHash().toHex ? sk.publicKey.accountHash().toHex() : sk.publicKey.accountHash().toString(),
}));
