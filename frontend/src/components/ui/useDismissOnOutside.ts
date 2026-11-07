import { useEffect } from "react";
import type { RefObject } from "react";

/**
 * Calls `onDismiss` when a pointer press lands outside `ref` while `active` is true. Escape handling stays with each
 * component, because some close and return focus and some do not.
 */
export function useDismissOnOutside(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  onDismiss: () => void,
): void {
  useEffect(() => {
    if (!active) return;
    function onPointerDown(event: PointerEvent) {
      const node = ref.current;
      if (node && event.target instanceof Node && !node.contains(event.target)) {
        onDismiss();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [ref, active, onDismiss]);
}
