/**
 * gen_ed25519_key.mjs — Generate a fresh ed25519 keypair and write the PEM
 * to `<label>_secret_key.pem` in cwd. Usage: node gen_ed25519_key.mjs <label>
 */
import sdk from 'casper-js-sdk';
import fs from 'fs';
const { PrivateKey, KeyAlgorithm } = sdk;
const label = process.argv[2] || 'agent';
const sk = await PrivateKey.generate(KeyAlgorithm.ED25519);
const pem = sk.toPem();
fs.writeFileSync(`${label}_secret_key.pem`, pem);
console.log(JSON.stringify({
  label,
  pubkey_hex: sk.publicKey.toHex(),
  account_hash: sk.publicKey.accountHash().toHex ? sk.publicKey.accountHash().toHex() : sk.publicKey.accountHash().toString(),
}));
