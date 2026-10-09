import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Dialog, Notice, Button, DataTable, Field } from "./ui";
describe("shared accessible UI primitives", () => {
  it("shows a named dialog and forwards cancellation to the owner", () => {
    const onClose = vi.fn();
    render(
      <Dialog open title="New target" onClose={onClose}>
        <input aria-label="Name" />
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog", { name: "New target" });
    fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
    expect(onClose).toHaveBeenCalledOnce();
  });
  it("uses truthful disabled actions and announced errors", () => {
    render(
      <>
        <Button disabled>Run live</Button>
        <Notice tone="danger">API unavailable</Notice>
        <DataTable label="Evidence">
          <table>
            <tbody>
              <tr>
                <td>Empty</td>
              </tr>
            </tbody>
          </table>
        </DataTable>
      </>,
    );
    expect(screen.getByRole("button", { name: "Run live" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("API unavailable");
    expect(screen.getByRole("region", { name: "Evidence" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  });
  it("keeps a field hint separate from its concise accessible name", () => {
    render(
      <Field label="Target name" hint="A local draft, not approval">
        <input />
      </Field>,
    );
    expect(
      screen.getByRole("textbox", { name: "Target name" }),
    ).toHaveAccessibleDescription("A local draft, not approval");
  });
});
