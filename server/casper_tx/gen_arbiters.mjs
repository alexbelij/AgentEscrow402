import sdk from 'casper-js-sdk';
import fs from 'fs';
const { PrivateKey, KeyAlgorithm } = sdk;

const out = [];
for (let i = 1; i <= 5; i++) {
  const key = await PrivateKey.generate(KeyAlgorithm.ED25519);
  const pemPath = `/work/temp/keys/arbiters/arbiter_${i}_secret_key.pem`;
  fs.writeFileSync(pemPath, key.toPem());
  const pubHex = key.publicKey.toHex().toLowerCase();
  const accountHashHex = key.publicKey.accountHash().toHex();
  out.push({ i, pubHex, accountHashHex, pemPath });
}
fs.writeFileSync('/work/temp/keys/arbiters/arbiters.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
