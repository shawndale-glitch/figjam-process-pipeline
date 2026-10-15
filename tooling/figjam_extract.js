// tooling/figjam_extract.js
//
// FigJam -> board.json extractor (Figma Plugin API).
// Run it through the Figma MCP `use_figma` tool or a Figma plugin, with SECTION_ID set to
// the process section (e.g. "38:468"), PAGE_ID to its page, and FILE_KEY to the board file.
// It returns the board.json object that tooling/workflow_intake.py consumes.
//
// It records facts only: component names and keys, component properties, positions,
// connector endpoints, labels and line style. All interpretation (types, lanes,
// rules) happens in Python, so the same board.json can be re-processed when the rules change.
//
// tooling/figma_rest.py produces the same shape from the REST API, for CI.

const FILE_KEY = '__FILE_KEY__';
const PAGE_ID = '__PAGE_ID__';
const SECTION_ID = '__SECTION_ID__';

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const section = await figma.getNodeByIdAsync(SECTION_ID);
if (!section || section.type !== 'SECTION') throw new Error('SECTION_ID is not a section: ' + SECTION_ID);

const sb = section.absoluteBoundingBox;
const rel = (n) => {
  const b = n.absoluteBoundingBox;
  return b ? { x: Math.round(b.x - sb.x), y: Math.round(b.y - sb.y), w: Math.round(b.width), h: Math.round(b.height) } : {};
};
const insideInstance = (n) => { let a = n.parent; while (a && a.id !== section.id) { if (a.type === 'INSTANCE') return true; a = a.parent; } return false; };

const out = {
  extractor: 'figjam_extract.js@2',
  source: { figma_file_key: FILE_KEY, page_id: PAGE_ID, section_id: section.id, section_name: section.name, exported_at: new Date().toISOString() },
  instances: [], connectors: [], other: [],
};

for (const n of section.findAll(() => true)) {
  if (insideInstance(n)) continue;
  if (n.type === 'INSTANCE') {
    const mc = await n.getMainComponentAsync();
    const props = {};
    for (const [k, v] of Object.entries(n.componentProperties)) props[k.split('#')[0]] = v.value;
    const texts = n.findAll(t => t.type === 'TEXT').map(t => t.characters); // fallback label source (e.g. pain point)
    out.instances.push({ id: n.id, component: mc ? mc.name : null, component_key: mc ? mc.key : null, remote: mc ? mc.remote : null, props, texts, ...rel(n) });
  } else if (n.type === 'CONNECTOR') {
    out.connectors.push({
      id: n.id,
      from: n.connectorStart.endpointNodeId || null,
      to: n.connectorEnd.endpointNodeId || null,
      label: n.text ? n.text.characters : '', // a connector that never had a label has no text sublayer
      dashed: n.dashPattern.length > 0,
      start_cap: n.connectorStartStrokeCap,
      end_cap: n.connectorEndStrokeCap,
    });
  } else if (['SHAPE_WITH_TEXT', 'STICKY', 'TEXT', 'FRAME', 'GROUP', 'SECTION'].includes(n.type)) {
    if (n.parent && n.parent.type === 'FRAME') continue; // text inside a detached frame is reported with the frame
    const o = { id: n.id, type: n.type, name: n.name, ...rel(n) };
    if (n.type === 'SHAPE_WITH_TEXT' || n.type === 'STICKY') o.text = n.text.characters;
    if (n.type === 'STICKY') o.author = n.authorName;
    if (n.type === 'TEXT') o.text = n.characters;
    if (n.type === 'FRAME') o.text = n.findAll(t => t.type === 'TEXT').map(t => t.characters).join(' ');
    out.other.push(o);
  }
}
return out;
