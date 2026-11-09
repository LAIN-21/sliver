"""Network boundaries: the x402 facilitator and the XRP Ledger. Tests inject stubs."""

from typing import Any, Protocol

from x402_xrpl.facilitator import FacilitatorClient, FacilitatorClientOptions
from x402_xrpl.types import PaymentRequirements, PaymentVerifyResponse, SettlementResponse
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import Tx


class Facilitator(Protocol):
    def verify(self, header: str, requirements: PaymentRequirements) -> PaymentVerifyResponse: ...
    def settle(self, header: str, requirements: PaymentRequirements) -> SettlementResponse: ...


class Ledger(Protocol):
    def transaction(self, tx_hash: str) -> dict[str, Any] | None: ...


class HttpFacilitator:
    """t54's XRPL facilitator (or any x402 v2 facilitator) over HTTP."""

    def __init__(self, base_url: str, verify_timeout: float = 15.0, settle_timeout: float = 75.0):
        # Verify runs while the invoice row is locked, so keep it short; settle waits for the ledger.
        self.verifier = FacilitatorClient(
            FacilitatorClientOptions(base_url=base_url, timeout_seconds=verify_timeout)
        )
        self.settler = FacilitatorClient(
            FacilitatorClientOptions(base_url=base_url, timeout_seconds=settle_timeout)
        )

    def verify(self, header: str, requirements: PaymentRequirements) -> PaymentVerifyResponse:
        return self.verifier.verify(payment_header=header, payment_requirements=requirements)

    def settle(self, header: str, requirements: PaymentRequirements) -> SettlementResponse:
        return self.settler.settle(payment_header=header, payment_requirements=requirements)


class XrplLedger:
    def __init__(self, rpc_url: str):
        self.client = JsonRpcClient(rpc_url)

    def transaction(self, tx_hash: str) -> dict[str, Any] | None:
        response = self.client.request(Tx(transaction=tx_hash))
        return response.result if response.is_successful() else None
