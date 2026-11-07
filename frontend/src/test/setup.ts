import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// react-data-grid uses the Iterator helpers (map, filter, toArray, ...). The test runtime may not provide them yet; the
// browser does. These polyfills align the test runtime with the browser, on the built-in %IteratorPrototype%.
const IteratorPrototype = Object.getPrototypeOf(Object.getPrototypeOf([][Symbol.iterator]())) as Record<string, unknown>;
const iteratorHelpers: Record<string, (this: Iterator<unknown>, ...args: never[]) => unknown> = {
  toArray(this: Iterator<unknown>) {
    const items: unknown[] = [];
    for (let step = this.next(); !step.done; step = this.next()) items.push(step.value);
    return items;
  },
  map(this: Iterator<unknown>, fn: (value: unknown, index: number) => unknown) {
    const pull = this.next.bind(this);
    let index = 0;
    return iteratorFrom(() => {
      const step = pull();
      return step.done ? step : { done: false, value: fn(step.value, index++) };
    });
  },
  filter(this: Iterator<unknown>, fn: (value: unknown, index: number) => boolean) {
    const pull = this.next.bind(this);
    let index = 0;
    return iteratorFrom(() => {
      for (;;) {
        const step = pull();
        if (step.done || fn(step.value, index++)) return step;
      }
    });
  },
  forEach(this: Iterator<unknown>, fn: (value: unknown, index: number) => void) {
    let index = 0;
    for (let step = this.next(); !step.done; step = this.next()) fn(step.value, index++);
  },
  some(this: Iterator<unknown>, fn: (value: unknown) => boolean) {
    for (let step = this.next(); !step.done; step = this.next()) if (fn(step.value)) return true;
    return false;
  },
  every(this: Iterator<unknown>, fn: (value: unknown) => boolean) {
    for (let step = this.next(); !step.done; step = this.next()) if (!fn(step.value)) return false;
    return true;
  },
  find(this: Iterator<unknown>, fn: (value: unknown) => boolean) {
    for (let step = this.next(); !step.done; step = this.next()) if (fn(step.value)) return step.value;
    return undefined;
  },
};

function iteratorFrom(next: () => IteratorResult<unknown>): Iterator<unknown> {
  // Inherit from %IteratorPrototype% so the helpers chain (map(...).toArray()).
  return Object.create(IteratorPrototype, { next: { value: next, writable: true, configurable: true } }) as Iterator<unknown>;
}

for (const [name, fn] of Object.entries(iteratorHelpers)) {
  if (typeof IteratorPrototype[name] !== "function") {
    Object.defineProperty(IteratorPrototype, name, { value: fn, configurable: true, writable: true });
  }
}
