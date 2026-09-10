import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { AuditPage } from "./pages/AuditPage";
import { ChatPage } from "./pages/ChatPage";
import { ComponentDetailPage } from "./pages/ComponentDetailPage";
import { ComponentsPage } from "./pages/ComponentsPage";
import { DependenciesPage } from "./pages/DependenciesPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { FindingsPage } from "./pages/FindingsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RevisionsPage } from "./pages/RevisionsPage";
import { StandardsPage } from "./pages/StandardsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/revisions" element={<RevisionsPage />} />
        <Route path="/components" element={<ComponentsPage />} />
        <Route path="/components/:id" element={<ComponentDetailPage />} />
        <Route path="/dependencies" element={<DependenciesPage />} />
        <Route path="/standards" element={<StandardsPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
      </Route>
    </Routes>
  );
}
