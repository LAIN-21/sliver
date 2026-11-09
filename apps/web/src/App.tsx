import { Route, Routes } from "react-router";

import Layout from "./components/Layout";
import ActivityPage from "./pages/ActivityPage";
import DatasetPage from "./pages/DatasetPage";
import MarketplacePage from "./pages/MarketplacePage";
import NotFoundPage from "./pages/NotFoundPage";
import PurchasePage from "./pages/PurchasePage";
import ResourcePage from "./pages/ResourcePage";
import SellerLoginPage from "./pages/SellerLoginPage";
import SellPage from "./pages/SellPage";
import UploadPage from "./pages/UploadPage";
import { SessionProvider } from "./session";

export default function App() {
  return (
    <SessionProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<MarketplacePage />} />
          <Route path="resources/:id" element={<ResourcePage />} />
          <Route path="sell" element={<SellPage />} />
          <Route path="sell/login" element={<SellerLoginPage />} />
          <Route path="sell/upload" element={<UploadPage />} />
          <Route path="sell/datasets/:id" element={<DatasetPage />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="purchases/:id" element={<PurchasePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </SessionProvider>
  );
}
