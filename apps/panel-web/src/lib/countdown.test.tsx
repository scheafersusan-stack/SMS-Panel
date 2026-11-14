import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clock, useCountdown } from "./countdown";

describe("clock", () => {
  it("formats mm:ss in Persian digits", () => {
    expect(clock(105)).toBe("۰۱:۴۵");
    expect(clock(0)).toBe("۰۰:۰۰");
  });
});

describe("useCountdown", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  it("counts down to zero", () => {
    const { result } = renderHook(() => useCountdown());
    expect(result.current.left).toBe(0);
    act(() => result.current.start(3));
    expect(result.current.left).toBe(3);
    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current.left).toBe(1);
    act(() => void vi.advanceTimersByTime(5000));
    expect(result.current.left).toBe(0);
  });
});
