import type { StepType } from "../services/workflowApi";

export interface CanvasNode {
  id: string;
  type: StepType;
  next: string;
  then: string;
  elseStep: string;
}

/** The outgoing connections of a node, as the words the canvas shows. A node with none ends the run. */
export function connectionsFor(node: CanvasNode): string[] {
  if (node.type === "condition") {
    return [
      node.then ? `if true: ${node.then}` : "if true: not set",
      node.elseStep ? `if false: ${node.elseStep}` : "if false: not set",
    ];
  }
  return node.next ? [`then: ${node.next}`] : ["ends the run"];
}
