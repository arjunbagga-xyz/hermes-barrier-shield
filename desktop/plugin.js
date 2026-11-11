import { PANES_AREA, STATUSBAR_AREAS, TRANSCRIPT_DIRECTIVE_AREA, host } from '@hermes/plugin-sdk';
import { useEffect, useState } from 'react';
import { jsx, jsxs } from 'react/jsx-runtime';

function parseAttrs(attrs) {
  if (!attrs) return {};
  if (typeof attrs === 'object') return attrs;
  var out = {};
  var pairs = String(attrs).split(/\s+/);
  for (var i = 0; i < pairs.length; i++) {
    var kv = pairs[i];
    var eq = kv.indexOf('=');
    if (eq === -1) continue;
    var k = kv.slice(0, eq);
    var v = kv.slice(eq + 1);
    if (v.length >= 2 && v.charAt(0) === '"' && v.charAt(v.length - 1) === '"') {
      v = v.slice(1, v.length - 1);
    }
    out[k] = v;
  }
  return out;
}

let _latest = {
  minH: '+0.52', damping: '51%', mode: 'ADAPTIVE_CLF_CBF', gamma: 0.45,
  lyapunov: 0.0, deflected: false, maxSpend: 25, maxFiles: 50, minHBefore: 0.52
};
var _listeners = new Set();
function _notify(attrs) {
  var a = parseAttrs(attrs);
  if (!a) return;
  var mH = a.min_h ? parseFloat(a.min_h) : _latest.minH;
  var damp = a.damping != null ? String(Math.round(parseFloat(a.damping))) : _latest.damping + '%';
  var md = a.mode || _latest.mode;
  var gm = a.gamma != null ? parseFloat(a.gamma) : _latest.gamma;
  var ly = a.lyapunov_v != null ? parseFloat(a.lyapunov_v) : _latest.lyapunov;
  var def = a.deflected === 'true' || a.deflected === true;
  var ms = a.max_spend != null ? parseFloat(a.max_spend) : _latest.maxSpend;
  var mf = a.max_files != null ? parseInt(a.max_files) : _latest.maxFiles;
  var mhb = a.min_h_before != null ? parseFloat(a.min_h_before) : _latest.minHBefore;
  _latest = { minH: mH, damping: damp, mode: md, gamma: gm, lyapunov: ly, deflected: def, maxSpend: ms, maxFiles: mf, minHBefore: mhb };
  _listeners.forEach((fn) => {
    try { fn(_latest); } catch (e) {}
  });
}
function useLatest() {
  const [s, setS] = useState(_latest);
  useEffect(() => {
    const h = (val) => setS({ ...val });
    _listeners.add(h);
    return () => _listeners.delete(h);
  }, []);
  return s;
}

