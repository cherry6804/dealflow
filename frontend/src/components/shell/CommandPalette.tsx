import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { Dialog } from "../ui";
import { filterCommands, type ShellCommand } from "./shellModel";

export interface CommandPaletteLabels {
  title: string;
  description: string;
  closeLabel: string;
  placeholder: string;
  listLabel: string;
  empty: string;
}

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  commands: readonly ShellCommand[];
  labels: CommandPaletteLabels;
}

/**
 * Search and command palette. Lists navigation destinations and shell commands. It is not a record search: the shell
 * has no search API, so the palette does not claim to find deals, contacts or other records.
 *
 * Combobox pattern: focus stays in the input, ArrowUp and ArrowDown move the active option (aria-activedescendant),
 * Enter runs it, Escape closes the dialog.
 */
export function CommandPalette({ open, onClose, commands, labels }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const results = useMemo(() => filterCommands(commands, query), [commands, query]);

  // The native dialog focuses its first control when it opens, which is the close button. Move focus to the search
  // field afterwards; this effect runs after the dialog's own, because the dialog is a child.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  function close() {
    setQuery("");
    setActive(0);
    onClose();
  }

  function run(command: ShellCommand) {
    close();
    command.run();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (results.length === 0 ? 0 : (index + 1) % results.length));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (results.length === 0 ? 0 : (index - 1 + results.length) % results.length));
    } else if (event.key === "Enter") {
      const command = results[active];
      if (command) {
        event.preventDefault();
        run(command);
      }
    }
  }

  const activeId = results[active] ? `${listId}-${results[active].id}` : undefined;

  return (
    <Dialog open={open} onClose={close} title={labels.title} closeLabel={labels.closeLabel} description={labels.description} placement="center">
      <div className="df-palette">
        <input
          type="search"
          className="df-input df-palette-input"
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-label={labels.placeholder}
          placeholder={labels.placeholder}
          value={query}
          autoComplete="off"
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          ref={inputRef}
        />
        {results.length === 0 ? (
          <p className="df-palette-empty" role="status">
            {labels.empty}
          </p>
        ) : (
          <ul id={listId} role="listbox" aria-label={labels.listLabel} className="df-palette-list">
            {results.map((command, index) => (
              <li
                key={command.id}
                id={`${listId}-${command.id}`}
                role="option"
                aria-selected={index === active}
                className={`df-palette-option${index === active ? " df-palette-option--active" : ""}`}
                onMouseEnter={() => setActive(index)}
                onClick={() => run(command)}
              >
                <span className="df-palette-option-label">{command.label}</span>
                <span className="df-palette-option-group">{command.group}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
