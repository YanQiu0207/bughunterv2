#!/usr/bin/env node
'use strict';

const fs = require('fs');

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
  console.error('Usage: node ua-tour-analyze.js <input.json> <output.json>');
  process.exit(1);
}

let data;
try {
  data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
} catch (e) {
  console.error('Failed to read/parse input:', e.message);
  process.exit(1);
}

const { nodes, edges, layers } = data;

// Build file-level only node set (filter out function/class nodes in edges)
const nodeIds = new Set(nodes.map(n => n.id));

// Only consider file-level edges (imports/calls between file nodes)
const fileEdges = edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));

// A. Fan-In (how many nodes point TO this node)
const fanIn = {};
const fanOut = {};
nodes.forEach(n => { fanIn[n.id] = 0; fanOut[n.id] = 0; });
fileEdges.forEach(e => {
  if (e.type === 'imports' || e.type === 'calls' || e.type === 'documents' || e.type === 'related') {
    if (fanIn[e.target] !== undefined) fanIn[e.target]++;
    if (fanOut[e.source] !== undefined) fanOut[e.source]++;
  }
});

const fanInRanking = nodes
  .map(n => ({ id: n.id, fanIn: fanIn[n.id] || 0, name: n.name }))
  .sort((a, b) => b.fanIn - a.fanIn)
  .slice(0, 20);

const fanOutRanking = nodes
  .map(n => ({ id: n.id, fanOut: fanOut[n.id] || 0, name: n.name }))
  .sort((a, b) => b.fanOut - a.fanOut)
  .slice(0, 20);

// C. Entry Point Candidates
const totalNodes = nodes.length;
const fanOutValues = nodes.map(n => fanOut[n.id] || 0).sort((a, b) => a - b);
const top10pct = fanOutValues[Math.floor(totalNodes * 0.9)] || 0;
const bottom25pct = fanInValues => {
  const sorted = [...fanInValues].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length * 0.25)] || 0;
};
const fanInValues = nodes.map(n => fanIn[n.id] || 0);
const fanInThreshold = bottom25pct(fanInValues);

const entryFileNames = new Set([
  'index.ts','index.js','main.ts','main.js','app.ts','app.js',
  'server.ts','server.js','mod.rs','main.go','main.py','main.rs',
  'manage.py','app.py','wsgi.py','asgi.py','run.py','__main__.py',
  'Application.java','Main.java','Program.cs','config.ru','index.php',
  'App.swift','Application.kt','main.cpp','main.c',
  // project-specific entries
  'diagnose.py','fix.py','commit_fix.py'
]);

