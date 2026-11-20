/**
 * GraphPanel — Cytoscape.js mule ring topology visualizer (Minimalist Light Sky-Blue)
 */
import { useEffect, useRef } from 'react';
import cytoscape, { type Core, type ElementsDefinition, type StylesheetStyle } from 'cytoscape';
import { Network } from 'lucide-react';
import { getGraph } from '../api';
import type { CytoscapeGraph } from '../types';

interface Props {
  latestGraph: CytoscapeGraph | null;
  fetchInitial?: boolean;
}

const STYLE: StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': '#6366f1',
      'label': 'data(label)',
      'color': 'rgba(226,232,240,0.9)',
      'font-size': 9,
      'font-weight': 'bold',
      'text-valign': 'bottom',
      'text-margin-y': 4,
      'width': 26,
      'height': 26,
    },
  },
  {
    selector: 'node[type = "new_account"]',
    style: {
      'background-color': '#f59e0b',
      shape: 'diamond',
      'width': 28,
      'height': 28,
    },
  },
  {
    selector: 'node[type = "quarantined"]',
    style: {
      'background-color': '#f43f5e',
      'border-color': 'rgba(244,63,94,0.5)',
      'border-width': 3,
      'width': 30,
      'height': 30,
    },
  },
  {
    selector: 'edge',
    style: {
      'width': 1.5,
      'line-color': 'rgba(255,255,255,0.12)',
      'target-arrow-color': 'rgba(255,255,255,0.2)',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'label': 'data(label)',
      'font-size': 8,
      'color': 'rgba(148,163,184,0.7)',
      'text-background-color': '#111118',
      'text-background-opacity': 0.9,
      'text-background-padding': '2px',
    },
  },
];

export default function GraphPanel({ latestGraph, fetchInitial = true }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  /* Init Cytoscape once */
  useEffect(() => {
    if (!containerRef.current) return;
    cyRef.current = cytoscape({
      container: containerRef.current,
      style: STYLE,
      layout: { name: 'cose', animate: false },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      backgroundColor: 'transparent' as unknown as string,
    } as cytoscape.CytoscapeOptions);
    // Load initial graph
    if (fetchInitial) getGraph().then(g => {
      if (cyRef.current) applyGraph(cyRef.current, g);
    }).catch(() => {});
    return () => { cyRef.current?.destroy(); cyRef.current = null; };
  }, []);

  /* Update graph when WS sends new data */
  useEffect(() => {
    if (latestGraph && cyRef.current) {
      applyGraph(cyRef.current, latestGraph);
    }
  }, [latestGraph]);

  return (
    <div
      className="rounded-xl p-3.5"
      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
    >
      <div className="mb-2 flex items-center gap-2">
        <Network size={13} className="text-indigo-400" />
        <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.7)' }}>
          Network Topology
        </h3>
      </div>

      <div
        ref={containerRef}
        className="cy-container"
        style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '0.75rem' }}
      />

      <div
        className="mt-2.5 flex items-center gap-4 text-xs border-t pt-2"
        style={{ borderColor: 'rgba(255,255,255,0.06)', color: 'rgba(148,163,184,0.5)' }}
      >
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-indigo-500" />
          Standard
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rotate-45 bg-amber-500" />
          New Account
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500" style={{ boxShadow: '0 0 6px rgba(244,63,94,0.5)' }} />
          Quarantined
        </span>
      </div>
    </div>
  );
}

function applyGraph(cy: Core, g: CytoscapeGraph) {
  cy.elements().remove();
  const elements = g.elements ?? { nodes: g.nodes ?? [], edges: g.edges ?? [] };
  cy.add(elements as unknown as ElementsDefinition);
  cy.layout({ name: 'cose', animate: false } as cytoscape.LayoutOptions).run();
  cy.fit(undefined, 20);
}
