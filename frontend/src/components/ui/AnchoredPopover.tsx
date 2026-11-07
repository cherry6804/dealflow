import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

export interface AnchoredPopoverProps {
  open: boolean;
  /** Element the popover is attached to. Its bounding box positions the popover. */
  anchorRef: RefObject<HTMLElement | null>;
  /** Accessible name of the popover dialog. */
  label: string;
  onClose: () => void;
  /** Preferred width in pixels. The popover never exceeds the viewport. */
  width?: number;
  children: ReactNode;
}

const GAP = 6;
const EDGE = 8;

/**
 * A popover rendered in a portal on document.body and positioned from its anchor. It is never clipped by overflow on the
 * grid or card that opened it, it repositions when the viewport changes, and it stays inside the viewport: it aligns to the
 * anchor's right edge and moves above the anchor when there is no room below.
 *
 * Escape closes it and returns focus to the anchor. A press outside both the panel and the anchor closes it. A press inside
 * the panel never closes it. Focus moves into the panel when it opens.
 */
export function AnchoredPopover({ open, anchorRef, label, onClose, width = 360, children }: AnchoredPopoverProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState<{ top: number; left: number; maxHeight: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const panelWidth = Math.min(width, window.innerWidth - EDGE * 2);
      let left = rect.right - panelWidth;
      left = Math.max(EDGE, Math.min(left, window.innerWidth - panelWidth - EDGE));
      const spaceBelow = window.innerHeight - rect.bottom - GAP - EDGE;
      const spaceAbove = rect.top - GAP - EDGE;
      const placeBelow = spaceBelow >= Math.min(320, spaceAbove) || spaceBelow >= spaceAbove;
      const maxHeight = Math.max(160, placeBelow ? spaceBelow : spaceAbove);
      const top = placeBelow ? rect.bottom + GAP : Math.max(EDGE, rect.top - GAP - Math.min(maxHeight, panelRef.current?.offsetHeight ?? maxHeight));
      setPosition({ top, left, maxHeight });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchorRef, width]);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>("input, button:not(:disabled)")?.focus();

    function onPointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (panelRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, anchorRef, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label={label}
      className="df-popover-surface"
      style={{
        position: "fixed",
        top: position?.top ?? 0,
        left: position?.left ?? 0,
        width: Math.min(width, window.innerWidth - EDGE * 2),
        maxHeight: position?.maxHeight ?? "70vh",
        visibility: position ? "visible" : "hidden",
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
