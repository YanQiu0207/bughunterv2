#!/usr/bin/env node
// Architecture analysis script for bughunterv2
const fs = require('fs');

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
  console.error('Usage: node ua-arch-analyze.js <input.json> <output.json>');
  process.exit(1);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(inputPath, 'utf-8'));
} catch (e) {
  console.error('Failed to read input:', e.message);
  process.exit(1);
}

const { fileNodes, importEdges, allEdges } = input;

// ---- A. Directory Grouping ----
// Compute common prefix
function getCommonPrefix(paths) {
  if (!paths.length) return '';
  const parts = paths.map(p => p.split('/'));
  const minLen = Math.min(...parts.map(p => p.length));
  let prefix = [];
  for (let i = 0; i < minLen - 1; i++) {
    const seg = parts[0][i];
    if (parts.every(p => p[i] === seg)) prefix.push(seg);
    else break;
  }
  return prefix.join('/');
}

const allPaths = fileNodes.map(n => n.filePath);
const commonPrefix = getCommonPrefix(allPaths);
const prefixSegs = commonPrefix ? commonPrefix.split('/').length : 0;

function getGroup(filePath) {
  const segs = filePath.split('/');
  // Remove common prefix segments
  const rest = segs.slice(prefixSegs);
  if (rest.length === 0) return 'root';
  // Special case: hidden dirs like .understand-anything
  if (rest[0].startsWith('.')) return rest[0];
  // egg-info dir
  if (rest[0].includes('.egg-info')) return 'egg-info';
  // workspace
  if (rest[0] === 'workspace') return 'workspace';
  // openspec
  if (rest[0] === 'openspec') return 'openspec';
  // src subdir
  if (rest[0] === 'src' && rest.length > 1) return `src/${rest[1]}`;
  // root level files
  if (rest.length === 1) return 'root';
  return rest[0];
}

const directoryGroups = {};
for (const node of fileNodes) {
  const group = getGroup(node.filePath);
  if (!directoryGroups[group]) directoryGroups[group] = [];
  directoryGroups[group].push(node.id);
}

// ---- B. Node Type Grouping ----
const nodeTypeGroups = {};
for (const node of fileNodes) {
  if (!nodeTypeGroups[node.type]) nodeTypeGroups[node.type] = [];
  nodeTypeGroups[node.type].push(node.id);
}

// ---- C. Import adjacency / fan-in / fan-out ----
const fanOut = {};
const fanIn = {};
for (const node of fileNodes) {
  fanOut[node.id] = 0;
  fanIn[node.id] = 0;
}
for (const edge of importEdges) {
  if (fanOut[edge.source] !== undefined) fanOut[edge.source]++;
  if (fanIn[edge.target] !== undefined) fanIn[edge.target]++;
}

// ---- D. Cross-Category Dependency Analysis ----
const nodeTypeById = {};
for (const node of fileNodes) nodeTypeById[node.id] = node.type;

const crossCategoryMap = {};
for (const edge of allEdges) {
  const srcType = nodeTypeById[edge.source];
  const tgtType = nodeTypeById[edge.target];
  if (!srcType || !tgtType) continue;
  if (srcType === tgtType) continue;
  const key = `${srcType}->${tgtType}:${edge.type}`;
  crossCategoryMap[key] = (crossCategoryMap[key] || 0) + 1;
}
const crossCategoryEdges = Object.entries(crossCategoryMap).map(([key, count]) => {
  const [types, edgeType] = key.split(':');
  const [fromType, toType] = types.split('->');
  return { fromType, toType, edgeType, count };
});

// ---- E. Inter-Group Import Frequency ----
const idToGroup = {};
for (const node of fileNodes) idToGroup[node.id] = getGroup(node.filePath);

const interGroupMap = {};
for (const edge of importEdges) {
  const srcGroup = idToGroup[edge.source];
  const tgtGroup = idToGroup[edge.target];
  if (!srcGroup || !tgtGroup || srcGroup === tgtGroup) continue;
  const key = `${srcGroup}=>${tgtGroup}`;
  interGroupMap[key] = (interGroupMap[key] || 0) + 1;
}
const interGroupImports = Object.entries(interGroupMap).map(([key, count]) => {
  const [from, to] = key.split('=>');
  return { from, to, count };
}).sort((a, b) => b.count - a.count);

