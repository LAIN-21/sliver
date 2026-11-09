"""Platform fee and seller payouts (ADR 0005): rate, Sliver's fee, seller's net, payout time.

Existing delivered payments are not backfilled: they were paid straight to the seller under
ADR 0004, so Sliver never held the money. Their fee columns stay NULL ("not collected by Sliver"):
no fee, nothing owed to the seller.

Revision ID: 0008_platform_fee
Revises: 0007_valuation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_platform_fee"
down_revision: str | None = "0007_valuation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("platform_fee_bps", sa.Integer()))
    op.add_column("payments", sa.Column("platform_fee_minor", sa.Integer()))
    op.add_column("payments", sa.Column("seller_net_minor", sa.Integer()))
    op.add_column("payments", sa.Column("platform_fee_drops", sa.BigInteger()))
    op.add_column("payments", sa.Column("seller_net_drops", sa.BigInteger()))
    op.add_column("payments", sa.Column("seller_paid_out_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "payments_platform_fee",
        "payments",
        "platform_fee_bps IS NULL"
        " OR (platform_fee_bps BETWEEN 0 AND 5000 AND status = 'delivered'"
        " AND platform_fee_minor >= 0 AND seller_net_minor >= 0"
        " AND platform_fee_minor + seller_net_minor = price_minor)",
    )
    op.create_check_constraint(
        "payments_platform_fee_drops",
        "payments",
        "(platform_fee_drops IS NULL) = (seller_net_drops IS NULL)"
        " AND (platform_fee_drops IS NULL OR platform_fee_bps IS NOT NULL)",
    )
    op.create_check_constraint(
        "payments_seller_paid_out", "payments", "seller_paid_out_at IS NULL OR platform_fee_bps IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint("payments_seller_paid_out", "payments", type_="check")
    op.drop_constraint("payments_platform_fee_drops", "payments", type_="check")
    op.drop_constraint("payments_platform_fee", "payments", type_="check")
    op.drop_column("payments", "seller_paid_out_at")
    op.drop_column("payments", "seller_net_drops")
    op.drop_column("payments", "platform_fee_drops")
    op.drop_column("payments", "seller_net_minor")
    op.drop_column("payments", "platform_fee_minor")
    op.drop_column("payments", "platform_fee_bps")
