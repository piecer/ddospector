import { createRoot } from "react-dom/client";
import { useState } from "react";
import { WorkspaceShell } from "../../src/components/WorkspaceShell";
import { EvidencePage } from "../../src/pages/operations/EvidencePage";
import { workspaceFixture } from "../../src/test/fixtures";
import type { Locale } from "../../src/lib/contracts";
import "../../src/styles.css";
function Fixture() {
  const [locale, setLocale] = useState<Locale>("en");
  document.documentElement.lang = locale;
  return (
    <WorkspaceShell
      locale={locale}
      setLocale={setLocale}
      route="evidence"
      navigate={() => {}}
      connection="ready"
    >
      <EvidencePage
        locale={locale}
        data={workspaceFixture()}
        navigate={() => {}}
        refresh={async () => {}}
      />
    </WorkspaceShell>
  );
}
// Only transport is controlled; shipped shell/page/controller/codec/styles are unchanged.
const root = createRoot(document.getElementById("root")!);
root.render(<Fixture />);
const unmount = document.createElement("button");
unmount.textContent = "Unmount fixture";
unmount.onclick = () => root.unmount();
document.body.append(unmount);
