import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronDown, ChevronUp, GripVertical, Pin, PinOff, type LucideIcon } from "lucide-react";

import { Button, Checkbox, Dialog, RadioGroup } from "../../../components/ui";
import type { TableDensity } from "../workspacePreferences";
import {
  allSpacesInOrder,
  moveSpace,
  reorderSpaces,
  setCollapsed,
  setDensity,
  toggleHidden,
  togglePinned,
  type SidebarDensity,
  type SpacePreferences,
} from "./spacePreferences";

export interface SidebarCustomizerProps {
  open: boolean;
  onClose: () => void;
  preferences: SpacePreferences;
  onChange: (next: SpacePreferences) => void;
  onRestoreDefaults: () => void;
  /** Table density is read by the data grids. It is kept in the workspace preference store, per user and organization. */
  tableDensity: TableDensity;
  onTableDensityChange: (density: TableDensity) => void;
}

const MODE_OPTIONS = [
  { value: "expanded", label: "Expanded (icons and labels)" },
  { value: "icons", label: "Icons only" },
];

const DENSITY_OPTIONS = [
  { value: "comfortable", label: "Comfortable" },
  { value: "compact", label: "Compact" },
];

interface RowProps {
  id: string;
  label: string;
  pinned: boolean;
  hidden: boolean;
  hideable: boolean;
  position: number;
  total: number;
  icon: LucideIcon;
  onTogglePinned: () => void;
  onToggleHidden: () => void;
  onMove: (direction: -1 | 1) => void;
}

function SortableSpaceRow(props: RowProps) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging, isOver } = useSortable({
    id: props.id,
  });
  const Icon = props.icon;
  const style = { transform: CSS.Transform.toString(transform), transition };
  const status = [props.pinned ? "Pinned" : null, props.hidden ? "Hidden" : null].filter(Boolean).join(" · ");

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`df-ws-custom-row${isDragging ? " df-ws-custom-row--dragging" : ""}${isOver && !isDragging ? " df-ws-custom-row--over" : ""}`}
    >
      <button
        ref={setActivatorNodeRef}
        type="button"
        className="df-ws-custom-handle"
        aria-label={`Drag ${props.label} to reorder, or use the move buttons`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={18} aria-hidden="true" />
      </button>
      <Icon size={18} aria-hidden={true} />
      <span className="df-ws-custom-name">
        {props.label}
        {status ? <span className="df-ws-custom-status"> · {status}</span> : null}
      </span>
      <Button
        variant="tertiary"
        size="sm"
        iconOnly
        aria-label={props.pinned ? `Unpin ${props.label}` : `Pin ${props.label}`}
        aria-pressed={props.pinned}
        icon={props.pinned ? <PinOff size={16} aria-hidden="true" /> : <Pin size={16} aria-hidden="true" />}
        onClick={props.onTogglePinned}
      >
        {props.pinned ? "Unpin" : "Pin"}
      </Button>
      <Checkbox
        label={`Show ${props.label}`}
        checked={!props.hidden}
        disabled={!props.hideable}
        title={props.hideable ? undefined : "Overview is always shown"}
        onChange={props.onToggleHidden}
      />
      <Button
        variant="tertiary"
        size="sm"
        iconOnly
        aria-label={`Move ${props.label} up`}
        disabled={props.position === 0}
        icon={<ChevronUp size={16} aria-hidden="true" />}
        onClick={() => props.onMove(-1)}
      >
        Up
      </Button>
      <Button
        variant="tertiary"
        size="sm"
        iconOnly
        aria-label={`Move ${props.label} down`}
        disabled={props.position === props.total - 1}
        icon={<ChevronDown size={16} aria-hidden="true" />}
        onClick={() => props.onMove(1)}
      >
        Down
      </Button>
    </li>
  );
}

/**
 * Sidebar customization. Spaces can be reordered by dragging (pointer or keyboard) or with the move buttons, pinned,
 * shown or hidden, and the sidebar can be switched between expanded and icons-only. Every change is personal and is
 * saved through the caller, which scopes it to the signed-in user and organization.
 */
export function SidebarCustomizer({
  open,
  onClose,
  preferences,
  onChange,
  onRestoreDefaults,
  tableDensity,
  onTableDensityChange,
}: SidebarCustomizerProps) {
  const entries = allSpacesInOrder(preferences);
  const ids = entries.map((entry) => entry.space.id);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    onChange(reorderSpaces(preferences, String(active.id), String(over.id)));
  }

  return (
    <Dialog open={open} onClose={onClose} title="Customize sidebar" closeLabel="Close customization" placement="end"
      description="Changes apply only to you, in this organization, on this device."
      footer={
        <Button variant="secondary" onClick={onRestoreDefaults}>
          Restore default arrangement
        </Button>
      }
    >
      <section aria-labelledby="df-custom-spaces">
        <h3 id="df-custom-spaces" className="df-state-title">Spaces</h3>
        <p className="df-state-message">Drag a handle, or use the move buttons, to change the order. Pinned spaces appear first.</p>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={ids} strategy={verticalListSortingStrategy}>
            <ul className="df-ws-custom-list" aria-label="Spaces in sidebar order">
              {entries.map((entry, index) => (
                <SortableSpaceRow
                  key={entry.space.id}
                  id={entry.space.id}
                  label={entry.space.label}
                  pinned={entry.pinned}
                  hidden={entry.hidden}
                  hideable={entry.space.hideable}
                  position={index}
                  total={entries.length}
                  icon={entry.space.icon}
                  onTogglePinned={() => onChange(togglePinned(preferences, entry.space.id))}
                  onToggleHidden={() => onChange(toggleHidden(preferences, entry.space.id))}
                  onMove={(direction) => onChange(moveSpace(preferences, entry.space.id, direction))}
                />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
      </section>

      <section aria-labelledby="df-custom-mode" className="df-ws-custom-settings">
        <h3 id="df-custom-mode" className="df-state-title">Sidebar mode</h3>
        <RadioGroup
          name="sidebar-mode"
          label="Sidebar mode"
          value={preferences.collapsed ? "icons" : "expanded"}
          options={MODE_OPTIONS}
          onChange={(value) => onChange(setCollapsed(preferences, value === "icons"))}
        />
      </section>

      <section aria-labelledby="df-custom-table" className="df-ws-custom-settings">
        <h3 id="df-custom-table" className="df-state-title">Table density</h3>
        <p className="df-state-message">Applies to data tables and grids.</p>
        <RadioGroup
          name="table-density"
          label="Table density"
          value={tableDensity}
          options={[
            { value: "comfortable", label: "Comfortable" },
            { value: "compact", label: "Compact" },
          ]}
          onChange={(value) => onTableDensityChange(value as TableDensity)}
        />
      </section>

      <section aria-labelledby="df-custom-density" className="df-ws-custom-settings">
        <h3 id="df-custom-density" className="df-state-title">Row spacing</h3>
        <RadioGroup
          name="sidebar-density"
          label="Row spacing"
          value={preferences.density}
          options={DENSITY_OPTIONS}
          onChange={(value) => onChange(setDensity(preferences, value as SidebarDensity))}
        />
      </section>
    </Dialog>
  );
}
