import { PANES_AREA, STATUSBAR_AREAS, TRANSCRIPT_DIRECTIVE_AREA, host } from '@hermes/plugin-sdk';
import { useState } from 'react';
import { jsx, jsxs } from 'react/jsx-runtime';

function CbfDirectiveCard({ attrs }) {
  const [expanded, setExpanded] = useState(true);
  const minH = (attrs && attrs.min_h) || '+0.52';
  const damping = (attrs && attrs.damping) || '51%';

  return jsxs('div', {
    style: {
      border: '1px solid var(--ui-stroke-secondary, var(--ui-border))',
      borderRadius: '10px',
      background: 'var(--card, var(--ui-surface-2))',
      color: 'var(--foreground, var(--ui-text-primary))',
      padding: '10px 14px',
      margin: '4px 0',
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
              jsx('span', { style: { fontFamily: 'var(--ui-font-mono)', color: 'var(--ui-accent)', fontWeight: 700 }, children: `🛡️ h(x)=${minH}` }),
              jsx('span', { style: { fontWeight: 600 }, children: `barrier-shield · Continuous QP Shield (Damped ${damping})` })
            ]
          }),
          jsx('span', { style: { fontFamily: 'var(--ui-font-mono)', fontSize: '11px', color: 'var(--ui-text-secondary)' }, children: `Nagumo Safe ${expanded ? '▲' : '▼'}` })
        ]
      }),
      expanded && jsx('div', {
        style: { marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--ui-stroke-secondary, var(--ui-border))' },
        children: jsxs('svg', {
          width: '100%',
          height: '96',
          viewBox: '0 0 500 96',
          preserveAspectRatio: 'xMidYMid meet',
          style: { display: 'block' },
          children: [
            jsx('rect', { x: 10, y: 8, width: 480, height: 64, rx: 6, fill: 'none', stroke: 'var(--ui-stroke-secondary, var(--ui-border))' }),
            jsx('line', { x1: 18, y1: 24, x2: 482, y2: 24, stroke: 'var(--ui-text-secondary)', strokeDasharray: '4 3', strokeWidth: '1.2' }),
            jsx('text', { x: 24, y: 19, fill: 'var(--ui-text-secondary)', fontSize: '10', fontFamily: 'var(--ui-font-mono)', children: 'FORBIDDEN UNSAFE BOUNDARY h(x) = 0 (50 Files / $25 Ceiling)' }),
            jsx('line', { x1: 30, y1: 64, x2: 245, y2: 12, stroke: 'var(--ui-text-secondary)', strokeDasharray: '2 2', strokeWidth: '1.3' }),
            jsx('path', { d: 'M 30 64 Q 175 30 475, 28', fill: 'none', stroke: 'var(--ui-accent)', strokeWidth: '2.5' }),
            jsx('circle', { cx: 235, cy: 33, r: '4.2', fill: 'var(--ui-accent)' }),
            jsx('text', { x: 14, y: 88, fill: 'var(--ui-text-secondary)', fontSize: '10.5', fontFamily: 'var(--ui-font-mono)', children: 'Control Deck: [STRICT γ=0.25] [ADAPTIVE γ=0.45*] [R&D γ=0.85] · 45->21 files' })
          ]
        })
      })
    ]
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
        render: ({ attrs, sessionId }) => jsx(CbfDirectiveCard, { attrs, sessionId })
      }
    });
    ctx.register({
      id: 'pane',
      area: PANES_AREA,
      title: 'Velvet CBF Shield',
      data: { placement: 'right', width: '300px' },
      render: () => jsx('div', { className: 'p-2 text-xs', children: '🎛️ Closed-Loop CBF Controller: Mode=ADAPTIVE_CLF_CBF (γ=0.45, λ₁-coupled)' })
    });
    ctx.register({
      id: 'chip',
      area: STATUSBAR_AREAS.right,
      order: 124,
      render: () => jsx('button', {
        type: 'button',
        className: 'px-2 text-[0.6875rem] text-(--ui-text-secondary)',
        onClick: () => host.notify({ kind: 'info', message: 'Velvet CBF: Safe set C = {x : h(x) >= 0} forward-invariant' }),
        children: '🛡️ h(x) +0.52'
      })
    });
  }
};
