// ABOUTME: Explore zone controller — boots the constellation, drives the inspector and views.
// ABOUTME: Reads embedded fixture JSON now; the same shape will arrive from FastAPI/Jinja later.

import { renderConstellation } from './constellation.js';

const ICONS = {
  feature: 'M12 5v14M5 12h14',
  fix: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.3 2.3-2-2z',
  refactor: 'M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5',
  config: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
  dependency: 'm7.5 4.3 9 5.2M21 8l-9-5-9 5v8l9 5 9-5ZM3.3 7l8.7 5 8.7-5M12 22V12',
  adaptation: 'M5 8 2 11l3 3M2 11h10M19 16l3-3-3-3M22 13H12',
  release: 'M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8zM7 7h.01',
  removal: 'M5 12h14',
};
const CATCOLOR = (c) => `var(--sig-${c})`;
const GH = 'https://github.com';

const svgIcon = (d, size = 13) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const EXT = svgIcon('M7 17 17 7M9 7h8v8', 11); // external-link arrow

// GitHub URLs for a fork: the fork's repo lives under the fork owner with the
// upstream repo's name; the SHA links to that exact commit.
function ghUrls(owner) { const repo = `${GH}/${owner}/${DATA.repo.name}`; return { repo, commit: (sha) => `${repo}/commit/${sha}` }; }

function chip(cat, withScore = null) {
  const col = CATCOLOR(cat);
  const label = withScore != null ? `${cat} · ${withScore}/10` : cat;
  return `<span class="chip" style="color:${col};background:color-mix(in oklch, ${col} 15%, transparent);box-shadow:inset 0 0 0 1px color-mix(in oklch, ${col} 32%, transparent)">${svgIcon(ICONS[cat])}${label}</span>`;
}
function bars(sig, cat) {
  const col = CATCOLOR(cat);
  let h = '<span class="bars">';
  for (let i = 0; i < 10; i++) h += `<i style="${i < sig ? `background:${col}` : ''}"></i>`;
  return h + '</span>';
}
const avatar = (id) => `<div class="av">${id[0].toUpperCase()}</div>`;

function renderDiff(diff) {
  if (!diff) return '';
  const rows = diff.map((l) => {
    const cls = l[0] === '+' ? 'add' : l[0] === '-' ? 'del' : 'ctx';
    return `<div class="${cls}">${l.replace(/</g, '&lt;')}</div>`;
  }).join('');
  return `<div><div class="insp-label">Diff preview <span class="zoom-hint">click to enlarge</span></div><div class="diff" role="button" tabindex="0" aria-label="Enlarge diff preview">${rows}</div></div>`;
}

function populateFork(insp, f) {
  const gh = ghUrls(f.owner);
  insp.querySelector('.insp-head').innerHTML =
    `${avatar(f.owner)}<div class="who-block">` +
      `<a class="who" href="${gh.repo}" target="_blank" rel="noopener">${f.owner}/${DATA.repo.name}${EXT}</a>` +
      `<a class="sha mono" href="${gh.commit(f.sha)}" target="_blank" rel="noopener">#${f.sha}</a>` +
    `</div>` +
    `<button class="close" aria-label="Close inspector">${svgIcon('M18 6 6 18M6 6l12 12', 18)}</button>`;
  if (f.live) {
    insp.querySelector('.insp-body').innerHTML =
      `<div class="why"><div class="tag">${svgIcon('M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4', 12)} analyzing now</div>This fork is being synced. The diff-analyst is classifying its changes; a signal will appear here when the session completes.</div>`;
  } else {
    const s = f.signal;
    insp.querySelector('.insp-body').innerHTML = `
      <div class="insp-row">${chip(s.category)}${bars(s.significance, s.category)}</div>
      <div style="font-size:14.5px;line-height:1.5">${s.summary}</div>
      <div class="why"><div class="tag">${svgIcon('M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1h6c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z', 12)} why the agent flagged it</div>${s.reasoning}</div>
      <div><div class="insp-label">Files involved</div><div class="files">${s.files.map((p) => `<code>${p}</code>`).join('')}</div></div>
      ${renderDiff(s.diff)}
      <div class="cost-line"><span>analysis cost</span><b>$${s.cost_usd.toFixed(3)}</b></div>`;
  }
  bindClose(insp);
  insp.classList.add('open');
}

