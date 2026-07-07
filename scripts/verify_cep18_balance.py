import asyncio, sys
sys.path.insert(0, "/work/temp/projects/AgentEscrow402")
from server.config import Config
from server.casper_client import CasperClient

async def main():
    cfg = Config.from_env()
    client = CasperClient(cfg)
    contract_hash = "761664c7e3070e478fe1a172c106d57ddab550409f6dd7219a6f760edfb7bb00"
    installer_hex = "74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8"
    r = await client.query_contract_dict("balances", installer_hex, contract_hash=contract_hash)
    print("balance raw:", r)

asyncio.run(main())
