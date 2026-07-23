import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildResolveMessage,
  buildCapApprovalMessage,
  buildInsuranceClaimMessage,
  verifyEd25519Vote,
  countValidVotes,
  countValidCapApprovalVotes,
  countValidInsuranceClaimVotes,
} from "./verify.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");

async function generateArbiterKeypair(): Promise<{ pubkeyHex: string; sign: (message: Uint8Array) => Promise<string> }> {
  const { publicKey, privateKey } = await crypto.subtle.generateKey({ name: "Ed25519" }, true, [
    "sign",
    "verify",
  ]);
  const rawPub = new Uint8Array(await crypto.subtle.exportKey("raw", publicKey));
  const pubkeyHex = "01" + Buffer.from(rawPub).toString("hex");
  return {
    pubkeyHex,
    sign: async (message: Uint8Array) => {
      const sig = await crypto.subtle.sign({ name: "Ed25519" }, privateKey, message);
      return "01" + Buffer.from(sig).toString("hex");
    },
  };
}

test("buildResolveMessage matches Python build_resolve_message canonical format", () => {
  const msg = buildResolveMessage("deadbeef", "sender");
  assert.equal(Buffer.from(msg).toString("utf-8"), "resolve:deadbeef:sender");
});

test("buildCapApprovalMessage matches canonical format", () => {
  const msg = buildCapApprovalMessage("release", "deadbeef");
  assert.equal(Buffer.from(msg).toString("utf-8"), "release:deadbeef:cap_approval");
});

test("buildInsuranceClaimMessage matches canonical format", () => {
  const msg = buildInsuranceClaimMessage("escrow-1", "ab" + "cd".repeat(31), 5000);
  assert.equal(Buffer.from(msg).toString("utf-8"), `claim:escrow-1:${"ab" + "cd".repeat(31)}:5000`);
});

test("verifyEd25519Vote: valid signature over the exact canonical message verifies", async () => {
  const arbiter = await generateArbiterKeypair();
  const message = buildResolveMessage("service-hash-1", "sender-A");
  const sigHex = await arbiter.sign(message);
  const ok = await verifyEd25519Vote(arbiter.pubkeyHex, sigHex, message);
  assert.equal(ok, true);
});

test("verifyEd25519Vote: signature does not verify for a different escrow (no cross-escrow replay)", async () => {
  const arbiter = await generateArbiterKeypair();
  const messageA = buildResolveMessage("service-hash-1", "sender-A");
  const messageB = buildResolveMessage("service-hash-2", "sender-A");
  const sigHex = await arbiter.sign(messageA);
  assert.equal(await verifyEd25519Vote(arbiter.pubkeyHex, sigHex, messageA), true);
  assert.equal(await verifyEd25519Vote(arbiter.pubkeyHex, sigHex, messageB), false);
});

test("verifyEd25519Vote: signature does not verify for a flipped verdict", async () => {
  const arbiter = await generateArbiterKeypair();
  const forSender = buildResolveMessage("service-hash-1", "sender");
  const forReceiver = buildResolveMessage("service-hash-1", "receiver");
  const sigHex = await arbiter.sign(forSender);
  assert.equal(await verifyEd25519Vote(arbiter.pubkeyHex, sigHex, forReceiver), false);
});

test("verifyEd25519Vote: rejects non-ed25519-tagged pubkey without throwing", async () => {
  const message = buildResolveMessage("service-hash-1", "sender");
  const ok = await verifyEd25519Vote("02" + "ab".repeat(32), "01" + "cd".repeat(64), message);
  assert.equal(ok, false);
});

test("verifyEd25519Vote: rejects malformed hex without throwing", async () => {
  const message = buildResolveMessage("service-hash-1", "sender");
  assert.equal(await verifyEd25519Vote("not-hex", "also-not-hex", message), false);
  assert.equal(await verifyEd25519Vote("01" + "ab".repeat(31), "01" + "cd".repeat(64), message), false); // wrong pubkey length
});

