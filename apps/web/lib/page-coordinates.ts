export type Box = { x: number; y: number; width: number; height: number };
export type Point = { x: number; y: number };
export function pagePoint(clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number }, width: number, height: number): Point {
  return { x: Math.min(width, Math.max(0, (clientX - rect.left) / rect.width * width)), y: Math.min(height, Math.max(0, (clientY - rect.top) / rect.height * height)) };
}
export function selectionBox(a: Point, b: Point): Box {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
}
export function validBox(box: Box, width: number, height: number): boolean {
  return Object.values(box).every(Number.isFinite) && box.x >= 0 && box.y >= 0 && box.width > 0 && box.height > 0 && box.x + box.width <= width && box.y + box.height <= height;
}