function CbfDirectiveCard({ attrs }) {
  const [expanded, setExpanded] = useState(true);
  useEffect(() => { _notify(attrs || {}); }, [attrs]);
  var a = parseAttrs(attrs || {});
  var minH = a.min_h ? String(a.min_h) : '+0.52';
  var damping = a.damping ? String(Math.round(parseFloat(a.damping))) + '%' : '51%';
  var gamma = a.gamma != null ? parseFloat(a.gamma) : 0.45;
  var mode = a.mode ? String(a.mode) : 'ADAPTIVE_CLF_CBF';
  var maxSpend = a.max_spend != null ? parseFloat(a.max_spend) : 25;
  var maxFiles = a.max_files != null ? parseInt(a.max_files) : 50;
  var minHNum = parseFloat(minH) || 0.5;
  var hBefore = a.min_h_before != null ? parseFloat(a.min_h_before) : 0.5;
  var bottleneckIdx = 0;
  for (var i = 0; i < 4; i++) {
    if (Math.abs(hBefore - (1 - (i % 2) * 0.25)) < 0.01) { bottleneckIdx = i; break; }
  }
  var cx = Math.round(30 + bottleneckIdx * 115);
  var cy = Math.round(64 - 8 - minHNum * 56);
  var safe = minHNum >= 0.3;
  var safeColor = safe ? 'var(--ui-accent)' : 'var(--ui-danger, rgba(239, 68, 68, 1))';
  return jsxs('div', {
    style: {
      color: 'var(--foreground, var(--ui-text-primary))',
      fontSize: '12px'
    },
    children: [
      jsxs('div', {
        onClick: () => setExpanded(!expanded),
        style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', gap: '8px' },
        children: [
          jsxs('div', {
            style: { display: 'flex', alignItems: 'center', gap: '8px' },
            children: [
              jsx('span', { style: { fontFamily: 'var(--ui-font-mono)', color: 'var(--ui-accent)', fontWeight: 700 }, children: '🛡️ h(x)=' + minH }),
              jsx('span', { style: { fontWeight: 600 }, children: 'barrier-shield · ' + mode + ' (γ=' + gamma + ') · Damped ' + damping })
            ]
          }),
          jsx('span', { style: { fontFamily: 'var(--ui-font-mono)', fontSize: '11px', color: 'var(--ui-text-secondary)' }, children: 'Nagumo Safe ' + (expanded ? '▲' : '▼') })
        ]
      }),
      expanded && jsx('div', {
        style: { marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--ui-stroke-secondary, var(--ui-border))' },
        children: jsxs('svg', {
          viewBox: '0 0 500 96', width: '100%', height: '96', style: { display: 'block' },
          children: [
            jsx('rect', { x: 10, y: 8, width: 480, height: Math.max(0, 64 * minHNum), rx: 6, fill: safeColor }),
            jsx('line', { x1: 10, y1: 8 + 64, x2: 490, y2: 8 + 64, stroke: safeColor, strokeWidth: 1.2, strokeDasharray: '4 3' }),
            jsx('line', { x1: 30, y1: 64, x2: 245, y2: 12, stroke: safeColor, strokeDasharray: '2 2', strokeWidth: 1.3 }),
            jsx('path', { d: 'M 30 64 Q 175 30 475, 28', fill: 'none', stroke: safeColor, strokeWidth: 2.5 }),
            jsx('circle', { cx: cx, cy: cy, r: 4.2, fill: safeColor }),
            jsx('text', { x: 24, y: 8 + 64 - 8, fill: safeColor ? 'var(--ui-text-on-accent)' : 'var(--ui-text-secondary)', fontSize: 10, fontFamily: 'var(--ui-font-mono)' }, 'FORBIDDEN UNSAFE BOUNDARY h(x)=0 (' + maxFiles + ' files / $' + maxSpend + ' ceiling)'),
            jsx('text', { x: 14, y: 88, fill: safeColor ? 'var(--ui-text-on-accent)' : 'var(--ui-text-secondary)', fontSize: 10.5, fontFamily: 'var(--ui-font-mono)' }, 'Control Deck: active=' + mode + ' (γ=' + gamma + ') · min_h ' + minH + ' · ' + (safe ? 'SAFE' : 'NEAR BOUNDARY'))
          ]
        })
      })
    ]
  });
}

function Pane() {
  const s = useLatest();
  return jsx('div', { className: 'p-2 text-xs', style: {
    display: 'flex', flexDirection: 'column', gap: '4px' }, children: [
    jsx('div', { style: { fontWeight: 700, color: 'var(--ui-accent)' }, children: '🛡️ Velvet CBF Shield' }),
    jsx('div', { children: 'Mode: ' + s.mode }),
    jsx('div', { children: 'γ: ' + s.gamma }),
    jsx('div', { children: 'min_h: ' + s.minH }),
    jsx('div', { children: 'Damping: ' + s.damping }),
    jsx('div', { children: 'Ceiling: $' + s.maxSpend + ' / ' + s.maxFiles + ' files' }),
    jsx('div', { style: { fontSize: '10px', color: 'var(--ui-text-secondary)' }, children: s.deflected ? 'Last: DEFLECTED' : 'Last: nominal' }),
  ]});
}

function Chip() {
  const s = useLatest();
  return jsx('button', {
    type: 'button',
    className: 'px-2 text-[0.6875rem] text-(--ui-text-secondary)',
    onClick: () => host.notify({ kind: 'info',
      message: 'Velvet CBF: mode=' + s.mode + ' γ=' + s.gamma + ' min_h=' + s.minH + ' (safe set C forward-invariant)' }),
    children: '🛡️ h(x) ' + s.minH
  });
}

export default {
  id: 'barrier-shield',
  name: 'Velvet Control-Barrier Shield',
  register(ctx) {
    ctx.register({
      id: 'directive',
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: {
        name: 'barrier-shield',
        render: ({ attrs, sessionId }) => { _notify(attrs || {}); return jsx(CbfDirectiveCard, { attrs, sessionId }); }
      }
    });
    ctx.register({
      id: 'pane',
      area: PANES_AREA,
      data: { placement: 'right', width: '300px' },
      render: () => jsx(Pane, {})
    });
    ctx.register({
      id: 'chip',
      area: STATUSBAR_AREAS.right,
      order: 124,
      render: () => jsx(Chip, {})
    });
  }
};