function populateCluster(insp, c) {
  const col = CATCOLOR(c.members_meta?.[0]?.category || 'feature');
  insp.querySelector('.insp-head').innerHTML =
    `<div class="av" style="background:color-mix(in oklch, ${col} 20%, transparent);color:${col}">${svgIcon('M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5', 18)}</div>` +
    `<div><div class="who">${c.label}</div><div class="sha">${c.members.length} forks converged</div></div>` +
    `<button class="close" aria-label="Close inspector">${svgIcon('M18 6 6 18M6 6l12 12', 18)}</button>`;
  const rows = c.members.map((m) => {
    const f = DATA.forks.find((x) => x.id === m);
    const g = ghUrls(f.owner);
    return `<div class="frow"><div class="av">${m[0].toUpperCase()}</div><div class="meta">` +
      `<a class="who" href="${g.repo}" target="_blank" rel="noopener">${f.owner}${EXT}</a>` +
      `<a class="sha mono" href="${g.commit(f.sha)}" target="_blank" rel="noopener">#${f.sha}</a></div>` +
      `<div>${chip(f.signal.category, f.signal.significance)}</div></div>`;
  }).join('');
  insp.querySelector('.insp-body').innerHTML = `
    <div class="why"><div class="tag">${svgIcon('M12 2 2 7l10 5 10-5-10-5z', 12)} convergent divergence</div>${c.summary}</div>
    <div><div class="insp-label">Forks in this cluster</div>${rows}</div>`;
  bindClose(insp);
  insp.classList.add('open');
}

function bindClose(insp) {
  insp.querySelector('.close').addEventListener('click', () => {
    insp.classList.remove('open');
    document.querySelectorAll('.node-hit.sel').forEach((x) => x.classList.remove('sel'));
  });
}

function buildList(data) {
  const wrap = document.querySelector('.listview');
  wrap.innerHTML = data.forks.map((f) => {
    const right = f.live
      ? `<span class="chip" style="color:var(--accent);background:color-mix(in oklch,var(--accent) 15%,transparent)">syncing…</span>`
      : chip(f.signal.category, f.signal.significance);
    const sum = f.live ? 'Being analyzed now.' : f.signal.summary;
    return `<div class="frow">${avatar(f.owner)}<div class="meta"><div class="who">${f.owner}</div><div class="sha mono">#${f.sha}</div></div><div class="sum">${sum}</div>${right}</div>`;
  }).join('');
}

function makeStarfield(svg, n = 46) {
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'none');
  let s = '';
  // deterministic pseudo-scatter (no Math.random so renders are stable)
  for (let i = 0; i < n; i++) {
    const x = (i * 37.3) % 100, y = (i * 61.7) % 100;
    const r = (i % 7 === 0) ? 0.22 : 0.13;
    const fill = (i % 9 === 0) ? 'var(--accent)' : 'var(--ink)';
    const o = 0.25 + ((i * 13) % 50) / 100;
    s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="${fill}" opacity="${o.toFixed(2)}"/>`;
  }
  svg.innerHTML = s;
}

let DATA;
function boot() {
  DATA = JSON.parse(document.getElementById('forkhub-data').textContent);
  document.documentElement.style.setProperty('--repo-name', DATA.repo.name);
  makeStarfield(document.querySelector('.starfield'));
  const svg = document.querySelector('.constellation');
  const insp = document.querySelector('.inspector');
  const draw = () => renderConstellation(svg, DATA, {
    onSelect: (sel) => sel.type === 'fork' ? populateFork(insp, sel.fork) : populateCluster(insp, sel.cluster),
  });
  buildList(DATA);

  // Initial render happens immediately — ResizeObserver callbacks are paused for
  // hidden/background tabs, so relying on the observer alone would leave the map
  // blank until the tab is foregrounded. The observer then handles resizes only.
  let lastW = svg.clientWidth, lastH = svg.clientHeight;
  draw();
  const ro = new ResizeObserver(() => {
    const w = svg.clientWidth, h = svg.clientHeight;
    if (!w || !h || (w === lastW && h === lastH)) return;
    lastW = w; lastH = h; draw();
  });
  ro.observe(document.querySelector('.sky-wrap'));

  // map / list toggle
  document.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('.seg button').forEach((x) => x.classList.toggle('on', x === b));
    const list = b.dataset.view === 'list';
    document.querySelector('.sky-wrap').hidden = list;
    document.querySelector('.listview').hidden = !list;
  }));
  // diff preview: click to enlarge, click again (or backdrop / Esc) to shrink
  const backdrop = document.querySelector('.diff-backdrop');
  const unzoom = () => { insp.querySelectorAll('.diff.zoom').forEach((d) => d.classList.remove('zoom')); backdrop.hidden = true; };
  const toggleZoom = (diff) => { backdrop.hidden = !diff.classList.toggle('zoom'); };
  insp.addEventListener('click', (e) => { const d = e.target.closest('.diff'); if (d) toggleZoom(d); });
  insp.addEventListener('keydown', (e) => {
    const d = e.target.closest('.diff');
    if (d && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleZoom(d); }
  });
  backdrop.addEventListener('click', unzoom);

  // esc shrinks an enlarged diff first, otherwise closes the inspector
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!backdrop.hidden) unzoom(); else insp.classList.remove('open');
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