// ---- F. Intra-Group Import Density ----
const intraGroupDensity = {};
for (const group of Object.keys(directoryGroups)) {
  const members = new Set(directoryGroups[group]);
  let internalEdges = 0;
  let totalEdges = 0;
  for (const edge of importEdges) {
    const srcInGroup = members.has(edge.source);
    const tgtInGroup = members.has(edge.target);
    if (srcInGroup || tgtInGroup) totalEdges++;
    if (srcInGroup && tgtInGroup) internalEdges++;
  }
  intraGroupDensity[group] = {
    internalEdges,
    totalEdges,
    density: totalEdges > 0 ? +(internalEdges / totalEdges).toFixed(3) : 0
  };
}

// ---- G. Directory Pattern Matching ----
const PATTERN_MAP = {
  routes: 'api', api: 'api', controllers: 'api', endpoints: 'api', handlers: 'api',
  services: 'service', core: 'service', lib: 'service', domain: 'service', logic: 'service',
  models: 'data', db: 'data', data: 'data', persistence: 'data', repository: 'data',
  entities: 'data', migrations: 'data', entity: 'data', sql: 'data', database: 'data',
  schema: 'data',
  components: 'ui', views: 'ui', pages: 'ui', ui: 'ui', layouts: 'ui', screens: 'ui',
  middleware: 'middleware', plugins: 'middleware', interceptors: 'middleware', guards: 'middleware',
  utils: 'utility', helpers: 'utility', common: 'utility', shared: 'utility', tools: 'utility',
  templatetags: 'utility', pkg: 'utility',
  config: 'config', constants: 'config', env: 'config', settings: 'config',
  management: 'config', commands: 'config',
  '__tests__': 'test', test: 'test', tests: 'test', spec: 'test', specs: 'test',
  types: 'types', interfaces: 'types', schemas: 'types', contracts: 'types', dtos: 'types',
  dto: 'types', request: 'types', response: 'types',
  hooks: 'hooks',
  store: 'state', state: 'state', reducers: 'state', actions: 'state', slices: 'state',
  assets: 'assets', static: 'assets', public: 'assets',
  signals: 'service', composables: 'service', mailers: 'service', jobs: 'service',
  channels: 'service', serializers: 'api', blueprints: 'api', routers: 'api',
  controller: 'api',
  cmd: 'entry', bin: 'entry',
  internal: 'service',
  docs: 'documentation', documentation: 'documentation', wiki: 'documentation',
  deploy: 'infrastructure', deployment: 'infrastructure', infra: 'infrastructure',
  infrastructure: 'infrastructure', k8s: 'infrastructure', kubernetes: 'infrastructure',
  helm: 'infrastructure', charts: 'infrastructure', terraform: 'infrastructure',
  tf: 'infrastructure', docker: 'infrastructure',
  '.github': 'ci-cd', '.gitlab': 'ci-cd', '.circleci': 'ci-cd',
};

const patternMatches = {};
for (const group of Object.keys(directoryGroups)) {
  // Check last segment of group
  const lastSeg = group.split('/').pop();
  if (PATTERN_MAP[lastSeg]) {
    patternMatches[group] = PATTERN_MAP[lastSeg];
  } else if (PATTERN_MAP[group]) {
    patternMatches[group] = PATTERN_MAP[group];
  } else if (group === 'root') {
    patternMatches[group] = 'entry';
  } else if (group === 'openspec') {
    patternMatches[group] = 'documentation';
  } else if (group === 'egg-info') {
    patternMatches[group] = 'config';
  } else if (group === 'workspace') {
    patternMatches[group] = 'infrastructure';
  } else if (group === '.understand-anything') {
    patternMatches[group] = 'config';
  } else {
    patternMatches[group] = 'unknown';
  }
}

// Override src/agent -> agent (service), src/tools -> tools, src/commit -> commit
for (const group of Object.keys(directoryGroups)) {
  if (group === 'src/agent') patternMatches[group] = 'service';
  if (group === 'src/tools') patternMatches[group] = 'utility';
  if (group === 'src/commit') patternMatches[group] = 'service';
}

