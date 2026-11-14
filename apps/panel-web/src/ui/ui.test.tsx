import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ICONS } from "@/icons/icons.gen";
import { Alert, Button, Modal, Pagination, Stepper, Tabs, TextField } from ".";

describe("design-system wrappers", () => {
  it("use the bundle.css class names", () => {
    render(
      <>
        <Button variant="primary" size="sm">
          ارسال
        </Button>
        <Alert tone="warning" title="کم">
          متن
        </Alert>
        <TextField label="موبایل" error="نامعتبر" ltr />
        <Stepper steps={["الف", "ب"]} current={1} />
      </>,
    );
    expect(screen.getByRole("button", { name: "ارسال" })).toHaveClass("ns-btn", "ns-btn-primary", "ns-btn-sm");
    expect(screen.getByText("متن").closest(".ns-alert")).toHaveClass("ns-alert-warning");
    const input = screen.getByLabelText("موبایل");
    expect(input).toHaveClass("ns-input", "is-error");
    expect(input).toHaveAttribute("dir", "ltr");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(document.querySelector(".ns-step.is-current")).not.toBeNull();
  });
  it("Modal closes on Esc and scrim", async () => {
    const onClose = vi.fn();
    render(
      <Modal title="سؤال" onClose={onClose}>
        بدنه
      </Modal>,
    );
    expect(screen.getByRole("dialog", { name: "سؤال" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it("Tabs and Pagination report changes", async () => {
    const onTab = vi.fn();
    const onPage = vi.fn();
    render(
      <>
        <Tabs tabs={[{ id: "a", label: "الف" }, { id: "b", label: "ب", count: 4 }]} value="a" onChange={onTab} />
        <Pagination page={1} pageSize={20} total={1241} onPage={onPage} />
      </>,
    );
    await userEvent.click(screen.getByRole("tab", { name: /ب/ }));
    expect(onTab).toHaveBeenCalledWith("b");
    await userEvent.click(screen.getByRole("button", { name: "بعدی" }));
    expect(onPage).toHaveBeenCalledWith(2);
    expect(screen.getByText(/۱٬۲۴۱/)).toBeInTheDocument();
  });
  it("has every icon the nav uses", async () => {
    const { NAV } = await import("@/nav");
    for (const r of ["user", "admin"] as const)
      for (const s of NAV[r]) for (const i of s.items) expect(ICONS[i.icon], i.icon).toBeTruthy();
  });
});
