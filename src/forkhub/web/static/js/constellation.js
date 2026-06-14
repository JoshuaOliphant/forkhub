// ABOUTME: Renders the ForkHub fork constellation as an interactive SVG star map.
// ABOUTME: Layout is computed once in a fixed virtual canvas, then scaled to fit on render.

const SVGNS = 'http://www.w3.org/2000/svg';
const VW = 1000, VH = 600, PAD = 70; // fixed virtual canvas — layout is stable across resizes
const GOLDEN = 137.50776;

let COLORS = {};
let LAYOUT = null;      // computed once; render only rescales it
let SELECTED = null;    // fork id, re-applied after a rescale render

function colorMap() {
  const cs = getComputedStyle(document.documentElement);
  const get = (n) => cs.getPropertyValue(n).trim();
  return {
    feature: get('--sig-feature'), fix: get('--sig-fix'), refactor: get('--sig-refactor'),
    config: get('--sig-config'), dependency: get('--sig-dependency'), adaptation: get('--sig-adaptation'),
    release: get('--sig-release'), removal: get('--sig-removal'), accent: get('--accent'),
  };
}

function el(name, attrs = {}) {
  const n = document.createElementNS(SVGNS, name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}

function goldenPos(k, total) {
  const r = Math.sqrt((k + 0.5) / total);
  const theta = (k * GOLDEN) * Math.PI / 180;
  return {
    x: VW / 2 + Math.cos(theta) * r * (VW / 2 - PAD),
    y: VH / 2 + Math.sin(theta) * r * (VH / 2 - PAD),
  };
}

function sigRadius(sig) { return 5 + sig * 1.1; }
function sigColorFor(f) { return f.live ? COLORS.accent : (COLORS[f.signal?.category] || COLORS.dependency); }
function makeNode(f, x, y, clusterId = null) {
  return { id: f.id, x, y, r: f.live ? 7 : sigRadius(f.signal?.significance || 3), color: sigColorFor(f), fork: f, clusterId };
}

// Separate overlapping nodes; intra-cluster members are already a ring apart,
// so clusters keep their shape while singletons get pushed clear.
function relax(nodes) {
  const GAP = 18;
  for (let iter = 0; iter < 160; iter++) {
    let moved = false;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d = Math.hypot(dx, dy);
        const min = a.r + b.r + GAP;
        if (d < min) {
          // degenerate: (near-)coincident nodes have no separation direction —
          // pick a deterministic one so they can never stay stacked.
          if (d < 0.5) { const ang = (i + 1) * GOLDEN * Math.PI / 180; dx = Math.cos(ang); dy = Math.sin(ang); d = 1; }
          const push = (min - d) / 2; dx /= d; dy /= d;
          a.x -= dx * push; a.y -= dy * push; b.x += dx * push; b.y += dy * push;
          moved = true;
        }
      }
    }
    for (const n of nodes) { n.x = Math.max(PAD, Math.min(VW - PAD, n.x)); n.y = Math.max(PAD, Math.min(VH - PAD, n.y)); }
    if (!moved) break;
  }
}

function computeLayout(data) {
  const byId = Object.fromEntries(data.forks.map((f) => [f.id, f]));
  const clustered = new Set();
  const groups = [];
  for (const c of data.clusters || []) {
    groups.push({ kind: 'cluster', cluster: c, members: c.members.map((m) => byId[m]).filter(Boolean) });
    c.members.forEach((m) => clustered.add(m));
  }
  for (const f of data.forks) if (!clustered.has(f.id)) groups.push({ kind: 'single', members: [f] });

  const N = groups.length;
  const nodes = [], clusterRefs = [];
  groups.forEach((g, gi) => {
    const center = goldenPos(gi, N);
    if (g.kind === 'single') { nodes.push(makeNode(g.members[0], center.x, center.y)); return; }
    const c = g.cluster, ms = g.members, ringR = 24 + ms.length * 7;
    const memberNodes = ms.map((f, i) => {
      const a = (i / ms.length) * Math.PI * 2 - Math.PI / 2;
      const node = makeNode(f, center.x + Math.cos(a) * ringR, center.y + Math.sin(a) * ringR, c.id);
      nodes.push(node); return node;
    });
    clusterRefs.push({ cluster: c, members: memberNodes, color: sigColorFor(ms[0]) });
  });

  relax(nodes);

  const edges = [], tags = [];
  for (const ci of clusterRefs) {
    const ms = ci.members;
    for (let i = 0; i < ms.length; i++) {
      if (ms.length === 2 && i === 1) break;
      const a = ms[i], b = ms[(i + 1) % ms.length];
      edges.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, color: ci.color });
    }
    const cx = ms.reduce((s, n) => s + n.x, 0) / ms.length;
    const topY = Math.min(...ms.map((n) => n.y - n.r));
    tags.push({ x: cx, y: Math.max(20, topY - 16), label: `⛓ ${ci.cluster.label} · ${ms.length}`, color: ci.color, clusterId: ci.cluster.id });
  }
  return { nodes, edges, tags };
}

