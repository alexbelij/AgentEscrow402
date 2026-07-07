import fs from 'fs';
import sdk from 'casper-js-sdk';
const { PrivateKey, KeyAlgorithm } = sdk;
const pem = fs.readFileSync(process.argv[2], 'utf8');
const msg = process.argv[3];
const sk = await PrivateKey.fromPem(pem, KeyAlgorithm.ED25519);
const sig = await sk.sign(Buffer.from(msg, 'utf8'));
console.log(Buffer.from(sig).toString('hex'));
