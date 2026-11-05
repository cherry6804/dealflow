import type { StepType } from "../services/workflowApi";

import "./WorkflowCanvas.css";
import { type CanvasNode, connectionsFor } from "./workflowCanvasModel";

interface WorkflowCanvasProps {
  nodes: CanvasNode[];
  entry: string;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

const TYPE_LABEL: Record<StepType, string> = {
  crm_action: "CRM action",
  condition: "Condition",
  agent: "Agent",
  approval: "Approval",
  delay: "Delay",
};

/**
 * A node canvas over the same steps the form edits. Each node is a button, so the canvas works with the keyboard. Selecting a
 * node selects the step whose settings the form shows. The canvas holds no state of its own.
 */
export default function WorkflowCanvas({ nodes, entry, selectedIndex, onSelect }: WorkflowCanvasProps) {
  if (nodes.length === 0) {
    return <p className="workflows-subtle">Add a step to see the workflow here.</p>;
  }
  return (
    <ol className="workflows-canvas" aria-label="Workflow steps as a graph">
      {nodes.map((node, index) => {
        const selected = selectedIndex === index;
        return (
          <li key={`${node.id}-${index}`} className="workflows-canvas-item">
            <button
              type="button"
              className="workflows-node"
              aria-pressed={selected}
              onClick={() => onSelect(index)}
            >
              <span className="workflows-node-title">{node.id || "Unnamed step"}</span>
              <span className="workflows-node-type">{TYPE_LABEL[node.type]}</span>
              {entry === node.id ? <span className="workflows-node-tag">Start</span> : null}
              <span className="workflows-subtle">{connectionsFor(node).join(" · ")}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
