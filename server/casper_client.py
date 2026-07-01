"""Casper Network SDK wrapper for AgentEscrow402."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from server.config import Config
from server.models import EscrowRecord, EscrowStatus, ReputationRecord

logger = logging.getLogger(__name__)


class CasperClient:
    """Thin wrapper around the Casper JSON-RPC API.

    Supports NOWNodes as primary RPC provider with automatic fallback
    to the default node URL when NOWNodes is unavailable.
    """

    NOWNODES_URL = "https://casper.nownodes.io/rpc"

    def __init__(self, cfg: Config) -> None:
        self._node_url = cfg.casper_node_url
        self._chain = cfg.casper_chain_name
        self._contract_hash = cfg.contract_hash
        self._key_path = cfg.casper_private_key_path
        self._insurance_bps = cfg.insurance_fee_bps
        self._nownodes_key = cfg.nownodes_api_key
        self._http = httpx.AsyncClient(timeout=30.0)
        if self._nownodes_key:
            logger.info("NOWNodes RPC configured as primary provider")

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        # Try NOWNodes first if configured
        if self._nownodes_key:
            try:
                resp = await self._http.post(
                    self.NOWNODES_URL,
                    json=payload,
                    headers={"api-key": self._nownodes_key},
                )
                resp.raise_for_status()
                body = resp.json()
                if "error" not in body:
                    return body.get("result")
                logger.warning("NOWNodes RPC error, falling back: %s", body["error"])
            except Exception as exc:
                logger.warning("NOWNodes unavailable (%s), falling back to default node", exc)

        # Fallback to default node
        resp = await self._http.post(self._node_url + "/rpc", json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body.get("result")

    async def get_state_root_hash(self) -> str:
        result = await self._rpc("chain_get_state_root_hash")
        return result["state_root_hash"]

    async def query_contract_dict(self, dict_name: str, key: str) -> dict[str, Any] | None:
        try:
            srh = await self.get_state_root_hash()
            result = await self._rpc(
                "state_get_dictionary_item",
                {
                    "state_root_hash": srh,
                    "dictionary_identifier": {
                        "ContractNamedKey": {
                            "key": f"hash-{self._contract_hash}",
                            "dictionary_name": dict_name,
                            "dictionary_item_key": key,
                        }
                    },
                },
            )
            return result.get("stored_value", {}).get("CLValue", {})
        except Exception:
            logger.exception("Failed to query dict %s[%s]", dict_name, key)
            return None

    def _detect_key_type(self, private_key) -> str:
        """Detect whether the loaded key is ed25519 or secp256k1."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            if isinstance(private_key, Ed25519PrivateKey):
                return "ed25519"
        except ImportError:
            pass

        try:
            from cryptography.hazmat.primitives.asymmetric.ec import SECP256K1, EllipticCurvePrivateKey

            if isinstance(private_key, EllipticCurvePrivateKey):
                if isinstance(private_key.curve, SECP256K1):
                    return "secp256k1"
        except ImportError:
            pass

        return "unknown"

    async def deploy_transaction(
        self,
        entry_point: str,
        args: dict[str, Any],
        payment_amount: int = 3_000_000_000,
    ) -> str:
        """Build, sign, and submit a Transaction targeting the escrow contract.

        Returns the deploy/transaction hash on success.
        Supports both ed25519 and secp256k1 keys.
        """
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key path not configured — cannot sign deploys")

        session = {
            "StoredContractByHash": {
                "hash": self._contract_hash,
                "entry_point": entry_point,
                "args": self._encode_args(args),
            }
        }

        timestamp = self._iso_now()
        deploy = {
            "header": {
                "chain_name": self._chain,
                "timestamp": timestamp,
                "ttl": "30m",
                "gas_price": 1,
            },
            "payment": {
                "ModuleBytes": {
                    "module_bytes": "",
                    "args": [
                        [
                            "amount",
                            {
                                "cl_type": "U512",
                                "bytes": self._u512_bytes(payment_amount),
                                "parsed": str(payment_amount),
                            },
                        ]
                    ],
                }
            },
            "session": session,
        }

        deploy = await self._sign_deploy(deploy)

        result = await self._rpc("account_put_deploy", {"deploy": deploy})
        deploy_hash = result.get("deploy_hash", "")
        logger.info("Deploy submitted: %s (entry_point=%s)", deploy_hash, entry_point)
        return deploy_hash

    async def _sign_deploy(self, deploy: dict) -> dict:
        """Sign a deploy using the configured private key.

        Supports both ed25519 (01 prefix) and secp256k1 (02 prefix) keys.
        """
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        with open(self._key_path, "rb") as f:
            private_key = load_pem_private_key(f.read(), password=None)

        key_type = self._detect_key_type(private_key)

        # Compute body hash
        body_bytes = json.dumps(
            {"payment": deploy["payment"], "session": deploy["session"]},
            sort_keys=True,
        ).encode()
        body_hash = hashlib.blake2b(body_bytes, digest_size=32).hexdigest()

        if key_type == "ed25519":
            return self._sign_ed25519(deploy, private_key, body_hash)
        elif key_type == "secp256k1":
            return self._sign_secp256k1(deploy, private_key, body_hash)
        else:
            raise TypeError(f"Unsupported key type: {key_type}")

    def _sign_ed25519(self, deploy: dict, private_key, body_hash: str) -> dict:
        """Sign deploy with ed25519 key (Casper 01-prefix accounts)."""
        pub_bytes = private_key.public_key().public_bytes_raw()
        deploy["header"]["account"] = "01" + pub_bytes.hex()
        deploy["header"]["body_hash"] = body_hash

        header_bytes = json.dumps(deploy["header"], sort_keys=True).encode()
        header_hash = hashlib.blake2b(header_bytes, digest_size=32).digest()
        signature = private_key.sign(header_hash)
        deploy["hash"] = header_hash.hex()
        deploy["approvals"] = [
            {
                "signer": deploy["header"]["account"],
                "signature": "01" + signature.hex(),
            }
        ]
        return deploy

    def _sign_secp256k1(self, deploy: dict, private_key, body_hash: str) -> dict:
        """Sign deploy with secp256k1 key (Casper 02-prefix accounts)."""
        from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        # Get compressed public key (33 bytes)
        pub_bytes = private_key.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
        deploy["header"]["account"] = "02" + pub_bytes.hex()
        deploy["header"]["body_hash"] = body_hash

        # Hash header
        header_bytes = json.dumps(deploy["header"], sort_keys=True).encode()
        header_hash = hashlib.blake2b(header_bytes, digest_size=32).digest()

        # Sign with ECDSA-SHA256 (Casper secp256k1 convention)
        der_sig = private_key.sign(header_hash, ECDSA(SHA256()))
        r, s = decode_dss_signature(der_sig)

        # Casper expects raw r||s (64 bytes)
        r_bytes = r.to_bytes(32, byteorder="big")
        s_bytes = s.to_bytes(32, byteorder="big")
        raw_sig = r_bytes + s_bytes

        deploy["hash"] = header_hash.hex()
        deploy["approvals"] = [
            {
                "signer": deploy["header"]["account"],
                "signature": "02" + raw_sig.hex(),
            }
        ]
        return deploy

    async def create_escrow(self, sender: str, receiver: str, amount: int, service_hash: str, ttl: int) -> str:
        return await self.deploy_transaction(
            "create_escrow",
            {
                "receiver": ("String", receiver),
                "amount": ("U512", str(amount)),
                "service_hash": ("String", service_hash),
                "ttl": ("U64", str(ttl)),
            },
        )

    async def release(self, service_hash: str) -> str:
        return await self.deploy_transaction(
            "release",
            {"service_hash": ("String", service_hash)},
        )

    async def refund(self, service_hash: str) -> str:
        return await self.deploy_transaction(
            "refund",
            {"service_hash": ("String", service_hash)},
        )

    async def dispute(self, service_hash: str) -> str:
        return await self.deploy_transaction(
            "dispute",
            {"service_hash": ("String", service_hash)},
        )

    async def get_escrow(self, service_hash: str) -> EscrowRecord | None:
        raw = await self.query_contract_dict("escrows", service_hash)
        if raw is None:
            return None
        parsed = raw.get("parsed")
        if not parsed:
            return None
        status_map = [
            "pending",
            "released",
            "refunded",
            "expired",
            "disputed",
            "resolved",
        ]
        return EscrowRecord(
            sender=parsed[0],
            receiver=parsed[1],
            amount=int(parsed[2]),
            service_hash=parsed[3],
            status=EscrowStatus(status_map[parsed[4]]),
            created_at=parsed[5],
            ttl=parsed[6],
        )

    async def get_reputation(self, agent: str) -> ReputationRecord:
        raw = await self.query_contract_dict("reputation", agent)
        if raw is None:
            return ReputationRecord(agent=agent)
        parsed = raw.get("parsed")
        if not parsed:
            return ReputationRecord(agent=agent)
        return ReputationRecord(
            agent=agent,
            completed=parsed[0],
            disputed=parsed[1],
            slashed=parsed[2],
            last_active=parsed[3],
            score=parsed[4],
        )

    async def close(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _encode_args(args: dict[str, tuple[str, str]]) -> list:
        encoded = []
        for name, (cl_type, value) in args.items():
            encoded.append([name, {"cl_type": cl_type, "bytes": "", "parsed": value}])
        return encoded

    @staticmethod
    def _iso_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    @staticmethod
    def _u512_bytes(amount: int) -> str:
        """Encode U512 as Casper CLValue bytes (little-endian with length prefix)."""
        if amount == 0:
            return "0100"
        byte_list = []
        n = amount
        while n > 0:
            byte_list.append(n & 0xFF)
            n >>= 8
        length_byte = format(len(byte_list), "02x")
        le_hex = "".join(format(b, "02x") for b in byte_list)
        return length_byte + le_hex
