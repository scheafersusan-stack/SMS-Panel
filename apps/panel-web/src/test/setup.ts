import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

window.scrollTo = () => undefined;

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  try {
    window.localStorage.clear();
  } catch {
    // storage may be unavailable
  }
});
