import { Route, Routes } from "react-router";

import Layout from "./components/Layout";
import ActivityPage from "./pages/ActivityPage";
import MarketplacePage from "./pages/MarketplacePage";
import NotFoundPage from "./pages/NotFoundPage";
import PurchasePage from "./pages/PurchasePage";
import ResourcePage from "./pages/ResourcePage";
import SellPage from "./pages/SellPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<MarketplacePage />} />
        <Route path="resources/:id" element={<ResourcePage />} />
        <Route path="sell" element={<SellPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="purchases/:id" element={<PurchasePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
