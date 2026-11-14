import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import RootLayout from "@/app/layout";
import { App } from "@/App";
import { ROUTES } from "@/routes";
import { Shell } from "./Shell";

describe("root layout", () => {
  it("is RTL Persian", () => {
    const html = renderToStaticMarkup(<RootLayout>x</RootLayout>);
    expect(html).toMatch(/^<html[^>]*lang="fa"/);
    expect(html).toMatch(/dir="rtl"/);
  });
});

describe("Shell", () => {
  it("renders the user nav, credit pill and children", () => {
    render(
      <Shell role="user" route="u-send">
        <p>محتوا</p>
      </Shell>,
    );
    const nav = screen.getByRole("navigation", { name: "منوی اصلی" });
    expect(within(nav).getAllByRole("link").length).toBeGreaterThanOrEqual(22);
    expect(within(nav).getByRole("link", { name: /ارسال سریع/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("محتوا")).toBeInTheDocument();
    expect(screen.getByLabelText("اعتبار حساب")).toBeInTheDocument();
  });
  it("renders the admin nav without credit pill", () => {
    render(
      <Shell role="admin" route="a-kyc">
        <p>x</p>
      </Shell>,
    );
    expect(screen.getByRole("link", { name: /احراز هویت/ })).toHaveAttribute("href", "#a-kyc");
    expect(screen.queryByLabelText("اعتبار حساب")).toBeNull();
  });
  it("toggles the theme on <html> and persists it", async () => {
    render(
      <Shell role="user" route="u-dashboard">
        <p>x</p>
      </Shell>,
    );
    await userEvent.click(screen.getByRole("button", { name: "تغییر تم" }));
    const first = document.documentElement.getAttribute("data-theme");
    expect(["light", "dark"]).toContain(first);
    expect(screen.getByRole("button", { name: "تغییر تم" })).toHaveAttribute("aria-pressed", String(first === "dark"));
    expect(window.localStorage.getItem("pk_theme")).toBe(first);
    await userEvent.click(screen.getByRole("button", { name: "تغییر تم" }));
    expect(document.documentElement.getAttribute("data-theme")).not.toBe(first);
  });
  it("opens and closes the mobile drawer", async () => {
    const { container } = render(
      <Shell role="user" route="u-dashboard">
        <p>x</p>
      </Shell>,
    );
    const app = container.querySelector(".app");
    expect(app).not.toHaveClass("nav-open");
    await userEvent.click(screen.getByRole("button", { name: "منو" }));
    expect(app).toHaveClass("nav-open");
    expect(screen.getByRole("button", { name: "منو" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "منو" })).toHaveAttribute("aria-controls", "main-nav");
    await userEvent.click(screen.getByRole("link", { name: /ارسال سریع/ }));
    expect(app).not.toHaveClass("nav-open");
    expect(screen.getByRole("button", { name: "منو" })).toHaveAttribute("aria-expanded", "false");
  });
  it("moves focus into the drawer and Escape returns it to the menu button", async () => {
    const { container } = render(
      <Shell role="user" route="u-dashboard">
        <p>x</p>
      </Shell>,
    );
    const menu = screen.getByRole("button", { name: "منو" });
    await userEvent.click(menu);
    expect(document.querySelector("#main-nav a")).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(container.querySelector(".app")).not.toHaveClass("nav-open");
    expect(menu).toHaveFocus();
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });
});

describe("App routes", () => {
  it.each(Object.keys(ROUTES))("renders %s with its title", (id) => {
    window.location.hash = `#${id}`;
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: ROUTES[id]?.title })).toBeInTheDocument();
  });
  it("falls back to the dashboard on an unknown hash", () => {
    window.location.hash = "#nope";
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: ROUTES["u-dashboard"]?.title })).toBeInTheDocument();
  });
});
