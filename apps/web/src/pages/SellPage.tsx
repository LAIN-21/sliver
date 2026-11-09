import PageHeader, { EmptyState } from "../components/PageHeader";

export default function SellPage() {
  return (
    <>
      <PageHeader title="Sell data">
        Upload a dataset, see how Sliver inspects and values it, and publish it as priced slices.
      </PageHeader>
      <EmptyState title="Seller workspace">Seller sign-in and uploads are not available yet.</EmptyState>
    </>
  );
}
