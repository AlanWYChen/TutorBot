import { describe, expect, it } from "vitest";
import { pagePoint, selectionBox, validBox } from "./page-coordinates";
describe("canonical page coordinates", () => {
  it("maps resized and zoomed canvas positions to the same page pixels", () => {
    expect(pagePoint(60, 120, { left: 10, top: 20, width: 100, height: 200 }, 1000, 2000)).toEqual({ x: 500, y: 1000 });
    expect(pagePoint(110, 220, { left: 10, top: 20, width: 200, height: 400 }, 1000, 2000)).toEqual({ x: 500, y: 1000 });
  });
  it("supports reverse drag and clamps outside the page", () => {
    expect(selectionBox({ x: 300, y: 400 }, { x: 100, y: 50 })).toEqual({ x: 100, y: 50, width: 200, height: 350 });
    expect(pagePoint(-10, 300, { left: 0, top: 0, width: 100, height: 200 }, 1000, 2000)).toEqual({ x: 0, y: 2000 });
  });
  it("refuses empty, non-finite or out-of-page boxes", () => {
    for (const box of [{ x: 0, y: 0, width: 0, height: 1 }, { x: 1, y: 0, width: 1000, height: 1 }, { x: NaN, y: 0, width: 1, height: 1 }]) expect(validBox(box, 1000, 2000)).toBe(false);
  });
});
