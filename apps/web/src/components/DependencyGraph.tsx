import { useCallback, useMemo } from "react";
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";

import type { DependencyGraph as Graph } from "../types/api";

const DIR_COLOR: Record<string, string> = {
  root: "#e0762a", downstream: "#4d8fd1", upstream: "#4fa37a", spec: "#c9a227", assembly: "#8b98a9",
};

/** Layered layout: upstream left, root centre, downstream right. */
export function DependencyGraphView({ graph, selected, onSelect }: {
  graph: Graph; selected: string | null; onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const upstream = graph.nodes.filter((n) => n.direction === "upstream").sort((a, b) => a.depth - b.depth);
    const downstream = graph.nodes.filter((n) => n.direction === "downstream").sort((a, b) => a.depth - b.depth);
    const root = graph.nodes.find((n) => n.direction === "root");
    const pos = new Map<string, { x: number; y: number }>();
    if (root) pos.set(root.id, { x: 420, y: 220 });
    upstream.forEach((n, i) => pos.set(n.id, { x: 420 - 190 * n.depth, y: 90 + i * 92 }));
    downstream.forEach((n, i) => pos.set(n.id, { x: 420 + 190 * n.depth, y: 90 + i * 92 }));
    const rfNodes: Node[] = graph.nodes.map((n) => ({
      id: n.id,
      position: pos.get(n.id) ?? { x: 420, y: 40 },
      data: { label: `${n.label}\n${n.subsystem || n.type}${n.depth ? ` · ${n.depth} hop` : ""}` },
      style: {
        background: "#131924",
        color: "#d7dde6",
        border: `1.5px solid ${DIR_COLOR[n.direction] ?? "#243040"}`,
        borderRadius: 2,
        fontSize: 11,
        fontFamily: "ui-monospace, monospace",
        padding: 8,
        width: 168,
        whiteSpace: "pre-line",
        boxShadow: selected === n.id ? `0 0 0 2px ${DIR_COLOR[n.direction]}` : undefined,
      },
    }));
    const rfEdges: Edge[] = graph.edges.map((e) => ({
      id: e.id,
      source: e.source_component_id,
      target: e.target_component_id,
      label: e.relationship_type.toLowerCase(),
      style: { stroke: e.criticality === "critical" ? "#d64533" : "#2e4054", strokeWidth: e.criticality === "critical" ? 1.8 : 1 },
      labelStyle: { fill: "#6b7480", fontSize: 9, fontFamily: "monospace" },
      labelBgStyle: { fill: "#0f131a" },
      animated: e.criticality === "critical",
    }));
    return { nodes: rfNodes, edges: rfEdges };
  }, [graph, selected]);

  const onNode = useCallback((_: unknown, node: Node) => onSelect(node.id), [onSelect]);

  return (
    <div className="h-full min-h-0">
      <ReactFlow nodes={nodes} edges={edges} onNodeClick={onNode} fitView proOptions={{ hideAttribution: true }}
        minZoom={0.35} maxZoom={1.6}>
        <Background color="#1c2634" gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