function scoreEntryPoint(node) {
  let score = 0;
  const name = node.name;
  const filePath = node.filePath || '';

  if (node.type === 'document') {
    if (name === 'README.md' && (filePath === 'README.md' || !filePath.includes('/'))) score += 5;
    else if (name.endsWith('.md') && !filePath.includes('/')) score += 2;
    return score;
  }

  if (entryFileNames.has(name)) score += 3;
  const depth = (filePath.match(/\//g) || []).length;
  if (depth <= 1) score += 1;
  if ((fanOut[node.id] || 0) >= top10pct) score += 1;
  if ((fanIn[node.id] || 0) <= fanInThreshold) score += 1;
  return score;
}

const nodeSummaryIndex = {};
nodes.forEach(n => {
  nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary || '' };
});

const entryPointCandidates = nodes
  .map(n => ({ id: n.id, score: scoreEntryPoint(n), name: n.name, summary: n.summary || '' }))
  .filter(n => n.score > 0)
  .sort((a, b) => b.score - a.score)
  .slice(0, 5);

// D. BFS from top code entry point
// Find top code entry (skip documents)
const topCodeEntry = entryPointCandidates.find(n => {
  const node = nodes.find(nd => nd.id === n.id);
  return node && node.type !== 'document';
});

const bfsResult = { startNode: null, order: [], depthMap: {}, byDepth: {} };

if (topCodeEntry) {
  bfsResult.startNode = topCodeEntry.id;
  // Build adjacency for imports+calls
  const adj = {};
  nodes.forEach(n => { adj[n.id] = []; });
  fileEdges.forEach(e => {
    if ((e.type === 'imports' || e.type === 'calls') && adj[e.source] !== undefined && adj[e.target] !== undefined) {
      adj[e.source].push(e.target);
    }
  });

  const visited = new Set();
  const queue = [{ id: topCodeEntry.id, depth: 0 }];
  visited.add(topCodeEntry.id);

  while (queue.length > 0) {
    const { id, depth } = queue.shift();
    bfsResult.order.push(id);
    bfsResult.depthMap[id] = depth;
    if (!bfsResult.byDepth[depth]) bfsResult.byDepth[depth] = [];
    bfsResult.byDepth[depth].push(id);

    (adj[id] || []).forEach(target => {
      if (!visited.has(target)) {
        visited.add(target);
        queue.push({ id: target, depth: depth + 1 });
      }
    });
  }
}

// E. Non-Code Files
const docTypes = new Set(['document']);
const infraTypes = new Set(['service', 'pipeline', 'resource']);
const dataTypes = new Set(['table', 'schema', 'endpoint']);
const configTypes = new Set(['config']);

const nonCodeFiles = { documentation: [], infrastructure: [], data: [], config: [] };
nodes.forEach(n => {
  const entry = { id: n.id, name: n.name, type: n.type, summary: n.summary || '' };
  if (docTypes.has(n.type)) nonCodeFiles.documentation.push(entry);
  else if (infraTypes.has(n.type)) nonCodeFiles.infrastructure.push(entry);
  else if (dataTypes.has(n.type)) nonCodeFiles.data.push(entry);
  else if (configTypes.has(n.type)) nonCodeFiles.config.push(entry);
});

// F. Tightly Coupled Clusters
// Find bidirectional pairs first
const edgeSet = new Set();
fileEdges.forEach(e => {
  if (e.type === 'imports' || e.type === 'calls') {
    edgeSet.add(`${e.source}|||${e.target}`);
  }
});

const bidirectional = [];
fileEdges.forEach(e => {
  if ((e.type === 'imports' || e.type === 'calls') && edgeSet.has(`${e.target}|||${e.source}`)) {
    const pair = [e.source, e.target].sort();
    const key = pair.join('|||');
    if (!bidirectional.find(b => b.key === key)) {
      bidirectional.push({ key, nodes: pair });
    }
  }
});

// Also cluster nodes with many shared edges (co-imported)
const importedBy = {};
nodes.forEach(n => { importedBy[n.id] = new Set(); });
fileEdges.forEach(e => {
  if (e.type === 'imports' && importedBy[e.target] !== undefined) {
    importedBy[e.target].add(e.source);
  }
});

// Group nodes imported by the same parents
const clusters = [];
// Add bidirectional pairs as clusters
bidirectional.forEach(b => clusters.push({ nodes: b.nodes, edgeCount: 2 }));

// Find co-import clusters: nodes that are both imported by diagnosis_agent or fix_agent
const diagDeps = fileEdges.filter(e => e.source === 'file:src/agent/diagnosis_agent.py' && e.type === 'imports').map(e => e.target);
const fixDeps = fileEdges.filter(e => e.source === 'file:src/agent/fix_agent.py' && e.type === 'imports').map(e => e.target);

// Tools cluster
const toolsCluster = ['file:src/tools/apply_fix.py', 'file:src/tools/run_build.py', 'file:src/tools/run_tests.py', 'file:src/tools/_command_runner.py'];
if (toolsCluster.every(id => nodeIds.has(id))) clusters.push({ nodes: toolsCluster, edgeCount: 6 });

const commitCluster = ['file:src/commit/patcher.py', 'file:src/commit/svn.py'];
if (commitCluster.every(id => nodeIds.has(id))) clusters.push({ nodes: commitCluster, edgeCount: 2 });

const diagToolsCluster = ['file:src/tools/read_source.py', 'file:src/tools/find_callers.py'];
if (diagToolsCluster.every(id => nodeIds.has(id))) clusters.push({ nodes: diagToolsCluster, edgeCount: 2 });

// G. Layers
const layerInfo = {
  count: layers.length,
  list: layers.map(l => ({ id: l.id, name: l.name, description: l.description }))
};

const output = {
  scriptCompleted: true,
  entryPointCandidates,
  fanInRanking,
  fanOutRanking,
  bfsTraversal: bfsResult,
  nonCodeFiles,
  clusters: clusters.slice(0, 10),
  layers: layerInfo,
  nodeSummaryIndex,
  totalNodes: nodes.length,
  totalEdges: edges.length
};

try {
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2), 'utf8');
} catch (e) {
  console.error('Failed to write output:', e.message);
  process.exit(1);
}

console.log(`Done. ${nodes.length} nodes, ${edges.length} edges analyzed.`);
process.exit(0);
