"""Create faucet-funded XRPL Testnet wallets for the demo sellers and buyer: `make wallets`.

Seeds are appended to the repository `.env` (gitignored, testnet only) and reused on later
runs. Sellers' classic addresses are written to their accounts so they can receive x402
payments. The buyer seed is only for local smoke tests and the buyer MCP; the API never reads it.
"""

import sys
import tomllib
from pathlib import Path

from sqlalchemy import select
from xrpl.account import get_balance
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet

from ..config import get_settings
from ..db import make_engine, make_session_factory
from ..models import User

BUYER_VAR = "SLIVER_DEMO_BUYER_SEED"


def seller_var(key: str) -> str:
    return f"SLIVER_WALLET_{key.upper()}_SEED"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def main() -> None:
    env_path, manifest_path = Path(sys.argv[1]), Path(sys.argv[2])
    settings = get_settings()
    client = JsonRpcClient(settings.xrpl_rpc_url)
    env = read_env(env_path)
    sellers = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["sellers"]

    created = []
    for name in [seller_var(seller["key"]) for seller in sellers] + [BUYER_VAR]:
        if not env.get(name):
            wallet = generate_faucet_wallet(client)
            env[name] = wallet.seed
            created.append(f"{name}={wallet.seed}")
    if created:
        with env_path.open("a", encoding="utf-8") as handle:
            handle.write("\n# XRPL Testnet wallets created by `make wallets` (testnet only, never mainnet)\n")
            handle.write("\n".join(created) + "\n")

    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as db:
            for seller in sellers:
                address = Wallet.from_seed(env[seller_var(seller["key"])]).address
                user = db.scalar(select(User).where(User.email == seller["email"]))
                if user is None:
                    print(f"{seller['email']}: not found; run `make seed` first, then `make wallets` again")
                    continue
                user.xrpl_address = address
            db.commit()
    finally:
        engine.dispose()

    for name in [seller_var(seller["key"]) for seller in sellers] + [BUYER_VAR]:
        address = Wallet.from_seed(env[name]).address
        balance = int(get_balance(address, client)) / 1_000_000
        print(f"{name.removesuffix('_SEED')}: {address} ({balance:,.2f} XRP)")
    print(f"created {len(created)} new wallet(s); seeds are in {env_path.name}")


if __name__ == "__main__":
    main()