export function renderConstellation(svg, data, { onSelect } = {}) {
  COLORS = colorMap();
  if (!LAYOUT) LAYOUT = computeLayout(data);

  const rect = svg.getBoundingClientRect();
  const w = Math.max(360, Math.round(rect.width)), h = Math.max(260, Math.round(rect.height));
  const sx = w / VW, sy = h / VH;           // non-uniform fit: positions stretch, radii stay round
  const X = (x) => +(x * sx).toFixed(1), Y = (y) => +(y * sy).toFixed(1);

  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.removeAttribute('preserveAspectRatio');
  svg.replaceChildren();

  const gEdges = el('g'), gTags = el('g'), gNodes = el('g');

  for (const e of LAYOUT.edges) {
    gEdges.appendChild(el('line', { x1: X(e.x1), y1: Y(e.y1), x2: X(e.x2), y2: Y(e.y2), stroke: e.color, 'stroke-width': 1.4, 'stroke-opacity': 0.45, class: 'edge' }));
  }

  for (const t of LAYOUT.tags) {
    const g = el('g', { class: 'cluster-tag-svg', tabindex: '0', role: 'button', 'aria-label': `Cluster ${t.label}` });
    g.style.cursor = 'pointer';
    const text = el('text', { x: X(t.x), y: Y(t.y), 'text-anchor': 'middle', 'dominant-baseline': 'middle', fill: t.color });
    text.style.font = '500 13px var(--font-mono)';
    text.textContent = t.label;
    const pill = el('rect', { rx: 9, fill: 'oklch(0.130 0.030 273 / 0.82)', stroke: t.color, 'stroke-opacity': 0.35 });
    g.append(pill, text);
    gTags.appendChild(g);
    queueMicrotask(() => {
      const b = text.getBBox();
      pill.setAttribute('x', b.x - 9); pill.setAttribute('y', b.y - 4);
      pill.setAttribute('width', b.width + 18); pill.setAttribute('height', b.height + 8);
    });
    const fire = () => onSelect && onSelect({ type: 'cluster', cluster: data.clusters.find((c) => c.id === t.clusterId) });
    g.addEventListener('click', fire);
    g.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); fire(); } });
  }

  for (const n of LAYOUT.nodes) {
    const cx = X(n.x), cy = Y(n.y);
    const g = el('g', { class: 'node-hit', tabindex: '0', role: 'button',
      'aria-label': `${n.fork.owner}, ${n.fork.live ? 'syncing now' : (n.fork.signal.category + ' significance ' + n.fork.signal.significance + ' of 10')}` });
    g.dataset.id = n.id;

    if (n.fork.live) g.appendChild(el('circle', { cx, cy, r: n.r, fill: 'none', stroke: n.color, 'stroke-width': 1.5, class: 'pulse' }));
    const ring = el('circle', { cx, cy, r: n.r + 6, class: 'node-ring', stroke: n.color, 'stroke-width': 1.5 });
    const core = el('circle', { cx, cy, r: n.r, fill: n.color, class: 'node-core' });
    core.style.filter = `drop-shadow(0 0 ${n.r}px ${n.color})`;
    const label = el('text', { x: cx, y: cy + n.r + 13, 'text-anchor': 'middle', class: 'node-label', fill: 'var(--muted)' });
    label.style.font = '400 11px var(--font-mono)';
    label.textContent = n.fork.owner;
    const isSel = n.id === SELECTED;
    label.style.opacity = (n.fork.live || isSel) ? '1' : '0';
    if (isSel) g.classList.add('sel');
    g.append(ring, core, label);

    const show = (v) => { if (!n.fork.live) label.style.opacity = v ? '1' : '0'; ring.style.opacity = v ? '1' : '0'; };
    g.addEventListener('pointerenter', () => show(true));
    g.addEventListener('pointerleave', () => { if (!g.classList.contains('sel')) show(false); });
    g.addEventListener('focus', () => show(true));
    g.addEventListener('blur', () => { if (!g.classList.contains('sel')) show(false); });
    const fire = () => {
      svg.querySelectorAll('.node-hit.sel').forEach((x) => x.classList.remove('sel'));
      g.classList.add('sel'); SELECTED = n.id; show(true);
      onSelect && onSelect({ type: 'fork', fork: n.fork });
    };
    g.addEventListener('click', fire);
    g.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); fire(); } });
    gNodes.appendChild(g);
  }

  svg.append(gEdges, gTags, gNodes);
}
