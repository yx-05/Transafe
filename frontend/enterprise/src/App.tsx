import { Navigate, Route, Routes } from "react-router-dom";
import Shell from "./components/Shell";
import OverviewPage from "./pages/OverviewPage";
import CaseDetailPage from "./pages/CaseDetailPage";
import GraphPage from "./pages/GraphPage";
import ValidationPage from "./pages/ValidationPage";
import RegistryPage from "./pages/RegistryPage";
import EvalPage from "./pages/EvalPage";
import McpLogPage from "./pages/McpLogPage";

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<OverviewPage />} />
        <Route path="cases" element={<CaseDetailPage />} />
        <Route path="cases/:caseId" element={<CaseDetailPage />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="validation" element={<ValidationPage />} />
        <Route path="validation/:campaignId" element={<ValidationPage />} />
        <Route path="registry" element={<RegistryPage />} />
        <Route path="eval" element={<EvalPage />} />
        <Route path="mcp" element={<McpLogPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default App;
