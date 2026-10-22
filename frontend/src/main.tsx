import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Compass } from "lucide-react";
import "./ui";
import "./app.css";
import "./trace.css";
import { Layout } from "./components/Layout";
import { DocumentsPage } from "./pages/DocumentsPage";
import { DocumentViewerPage } from "./pages/DocumentViewerPage";
import { OverviewPage } from "./pages/OverviewPage";
import { LinePage } from "./pages/LinePage";
import { RefPage } from "./pages/RefPage";
import { ReturnPage } from "./pages/ReturnPage";
import { ReviewPage } from "./pages/ReviewPage";
import { ActivityPage } from "./pages/ActivityPage";
import "./review.css";
import "./health.css";
import { AreaPage } from "./pages/AreaPage";
import { FindingsPage } from "./pages/FindingsPage";
import { VariancePage } from "./pages/VariancePage";
import { ValuesPage } from "./pages/ValuesPage";
import { AdjustmentsPage } from "./pages/AdjustmentsPage";
import { ComparePage } from "./pages/ComparePage";
import { WhatIfPage } from "./pages/WhatIfPage";
import { WhatsNewPage } from "./pages/WhatsNewPage";
import "./changes.css";
import "./lifecycle.css";
import "./polish.css";
import { StatusPage } from "./pages/StatusPage";
import { BudgetPage } from "./pages/BudgetPage";
import { FilingPage } from "./pages/FilingPage";
import { AmendPage } from "./pages/AmendPage";
import { NoticesPage } from "./pages/NoticesPage";
import { CarryForwardPage } from "./pages/CarryForwardPage";
import { SessionProvider } from "./session";
import { ButtonLink, EmptyState } from "./ui";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

function NotFound() {
  return (
    <div className="page">
      <EmptyState icon={<Compass />} title="This screen doesn't exist"
        description="The link may be from a later milestone or mistyped."
        action={<ButtonLink to="/" size="sm">Back to overview</ButtonLink>} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<OverviewPage />} />
              <Route path="return" element={<ReturnPage />} />
              <Route path="lines/:key" element={<LinePage />} />
              <Route path="documents" element={<DocumentsPage />} />
              <Route path="documents/:docId" element={<DocumentViewerPage />} />
              <Route path="values" element={<ValuesPage />} />
              <Route path="ref" element={<RefPage />} />
              <Route path="review" element={<ReviewPage />} />
              <Route path="areas/:areaId" element={<AreaPage />} />
              <Route path="findings" element={<FindingsPage />} />
              <Route path="variance" element={<VariancePage />} />
              <Route path="activity" element={<ActivityPage />} />
              <Route path="adjustments" element={<AdjustmentsPage />} />
              <Route path="compare" element={<ComparePage />} />
              <Route path="whatif" element={<WhatIfPage />} />
              <Route path="whats-new" element={<WhatsNewPage />} />
              <Route path="status" element={<StatusPage />} />
              <Route path="budget" element={<BudgetPage />} />
              <Route path="filing" element={<FilingPage />} />
              <Route path="amend" element={<AmendPage />} />
              <Route path="notices" element={<NoticesPage />} />
              <Route path="carryforward" element={<CarryForwardPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </SessionProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