// ---- H. Deployment Topology Detection ----
const infraPatterns = [/Dockerfile/i, /docker-compose/i, /\.tf$/, /\.tfvars$/, /k8s/, /kubernetes/];
const ciPatterns = [/\.github/, /\.gitlab-ci/, /Jenkinsfile/, /\.circleci/];
const infraFiles = [];
const ciFiles = [];
for (const node of fileNodes) {
  if (infraPatterns.some(p => p.test(node.filePath))) infraFiles.push(node.filePath);
  if (ciPatterns.some(p => p.test(node.filePath))) ciFiles.push(node.filePath);
}
const deploymentTopology = {
  hasDockerfile: infraFiles.some(f => /Dockerfile/i.test(f) && !f.includes('compose')),
  hasCompose: infraFiles.some(f => /docker-compose/i.test(f)),
  hasK8s: infraFiles.some(f => /k8s|kubernetes/i.test(f)),
  hasTerraform: infraFiles.some(f => /\.tf$/.test(f)),
  hasCI: ciFiles.length > 0,
  infraFiles: [...infraFiles, ...ciFiles]
};

// ---- I. Data Pipeline Detection ----
const schemaPatterns = [/\.sql$/, /\.graphql$/, /\.gql$/, /\.proto$/, /schema/i];
const migrationPatterns = [/migration/i, /migrate/i];
const modelPatterns = [/model/i, /entity/i];
const apiPatterns = [/route/i, /controller/i, /endpoint/i, /handler/i];

const schemaFiles = fileNodes.filter(n => schemaPatterns.some(p => p.test(n.filePath))).map(n => n.filePath);
const migrationFiles = fileNodes.filter(n => migrationPatterns.some(p => p.test(n.filePath))).map(n => n.filePath);
const dataModelFiles = fileNodes.filter(n => modelPatterns.some(p => p.test(n.name))).map(n => n.filePath);
const apiHandlerFiles = fileNodes.filter(n => apiPatterns.some(p => p.test(n.filePath))).map(n => n.filePath);

const dataPipeline = { schemaFiles, migrationFiles, dataModelFiles, apiHandlerFiles };

// ---- J. Documentation Coverage ----
const docNodes = fileNodes.filter(n => n.type === 'document');
const groupsWithDocIds = new Set();
for (const doc of docNodes) {
  const group = getGroup(doc.filePath);
  groupsWithDocIds.add(group);
}
const allGroups = Object.keys(directoryGroups);
const undocumentedGroups = allGroups.filter(g => !groupsWithDocIds.has(g));
const docCoverage = {
  groupsWithDocs: groupsWithDocIds.size,
  totalGroups: allGroups.length,
  coverageRatio: +(groupsWithDocIds.size / allGroups.length).toFixed(2),
  undocumentedGroups
};

// ---- K. Dependency Direction ----
const pairCounts = {};
for (const edge of importEdges) {
  const srcGroup = idToGroup[edge.source];
  const tgtGroup = idToGroup[edge.target];
  if (!srcGroup || !tgtGroup || srcGroup === tgtGroup) continue;
  const key = `${srcGroup}|||${tgtGroup}`;
  pairCounts[key] = (pairCounts[key] || 0) + 1;
}
const dependencyDirection = [];
const processed = new Set();
for (const [key, count] of Object.entries(pairCounts)) {
  const [a, b] = key.split('|||');
  const revKey = `${b}|||${a}`;
  if (processed.has(revKey)) continue;
  processed.add(key);
  const revCount = pairCounts[revKey] || 0;
  if (count >= revCount) {
    dependencyDirection.push({ dependent: a, dependsOn: b });
  } else {
    dependencyDirection.push({ dependent: b, dependsOn: a });
  }
}

// ---- File Stats ----
const filesPerGroup = {};
for (const [g, ids] of Object.entries(directoryGroups)) filesPerGroup[g] = ids.length;
const nodeTypeCounts = {};
for (const node of fileNodes) nodeTypeCounts[node.type] = (nodeTypeCounts[node.type] || 0) + 1;

const fileFanIn = {};
const fileFanOut = {};
for (const node of fileNodes) {
  if (fanIn[node.id] > 0) fileFanIn[node.id] = fanIn[node.id];
  if (fanOut[node.id] > 0) fileFanOut[node.id] = fanOut[node.id];
}

const result = {
  scriptCompleted: true,
  directoryGroups,
  nodeTypeGroups,
  crossCategoryEdges,
  interGroupImports,
  intraGroupDensity,
  patternMatches,
  deploymentTopology,
  dataPipeline,
  docCoverage,
  dependencyDirection,
  fileStats: {
    totalFileNodes: fileNodes.length,
    filesPerGroup,
    nodeTypeCounts
  },
  fileFanIn,
  fileFanOut
};

try {
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf-8');
  console.log('Analysis complete. Output written to', outputPath);
  process.exit(0);
} catch (e) {
  console.error('Failed to write output:', e.message);
  process.exit(1);
}
