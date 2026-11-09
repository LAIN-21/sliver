import PageHeader, { EmptyState } from "../components/PageHeader";

export default function ActivityPage() {
  return (
    <>
      <PageHeader title="Activity">
        Every agent purchase, from the HTTP 402 challenge to settlement on the XRP Ledger.
      </PageHeader>
      <EmptyState title="No purchases yet">Purchases will appear here as they happen.</EmptyState>
    </>
  );
}
