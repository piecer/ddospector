import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { Application } from "./App";
import { pages } from "./pageRegistry";
const root = document.getElementById("root");
if (!root) throw new Error("Application mount point is missing.");
createRoot(root).render(
  <StrictMode>
    <Application pages={pages} />
  </StrictMode>,
);
