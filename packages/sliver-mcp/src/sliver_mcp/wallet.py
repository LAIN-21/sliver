"""The buyer's XRPL Testnet wallet. The seed is read locally and never leaves this machine:
it is not returned by any tool, logged, or sent to Sliver."""

import os

from xrpl.account import get_balance
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet

from .store import Store

WALLET_FILE = "wallet.json"
SEED_ENV = "SLIVER_WALLET_SEED"


class WalletMissing(RuntimeError):
    pass


def load_wallet(store: Store, env: dict[str, str] | None = None) -> Wallet:
    """`SLIVER_WALLET_SEED` if set, otherwise `~/.sliver/wallet.json`."""
    seed = (os.environ if env is None else env).get(SEED_ENV)
    if not seed:
        path = store.home / WALLET_FILE
        if not path.exists():
            raise WalletMissing(
                "No buyer wallet. Ask your human to run `sliver-mcp wallet init` (XRPL Testnet only)."
            )
        if path.stat().st_mode & 0o077:
            raise WalletMissing(f"{path} must be readable only by its owner (chmod 600).")
        seed = store.read_json(WALLET_FILE, {}).get("seed")
    if not seed:
        raise WalletMissing("The buyer wallet has no seed.")
    return Wallet.from_seed(seed)


def init_wallet(store: Store, rpc_url: str, *, fund: bool = True) -> tuple[Wallet, bool]:
    """Create (and faucet-fund) a Testnet wallet unless one exists. Returns (wallet, created)."""
    path = store.home / WALLET_FILE
    if path.exists():
        return load_wallet(store, env={}), False
    wallet = generate_faucet_wallet(JsonRpcClient(rpc_url)) if fund else Wallet.create()
    store.write_json(WALLET_FILE, {"network": "xrpl:1", "address": wallet.address, "seed": wallet.seed})
    return wallet, True


def balance_drops(address: str, rpc_url: str) -> int | None:
    """Balance in drops, or None when it cannot be read (account not funded yet, or RPC unreachable)."""
    try:
        return int(get_balance(address, JsonRpcClient(rpc_url)))
    except Exception:
        return None
