import { createRoot } from "react-dom/client";
import { RunsWorkspace } from "../../src/pages/runs/RunsWorkspace";
import { workspaceFixture } from "../../src/test/fixtures";
import "../../src/styles.css";
const locale = new URL(location.href).searchParams.get("locale") === "ko" ? "ko" : "en";
document.documentElement.lang = locale;
// Shipped component/controller/transport/styles. Only HTTP is controlled by Playwright.
const root = createRoot(document.getElementById("root")!);
const unmount = document.createElement("button");
unmount.textContent = "Unmount fixture";
unmount.onclick = () => root.unmount();
document.body.append(unmount);
root.render(
  <RunsWorkspace data={workspaceFixture()} locale={locale} navigate={() => {}} refresh={async () => {}} />,
);
