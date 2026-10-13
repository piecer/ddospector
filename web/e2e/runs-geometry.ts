import { expect, type Locator, type ElementHandle } from "@playwright/test";

/** Bounded UUID/digest oracle, not a general CSS/occlusion or screen-reader audit.
 * Initial focus/scroll setup is programmatic. All subsequent offsets are reached
 * by real keyboard input, and every glyph fragment must be wholly visible at an
 * observed offset through the INTERSECTION of every applicable ancestor clip.
 */
export async function literalGeometry(locator: Locator, literal: string) {
  expect(literal).toMatch(/^(?:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/);
  await expect(locator).toHaveText(literal);
  await expect(locator).toBeVisible();
  await locator.scrollIntoViewIfNeeded();
  const sample = () => locator.evaluate(element => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const rectangles: { key: string; left: number; right: number; top: number; bottom: number; width: number; height: number; visible: boolean }[] = [];
    const ancestors: { tag: string; className: string; overflowX: string; overflowY: string; left: number; right: number; top: number; bottom: number; scrollLeft: number; scrollTop: number }[] = [];
    let offset = 0, text: Node | null;
    const unsupported = new Set<string>();
    while ((text = walker.nextNode())) {
      for (let i = 0; i < (text.textContent?.length ?? 0); i++, offset++) {
        const range = document.createRange();
        range.setStart(text, i); range.setEnd(text, i + 1);
        let left = 0, right = innerWidth, top = 0, bottom = innerHeight, rendered = true;
        for (let node = text.parentElement; node; node = node.parentElement) {
          const style = getComputedStyle(node), box = node.getBoundingClientRect();
          const bounds = { left: box.left + node.clientLeft, right: box.left + node.clientLeft + node.clientWidth,
            top: box.top + node.clientTop, bottom: box.top + node.clientTop + node.clientHeight };
          if (offset === 0) ancestors.push({ tag: node.tagName, className: node.className, overflowX: style.overflowX, overflowY: style.overflowY, ...bounds, scrollLeft: node.scrollLeft, scrollTop: node.scrollTop });
          if (/hidden|clip|auto|scroll/.test(style.overflowX)) { left = Math.max(left, bounds.left); right = Math.min(right, bounds.right); }
          if (/hidden|clip|auto|scroll/.test(style.overflowY)) { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom); }
          if (style.visibility !== "visible" || style.display === "none" || Number(style.opacity) === 0) rendered = false;
          if (style.clipPath !== "none" || style.maskImage !== "none" || style.transform !== "none") unsupported.add(node.tagName + ":unsupported-nonrectangular-clip-or-transform");
        }
        const fragments = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
        fragments.forEach((r, part) => rectangles.push({ key: `${offset}:${part}`, left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height,
          visible: rendered && r.left >= left - .75 && r.right <= right + .75 && r.top >= top - .75 && r.bottom <= bottom + .75 }));
      }
    }
    return { text: element.textContent, rectangles, ancestors, unsupported: [...unsupported], documentWidth: document.documentElement.scrollWidth, viewportWidth: innerWidth };
  });
  const initial = await sample(), covered = new Set<string>();
  const observations = [initial];
  const required = initial.rectangles.map(r => r.key);
  const observedOffsets = new Set(initial.rectangles.map(r => Number(r.key.split(":")[0])));
  expect(observedOffsets.size).toBe(literal.length); // no invisible/missing characters
  const collect = (value: typeof initial) => {
    expect(value.text).toBe(literal);
    expect(value.rectangles.map(r => r.key)).toEqual(required);
    for (const r of value.rectangles) if (r.visible) covered.add(r.key);
  };
  collect(initial);
  const complete = () => covered.size === required.length;
  const failures = new Set(initial.unsupported);
  const axes: { node: ElementHandle<HTMLElement>; axis: "x" | "y" }[] = [];
  // DOM order is outermost first. Recursion visits combinations of nested offsets.
  for (const ancestor of await locator.locator("xpath=ancestor-or-self::*").elementHandles()) {
    const scroll = await ancestor.evaluate(e => {
      if (!(e instanceof Element)) throw new Error("Expected an element ancestor");
      const s = getComputedStyle(e);
      return { x: /auto|scroll/.test(s.overflowX) && e.scrollWidth > e.clientWidth + 1,
        y: /auto|scroll/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 1 };
    });
    for (const axis of ["x", "y"] as const) if (scroll[axis]) axes.push({ node: ancestor as ElementHandle<HTMLElement>, axis });
  }
  if (axes.length > 8) failures.add("scroll-axis-budget");
  const moves: { axis: string; key: string; before: number; after: number; focused: boolean }[] = [];
  let keys = 0;
  const position = ({ node, axis }: typeof axes[number]) => node.evaluate((e, a) => a === "x" ? e.scrollLeft : e.scrollTop, axis);
  async function move(entry: typeof axes[number], positive: boolean) {
    if (++keys > 128 || observations.length >= 256) { failures.add("keyboard-observation-budget"); return false; }
    await entry.node.focus();
    const focused = await entry.node.evaluate(e => e === document.activeElement);
    if (!focused) { failures.add("scrollport-cannot-focus"); return false; }
    const before = await position(entry), key = entry.axis === "x" ? positive ? "ArrowRight" : "ArrowLeft" : positive ? "ArrowDown" : "ArrowUp";
    await locator.page().keyboard.press(key);
    // Wait for actual native smooth scrolling to settle, not a guessed offset.
    await entry.node.evaluate(e => new Promise<void>(resolve => {
      let x = e.scrollLeft, y = e.scrollTop, stable = 0, frames = 0;
      function frame() {
        if (e.scrollLeft === x && e.scrollTop === y) stable++; else stable = 0;
        x = e.scrollLeft; y = e.scrollTop;
        if (stable >= 3 || ++frames >= 30) resolve(); else requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    }));
    const after = await position(entry);
    moves.push({ axis: entry.axis, key, before, after, focused });
    const value = await sample(); observations.push(value); collect(value);
    value.unsupported.forEach(x => failures.add(x));
    return Math.abs(after - before) > .25;
  }
  async function visit(depth: number): Promise<void> {
    if (complete() || failures.size || depth === axes.length) return;
    const entry = axes[depth];
    // Include current offset; then sweep both directions. Never set scrollLeft/Top.
    await visit(depth + 1);
    for (const positive of [false, true]) {
      while (!complete() && !failures.size) {
        const moved = await move(entry, positive);
        await visit(depth + 1);
        if (!moved) break;
      }
    }
  }
  await visit(0);
  const missing = required.filter(key => !covered.has(key));
  return { ...initial, observations, moves, covered: [...covered], missing,
    inaccessible: [...failures, ...missing.map(key => `unreached-fragment:${key}`)] };
}
