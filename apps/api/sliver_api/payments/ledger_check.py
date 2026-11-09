"""Independent post-settlement check of the ledger result. Sliver does not take the
facilitator's word for a settlement: the transaction must be validated on the XRP Ledger and
deliver exactly what the invoice asked for, to the seller, bound to the invoice."""

from typing import Any

from .x402 import invoice_id_field

TF_PARTIAL_PAYMENT = 0x00020000


def settlement_problem(
    result: dict[str, Any] | None, *, pay_to: str, amount_drops: str, invoice_id: str
) -> str | None:
    """Return None when the ledger result proves the payment, otherwise a short reason."""
    if not result:
        return "transaction_not_found"
    if result.get("validated") is not True:
        return "not_validated"
    tx = result.get("tx_json") or result  # API v2 nests fields under tx_json
    meta = result.get("meta") or {}
    if tx.get("TransactionType") != "Payment":
        return "not_a_payment"
    if meta.get("TransactionResult") != "tesSUCCESS":
        return f"failed_on_ledger:{meta.get('TransactionResult')}"
    flags = tx.get("Flags", 0)
    if type(flags) is not int or flags & TF_PARTIAL_PAYMENT:
        return "partial_payment"
    if tx.get("Destination") != pay_to:
        return "wrong_destination"
    delivered = meta.get("delivered_amount")
    if not isinstance(delivered, str) or delivered != amount_drops:
        return "wrong_amount"
    if str(tx.get("InvoiceID", "")).upper() != invoice_id_field(invoice_id):
        return "invoice_binding_mismatch"
    return None
