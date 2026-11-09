"""Buyer-side configuration, read from the environment of the machine running the MCP."""

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sliver_x402 import DEFAULT_MAX_FEE_DROPS, TESTNET_RPC_URLS, check_rpc_url

# Sliver's disclosed demo rate (see docs/ARCHITECTURE.md): 1 USD = 400,000 drops (0.4 XRP).
DEFAULT_DROPS_PER_USD = 400_000


def usd_to_minor(value: object, name: str) -> int:
    """A USD amount to whole cents, rounded down so a limit never grows."""
    try:
        cents = int(Decimal(str(value)) * 100)
    except (InvalidOperation, ValueError, OverflowError) as error:
        raise ValueError(f"{name} must be a USD amount such as 5 or 2.50") from error
    if cents < 0:
        raise ValueError(f"{name} must not be negative")
    return cents


def drops_for(price_minor: int, drops_per_usd: int) -> int:
    """USD cents to XRP drops, rounded up: the same conversion the Sliver API uses."""
    return -(-price_minor * drops_per_usd // 100)


@dataclass(frozen=True)
class Config:
    api_url: str = "http://127.0.0.1:8000"
    home: Path = Path.home() / ".sliver"
    output_dir: Path = Path.home() / ".sliver" / "data"
    rpc_url: str = TESTNET_RPC_URLS[0]
    drops_per_usd: int = DEFAULT_DROPS_PER_USD
    max_purchase_minor: int = 500
    daily_cap_minor: int = 2_000
    max_fee_drops: int = DEFAULT_MAX_FEE_DROPS

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        home = Path(env.get("SLIVER_HOME") or Path.home() / ".sliver").expanduser()
        return cls(
            api_url=(env.get("SLIVER_API_URL") or cls.api_url).rstrip("/"),
            home=home,
            output_dir=Path(env.get("SLIVER_OUTPUT_DIR") or home / "data").expanduser(),
            rpc_url=check_rpc_url(env.get("SLIVER_XRPL_RPC_URL") or cls.rpc_url),
            drops_per_usd=int(env.get("SLIVER_DROPS_PER_USD") or DEFAULT_DROPS_PER_USD),
            max_purchase_minor=usd_to_minor(
                env.get("SLIVER_MAX_PURCHASE_USD", "5"), "SLIVER_MAX_PURCHASE_USD"
            ),
            daily_cap_minor=usd_to_minor(env.get("SLIVER_DAILY_CAP_USD", "20"), "SLIVER_DAILY_CAP_USD"),
            max_fee_drops=int(env.get("SLIVER_MAX_FEE_DROPS") or DEFAULT_MAX_FEE_DROPS),
        )
