import { Link } from "react-router";

import PageHeader from "../components/PageHeader";

export default function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found">This page does not exist.</PageHeader>
      <Link to="/" className="font-medium text-brand hover:underline">
        Back to the marketplace
      </Link>
    </>
  );
}