test("countValidVotes: counts only valid, registered, deduplicated votes", async () => {
  const a1 = await generateArbiterKeypair();
  const a2 = await generateArbiterKeypair();
  const unregistered = await generateArbiterKeypair();
  const serviceHash = "svc-abc";
  const inFavorOf = "sender-x";
  const message = buildResolveMessage(serviceHash, inFavorOf);

  const sig1 = await a1.sign(message);
  const sig2 = await a2.sign(message);
  const sigUnregistered = await unregistered.sign(message);

  const registered = [a1.pubkeyHex, a2.pubkeyHex];

  // 3 submitted votes: a1, a2, and one from an unregistered arbiter -> only 2 count.
  const count = await countValidVotes(
    [a1.pubkeyHex, a2.pubkeyHex, unregistered.pubkeyHex],
    [sig1, sig2, sigUnregistered],
    registered,
    serviceHash,
    inFavorOf,
  );
  assert.equal(count, 2);

  // Duplicate submission of a1's vote should not double-count.
  const dupCount = await countValidVotes([a1.pubkeyHex, a1.pubkeyHex], [sig1, sig1], registered, serviceHash, inFavorOf);
  assert.equal(dupCount, 1);
});

test("countValidCapApprovalVotes: counts votes over the cap-approval message, not the resolve message", async () => {
  const a1 = await generateArbiterKeypair();
  const serviceHash = "svc-cap-1";
  const capMessage = buildCapApprovalMessage("release", serviceHash);
  const sig = await a1.sign(capMessage);

  const validCount = await countValidCapApprovalVotes([a1.pubkeyHex], [sig], [a1.pubkeyHex], "release", serviceHash);
  assert.equal(validCount, 1);

  // Same signature should NOT validate for reveal_swap (different canonical message).
  const wrongActionCount = await countValidCapApprovalVotes(
    [a1.pubkeyHex],
    [sig],
    [a1.pubkeyHex],
    "reveal_swap",
    serviceHash,
  );
  assert.equal(wrongActionCount, 0);
});

test("countValidInsuranceClaimVotes: counts votes over the insurance-claim message", async () => {
  const a1 = await generateArbiterKeypair();
  const escrowId = "escrow-42";
  const claimantAccountHash = "ab".repeat(32);
  const amount = 12345;
  const message = buildInsuranceClaimMessage(escrowId, claimantAccountHash, amount);
  const sig = await a1.sign(message);

  const count = await countValidInsuranceClaimVotes(
    [a1.pubkeyHex],
    [sig],
    [a1.pubkeyHex],
    escrowId,
    claimantAccountHash,
    amount,
  );
  assert.equal(count, 1);

  // A different amount must not validate against the same signature.
  const wrongAmountCount = await countValidInsuranceClaimVotes(
    [a1.pubkeyHex],
    [sig],
    [a1.pubkeyHex],
    escrowId,
    claimantAccountHash,
    amount + 1,
  );
  assert.equal(wrongAmountCount, 0);
});

test("interop: TypeScript verifier accepts a vote signed by the real Python sign_arbiter_vote helper", async () => {
  // Generate an Ed25519 PKCS8 PEM key with Python's cryptography lib (already
  // a dependency of the Python SDK/server), sign with the exact
  // sdk/arbiter_signing.py helper, and verify the (pubkey_hex, signature_hex)
  // pair with the TypeScript verifier -- proving cross-language wire
  // compatibility of the tag-prefixed-hex Ed25519 convention.
  const script = `
import sys, json, tempfile, os
sys.path.insert(0, ${JSON.stringify(repoRoot)})
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from sdk.arbiter_signing import sign_arbiter_vote

key = Ed25519PrivateKey.generate()
pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
fd, path = tempfile.mkstemp(suffix=".pem")
with os.fdopen(fd, "wb") as f:
    f.write(pem)
try:
    pubkey_hex, sig_hex = sign_arbiter_vote(path, "service-hash-py", "sender-py")
finally:
    os.remove(path)
print(json.dumps({"pubkey_hex": pubkey_hex, "sig_hex": sig_hex}))
`;
  let stdout: string;
  try {
    stdout = execFileSync("python3", ["-c", script], { cwd: repoRoot, encoding: "utf-8" });
  } catch (err) {
    // Environment without the repo's Python deps available -- skip rather
    // than fail the whole TS suite on an unrelated missing interpreter.
    console.warn("skipping Python interop test:", (err as Error).message);
    return;
  }
  const { pubkey_hex, sig_hex } = JSON.parse(stdout.trim());
  const message = buildResolveMessage("service-hash-py", "sender-py");
  const ok = await verifyEd25519Vote(pubkey_hex, sig_hex, message);
  assert.equal(ok, true);
});
