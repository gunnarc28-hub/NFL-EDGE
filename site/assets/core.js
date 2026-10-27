/* Sports Edge: helpers shared by the home page and every sport page.
   Plain script (no build step). Everything hangs off window.SE so a page can pull what it needs:
   const {$, $$, esc, fmtOdds} = SE; */
(function(){
'use strict';
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

/* localStorage that never throws (private windows and blocked storage just forget) */
function mkStore(prefix){
  return {
    get(k, d){ try { const v = localStorage.getItem(prefix + k); return v == null ? d : JSON.parse(v); } catch(e){ return d; } },
    set(k, v){ try { localStorage.setItem(prefix + k, JSON.stringify(v)); } catch(e){} },
    del(k){ try { localStorage.removeItem(prefix + k); } catch(e){} },
    raw(k){ try { return localStorage.getItem(k); } catch(e){ return null; } }
  };
}

/* ---------- numbers and prices ---------- */
const sign = (v, d = 1) => v == null || isNaN(v) ? '–' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
const fmtLine = v => v == null || v === '' || isNaN(v) ? '–' : (Number(v) === 0 ? 'PK' : sign(Number(v), 1));
const fmtOdds = v => v == null || v === '' || isNaN(v) ? '–' : (Number(v) > 0 ? '+' + Number(v) : '−' + Math.abs(Number(v)));
const pct = (x, d = 0) => x == null || isNaN(x) ? '–' : (x * 100).toFixed(d) + '%';
const numOf = v => { const t = String(v == null ? '' : v).trim().replace(/[−–]/g, '-').replace(/^\+/, ''); return t === '' || isNaN(t) ? null : Number(t); };
function parseOdds(v){
  const t = String(v == null ? '' : v).trim().replace(/[−–]/g, '-').replace(/^\+/, '');
  if (!t) return null; const o = Number(t); return isFinite(o) && Math.abs(o) >= 100 ? o : null;
}
const dec = o => { o = Number(o); return o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o); };
const amOf = d => d >= 2 ? Math.round((d - 1) * 100) : -Math.round(100 / (d - 1));
function impProb(o){ o = Number(o); return o < 0 ? -o / (-o + 100) : 100 / (o + 100); }
function oddsNum(p){ return p >= 0.5 ? -Math.round(100 * p / (1 - p)) : Math.round(100 * (1 - p) / p); }
function evOf(p, o){ return p * (o > 0 ? o / 100 : 100 / Math.abs(o)) - (1 - p); }
function evMsg(p, fair, raw){
  const o = parseOdds(raw);
  if (o == null) return {t: String(raw || '').trim() ? 'Use American odds, like +250 or -120' : "Enter your book's odds to see if the price is worth it", c: ''};
  const ev = evOf(p, o), c = Math.round(ev * 100);
  if (ev >= 0.05) return {t: `Good price: about +${c}¢ back per $1 over time`, c: 'pos'};
  if (c === 0) return {t: 'About break-even: the price matches the chance', c: 'thin'};
  if (ev >= 0) return {t: `Thin edge: +${c}¢ per $1, inside the model's margin of error`, c: 'thin'};
  return {t: `Not worth it: about −${Math.abs(c)}¢ per $1. Needs ${fmtOdds(fair)} or better`, c: 'neg'};
}
function erf(x){ const s = Math.sign(x); x = Math.abs(x); const t = 1 / (1 + 0.3275911 * x); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return s * y; }
function ncdf(x){ return 0.5 * (1 + erf(x / Math.SQRT2)); }
const uid = pre => pre + '_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const unitsTxt = v => (Math.round(v * 100) / 100).toFixed(2).replace(/\.?0+$/, '') + 'u';

/* ---------- time ---------- */
function kick(iso, opts){
  const d = new Date(iso);
  try { return d.toLocaleString([], Object.assign({weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'}, opts || {})); }
  catch(e){ return iso; }
}
function ago(iso){ const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' hr ago' : Math.round(m / 1440) + ' days ago'; }
/* local calendar day of an ISO time, as YYYY-MM-DD */
function dayKey(iso){ const d = new Date(iso); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function dayLabel(key, opts){
  const [y, m, d] = String(key).split('-').map(Number); const dt = new Date(y, m - 1, d);
  const today = dayKey(new Date().toISOString()), t2 = new Date(); t2.setDate(t2.getDate() + 1); const tom = dayKey(t2.toISOString());
  const t0 = new Date(); t0.setDate(t0.getDate() - 1); const yest = dayKey(t0.toISOString());
  if (!(opts && opts.plain)){ if (key === today) return 'Today'; if (key === tom) return 'Tomorrow'; if (key === yest) return 'Yesterday'; }
  return dt.toLocaleDateString([], {weekday: 'short', month: 'short', day: 'numeric'});
}

/* ---------- toast ---------- */
function toast(msg){ const t = $('#toast'); if (!t) return; t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => t.hidden = true, 2400); }

/* ---------- sparkline ---------- */
function spark(series, o){
  o = o || {}; const w = o.w || 104, h = o.h || 30, pad = 3;
  const vals = series.map(s => s[1]); if (!vals.length) return '';
  const all = o.base != null ? vals.concat([o.base]) : vals.slice();
  let lo = Math.min.apply(null, all), hi = Math.max.apply(null, all); if (hi === lo){ hi += 1; lo -= 1; }
  const x = i => pad + i * (w - 2 * pad) / Math.max(1, vals.length - 1);
  const y = v => h - pad - (v - lo) * (h - 2 * pad) / (hi - lo);
  const pts = vals.map((v, i) => x(i).toFixed(1) + ',' + y(v).toFixed(1));
  const area = 'M' + x(0).toFixed(1) + ',' + (h - pad) + ' L' + pts.join(' L') + ' L' + x(vals.length - 1).toFixed(1) + ',' + (h - pad) + ' Z';
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><path d="${area}" class="spark-area"/>` +
    (o.base != null ? `<line x1="${pad}" x2="${w - pad}" y1="${y(o.base).toFixed(1)}" y2="${y(o.base).toFixed(1)}" class="spark-base"/>` : '') +
    `<polyline points="${pts.join(' ')}" class="spark-line"/><circle cx="${x(vals.length - 1).toFixed(1)}" cy="${y(vals[vals.length - 1]).toFixed(1)}" r="2.8" class="spark-end"/></svg>`;
}

/* ---------- +/− steppers: phone keypads often have no minus or plus key ----------
   kind: odds (American, steps of 5, skips -100..+100), spread (0.5, either sign), line (1, so .5 lines stay .5), units (0.25, min 0.25) */
function stepWrap(input, kind){
  const flip = kind === 'odds' || kind === 'spread';
  return `<span class="stp" data-kind="${kind}"><button type="button" class="stp-b" data-stp="-1" aria-label="Lower">−</button>${input}<button type="button" class="stp-b" data-stp="1" aria-label="Higher">+</button>${flip ? '<button type="button" class="stp-b stp-f" data-stp="flip" aria-label="Switch between plus and minus">+/−</button>' : ''}</span>`;
}
function stepInput(btn){
  const box = btn.closest('.stp'), inp = box && box.querySelector('input'); if (!inp) return;
  const kind = box.dataset.kind, act = btn.dataset.stp, cur = numOf(inp.value);
  let v;
  if (kind === 'odds'){
    let base = cur != null && Math.abs(cur) >= 100 ? cur : (numOf(inp.placeholder) ?? -110);
    if (cur == null && Math.abs(base) >= 100) base = Math.round(base / 5) * 5;
    if (act === 'flip') v = cur == null ? -Math.abs(base) : -cur;
    else if (cur == null || Math.abs(cur) < 100) v = base;
    else { v = cur + 5 * Number(act); if (cur < 0 && v > -100) v = 100; else if (cur > 0 && v < 100) v = -105; }
    inp.value = v > 0 ? '+' + v : String(v);
  } else {
    const step = kind === 'units' ? 0.25 : kind === 'line' ? 1 : 0.5;
    const base = cur != null ? cur : (inp.dataset.proj && !isNaN(inp.dataset.proj) ? Math.floor(Number(inp.dataset.proj)) + 0.5 : (numOf(inp.placeholder) ?? (kind === 'units' ? 1 : 0)));
    if (act === 'flip') v = -(cur ?? base);
    else if (cur == null) v = base;
    else v = cur + step * Number(act);
    if (kind === 'line') v = Math.max(0, v);
    if (kind === 'units') v = Math.max(0.25, v);
    inp.value = String(Math.round(v * 100) / 100);
  }
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  inp.dispatchEvent(new Event('change', {bubbles: true}));
}
document.addEventListener('click', e => { const b = e.target.closest('.stp-b'); if (b){ e.stopPropagation(); stepInput(b); } }, true);

/* ---------- the three sports: names, paths, page colors ---------- */
const SPORTS = {
  nfl: {key: 'nfl', label: 'NFL', name: 'Football', path: 'nfl/', period: 'Week'},
  nba: {key: 'nba', label: 'NBA', name: 'Basketball', path: 'nba/', period: 'Day'},
  nhl: {key: 'nhl', label: 'NHL', name: 'Hockey', path: 'nhl/', period: 'Day'}
};

/* a live game's clock: ESPN's "38.7 - 4th" reads "4th · 38.7", the NHL feed's "P3" reads "3rd" */
function liveTxt(d){
  d = String(d || '').trim(); if (!d) return 'Live';
  const ORD = {1: '1st', 2: '2nd', 3: '3rd', 4: '4th'};
  let m = /^P(\d)$/.exec(d); if (m) return ORD[m[1]] || d;
  m = /^([\d:.]+)\s*-\s*(.+)$/.exec(d);
  if (m) return /^0+(:0+)?(\.0+)?$/.test(m[1]) ? `End of ${m[2]}` : `${m[2]} · ${m[1]}`;
  return d;
}

window.SE = {$, $$, esc, mkStore, sign, fmtLine, fmtOdds, pct, numOf, parseOdds, dec, amOf, impProb, oddsNum, evOf, evMsg, erf, ncdf, uid, unitsTxt,
             kick, ago, dayKey, dayLabel, toast, spark, stepWrap, stepInput, liveTxt, SPORTS};
})();
