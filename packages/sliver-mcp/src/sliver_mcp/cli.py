"""`sliver-mcp`: run the stdio MCP server; `sliver-mcp wallet init|show` manages the Testnet wallet."""

import argparse
import logging
import os
import sys

from .config import Config
from .store import Store
from .wallet import SEED_ENV, WALLET_FILE, WalletMissing, balance_drops, init_wallet, load_wallet


def wallet_command(config: Config, action: str) -> int:
    store = Store(config.home)
    if action == "init":
        wallet, created = init_wallet(store, config.rpc_url)
        where = store.home / WALLET_FILE
        verb = "Created and faucet-funded" if created else "Using existing"
        print(f"{verb} XRPL Testnet wallet {wallet.address}")
        print(f"Seed stored in {where} (mode 0600). It never leaves this machine.")
    else:
        try:
            wallet = load_wallet(store)
        except WalletMissing as error:
            print(error, file=sys.stderr)
            return 1
        source = f"from {SEED_ENV}" if os.environ.get(SEED_ENV) else "from the wallet file"
        print(f"Address: {wallet.address} ({source})")
    drops = balance_drops(wallet.address, config.rpc_url)
    print(f"Balance: {'unknown' if drops is None else f'{drops / 1_000_000} XRP'} on XRPL Testnet")
    print(f"Explorer: https://testnet.xrpl.org/accounts/{wallet.address}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sliver-mcp", description="Sliver buyer MCP server (stdio).")
    commands = parser.add_subparsers(dest="command")
    wallet = commands.add_parser("wallet", help="Manage the XRPL Testnet buyer wallet in ~/.sliver/")
    wallet.add_argument("action", choices=["init", "show"])
    args = parser.parse_args(argv)
    config = Config.from_env()
    if args.command == "wallet":
        sys.exit(wallet_command(config, args.action))
    from .server import build_server

    logging.getLogger("httpx").setLevel(logging.WARNING)  # keep request lines out of the client's logs
    build_server(config).run("stdio")
