import PageHeader, { EmptyState } from "../components/PageHeader";

export default function MarketplacePage() {
  return (
    <>
      <PageHeader title="Marketplace">
        Reviewed data Resources that external agents can discover and buy per slice. Listings show
        metadata only; protected data is delivered after payment.
      </PageHeader>
      <EmptyState title="No published Resources yet">
        Seed the demo catalog or publish a dataset from the seller workspace to see listings here.
      </EmptyState>
    </>
  );
}
