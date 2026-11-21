import { lazy, StrictMode, Suspense, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { CustomerApp } from "./customer/CustomerApp";
import "./index.css";
import { navigate, useLocation } from "./lib/router";
import { PRODUCT } from "./ui/Brand";

const AnalystApp = lazy(() => import("./analyst/AnalystApp").then((m) => ({ default: m.AnalystApp })));

function App() {
  const { path } = useLocation();
  const legacySoc = path === "/soc" || path.startsWith("/soc/");
  const isAnalyst = path === "/analyst" || path === "/analyst/";
  useEffect(() => {
    if (legacySoc) {
      navigate("/analyst", true);
      return;
    }
    document.title = isAnalyst ? `Analyst workspace · ${PRODUCT}` : PRODUCT;
  }, [legacySoc, isAnalyst]);
  if (legacySoc) return null;
  if (isAnalyst) return <Suspense fallback={<p className="mx-auto max-w-6xl px-4 py-8 text-muted" role="status">Loading analyst workspace…</p>}>
    <AnalystApp />
  </Suspense>;
  return <CustomerApp path={path} />;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
