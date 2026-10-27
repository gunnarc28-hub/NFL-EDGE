/* Sports Edge: the NBA and NHL pages (one app, two sports). Reads data/data.json from its own folder;
   chart logs (data/logs.json) load the first time a chart opens. The bet slip and My bets come from bets.js. */
(async function(){
'use strict';
const SP = document.documentElement.dataset.sport;
const NHL = SP === 'nhl';
const {$, $$, esc, sign, fmtLine, fmtOdds, pct, numOf, parseOdds, dec, impProb, oddsNum, evOf, evMsg, ncdf, kick, ago, dayKey, dayLabel, toast, spark, stepWrap, SPORTS} = SE;
const store = SE.mkStore(`sportsedge.${SP}.`);
const DATA_URL = 'data/data.json';
let D;
try {
  const r = await fetch(DATA_URL + '?t=' + Date.now(), {cache: 'no-store'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  D = await r.json();
} catch(e){
  $('#v-games').innerHTML = '<div class="empty"><div class="h3">Could not load the latest numbers</div><p class="lede" style="margin:0">Check your connection and reload the page.</p></div>';
  return;
}
let LOADED_AT = Date.now();
const T = D.teams, M = D.meta;

/* ---------------- sport words ---------------- */
const CFG = NHL ? {
  label: 'NHL', spread: 'Puck line', unit: 'goals', minLabel: 'TOI',
  ou: ['sog', 'points', 'assists', 'blocks', 'saves'],
  mk: {sog: 'Shots on goal', points: 'Points', assists: 'Assists', blocks: 'Blocked shots', saves: 'Saves', goals: 'Goals', hits: 'Hits', atg: 'Anytime goal', g2: '2+ goals', first_goal: 'First goal'},
  short: {sog: 'shots', points: 'points', assists: 'assists', blocks: 'blocks', saves: 'saves', goals: 'goals', hits: 'hits'},
  propTabs: [['sog', 'Shots'], ['points', 'Points'], ['goals', 'Goals'], ['assists', 'Assists'], ['blocks', 'Blocks'], ['saves', 'Goalie saves']],
  lsGroups: [['all', 'All'], ['atg', 'Anytime goal'], ['g2', '2+ goals'], ['first_goal', 'First goal'], ['pts2', '2+ points'], ['pts3', '3+ points'], ['sog5', '5+ shots']],
  chartStats: [['sog', 'SOG'], ['goals', 'G'], ['assists', 'A'], ['points', 'PTS'], ['hits', 'HITS'], ['blocks', 'BLK'], ['toi', 'TOI']],
  goalieStats: [['saves', 'SAVES'], ['ga', 'GA'], ['shots', 'SHOTS']]
} : {
  label: 'NBA', spread: 'Spread', unit: 'points', minLabel: 'MIN',
  ou: ['pts', 'reb', 'ast', 'fg3m', 'pra', 'pr', 'pa', 'ra', 'stl', 'blk', 'tov'],
  mk: {pts: 'Points', reb: 'Rebounds', ast: 'Assists', fg3m: '3-pointers', pra: 'Pts + reb + ast', pr: 'Pts + reb', pa: 'Pts + ast', ra: 'Reb + ast', stl: 'Steals', blk: 'Blocks', tov: 'Turnovers', dd: 'Double-double', td3: 'Triple-double'},
  short: {pts: 'points', reb: 'rebounds', ast: 'assists', fg3m: '3-pointers', pra: 'pts+reb+ast', pr: 'pts+reb', pa: 'pts+ast', ra: 'reb+ast', stl: 'steals', blk: 'blocks', tov: 'turnovers'},
  propTabs: [['pts', 'Points'], ['reb', 'Rebounds'], ['ast', 'Assists'], ['fg3m', '3-pointers'], ['pra', 'PRA'], ['pr', 'P+R'], ['pa', 'P+A'], ['ra', 'R+A'], ['stl', 'Steals'], ['blk', 'Blocks'], ['tov', 'Turnovers']],
  lsGroups: [['all', 'All'], ['pts', 'Points'], ['reb', 'Rebounds'], ['ast', 'Assists'], ['fg3m', '3-pointers'], ['pra', 'PRA'], ['dd', 'Double-double'], ['td3', 'Triple-double']],
  chartStats: [['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['fg3m', '3PM'], ['pra', 'PRA'], ['stl', 'STL'], ['blk', 'BLK'], ['tov', 'TOV'], ['min', 'MIN']]
};

/* ---------------- formatting ---------------- */
const chip = (t, sm) => { const x = T[t]; return x ? `<span class="tm${sm ? ' sm' : ''}" style="--c1:${x.c1};--c2:${x.c2}" title="${esc(x.name)}">${esc(t)}</span>` : esc(t); };
const nick = t => (T[t] || {}).nick || t;
const recTxt = r => !r ? '–' : NHL ? `${r.W}-${r.L}-${r.OTL || 0}` : `${r.W}-${r.L}`;
const wl = r => r ? `${r.W}-${r.L}${r.P ? '-' + r.P : ''}` : '–';
const ouTxt = r => r ? `${r.O}-${r.U}${r.P ? '-' + r.P : ''}` : '–';
const resDots = (arr, n = 5) => { const a = (arr || []).slice(-n); let s = '<span class="res" aria-label="' + esc(a.join(' ')) + '">'; for (let i = 0; i < n - a.length; i++) s += '<i class="n"></i>'; a.forEach(r => s += `<i class="${r === 'OTL' ? 'P' : r}"></i>`); return s + '</span>'; };
const when = (iso, o) => kick(iso, Object.assign({weekday: undefined, timeZoneName: undefined}, o || {}));
const whenDay = iso => kick(iso, {weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: undefined});
const gameOf = id => D.games.find(g => g.id === String(id));
const lastName = n => String(n || '').split(' ').slice(-1)[0];
const isLive = g => g.state === 'in';
const fmtN = (v, d = 1) => v == null || isNaN(v) ? '–' : Number(v).toFixed(d);
const fairTxt = p => fmtOdds(oddsNum(p));
const LEVEL_WORD = {out: 'Out', doubt: 'Doubtful', gtd: 'Questionable', likely: 'Probable'};
/* a teammate is out: the build already raised this player's projection; say by how much and why */
const bumpTxt = p => p && p.bump && p.bump.txt ? `<div class="bump">▲ ${esc(p.bump.txt)}</div>` : '';
const liveTxt = SE.liveTxt;
const shortDay = d => { const [y, mo, da] = String(d).split('-').map(Number); return new Date(y, mo - 1, da).toLocaleDateString([], {month: 'short', day: 'numeric'}); };
const SEASON_START = `${String(M.season || '').slice(0, 4)}-08-01`;

/* ---------------- chances: the same math the build uses ---------------- */
const QS41 = Array.from({length: 41}, (_, i) => i / 40);
function interp(x, xs, ys){
  if (x <= xs[0]) return ys[0]; if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1; while (xs[i] < x) i++;
  const t = (x - xs[i - 1]) / ((xs[i] - xs[i - 1]) || 1e-9); return ys[i - 1] + t * (ys[i] - ys[i - 1]);
}
/* NBA: outcome ratios around the projection (research tables); NHL: Poisson counts with the research's calibration */
function pOverNBA(k, proj, L){
  const bins = (D.dist || {})[k]; if (!bins || proj == null) return null;
  if (proj <= 0.05) return L < 0 ? 1 : 0;
  const b = bins.find(x => proj <= x[0]) || bins[bins.length - 1], q = b[1];
  const t = (L % 1 ? L : L - 0.5) / proj;
  // q is increasing in probability; invert: P(ratio <= t)
  let cdf;
  if (t <= q[0]) cdf = 0; else if (t >= q[q.length - 1]) cdf = 1; else { let i = 1; while (q[i] < t) i++; cdf = QS41[i - 1] + (t - q[i - 1]) / ((q[i] - q[i - 1]) || 1e-9) * (QS41[i] - QS41[i - 1]); }
  return Math.min(1, Math.max(0, 1 - cdf));
}
function poisPmf(k, lam){ let p = Math.exp(-lam); for (let i = 1; i <= k; i++) p *= lam / i; return p; }
function poisAtLeast(t, lam){ let c = 0; for (let i = 0; i < t; i++) c += poisPmf(i, lam); return Math.max(0, 1 - c); }
const CALN = {goals: 'goal', points: 'point', assists: 'assist', sog: 'sog', blocks: 'blk', hits: 'hit'};
function calP(name, p){ const pts = (D.cal || {})[name]; if (!pts || p == null) return p; return interp(p, [0].concat(pts.map(x => x[0]), [1]), [0].concat(pts.map(x => x[1]), [1])); }
function pAtLeastNHL(k, lam, t){ if (lam == null) return null; return calP(CALN[k] + t, poisAtLeast(t, Math.max(lam, 1e-6))); }
function pOver(k, proj, L){
  if (L == null || isNaN(L)) return null;
  if (NHL){
    if (k === 'saves') return null;
    return pAtLeastNHL(k, proj, Math.floor(L) + 1);
  }
  return pOverNBA(k, proj, Number(L));
}
function pSaves(g, L){ return g ? 1 - ncdf((L - g.saves) / (D.sv_sd || 6)) : null; }
const lgt = p => Math.log(p / (1 - p)), sgm = x => 1 / (1 + Math.exp(-x));
function blendP(k, pm, pb){
  if (pb == null) return pm; if (pm == null) return pb;
  const w = ((D.research || {}).blend || {})[k] ?? 0;
  const a = Math.min(Math.max(pm, .02), .98), b = Math.min(Math.max(pb, .02), .98);
  return sgm((1 - w) * lgt(b) + w * lgt(a));
}

/* ---------------- header and tabs ---------------- */
const DAYS = M.days || [];
function renderAsof(){
  $('#m-asof').innerHTML = `Updated <strong>${ago(M.asof)}</strong>${M.stats_through ? `<span class="xs-hide"> · box scores through ${esc(dayLabel(M.stats_through, {plain: true}))}</span>` : ''}`;
  $('#m-day').innerHTML = `<strong>${esc(M.season)}</strong> season`;
  $('#m-asof2').innerHTML = `<strong>${esc(M.season)}</strong> · updated ${ago(M.asof)}`;
}
renderAsof(); setInterval(renderAsof, 60000);
const NAV = [['games', 'Games', NHL ? 'Every game: lines, starting goalies, the model and injuries' : 'Every game: lines, the model, rest and injuries'],
  ['props', 'Props', 'Player projections against the real prop lines, with fair prices'], ['model', 'Model', 'Who the model picks, why, and its record'],
  ['hc', 'High-chance', 'Legs rated 80% or better, checked against past results'], ['ls', 'Long shots', NHL ? 'Goal scorers, multi-point nights and the first goal' : 'Big scoring nights, double- and triple-doubles'],
  ['trends', 'Trends', 'Players and teams on runs, and whether runs last'], ['picks', 'My bets', 'Every bet across sports: record, units, closing line'],
  ['tips', 'Betting tips', 'Where real edges come from, applied to today'], ['matters', 'What matters', 'What the research says predicts games and props'],
  ['teams', 'Teams', 'Records, ratings and trends for all ' + Object.keys(T).length]];
function tabFade(){ const n = $('.tabs'); if (!n) return; n.classList.toggle('fl', n.scrollLeft > 4); n.classList.toggle('fr', n.scrollLeft + n.clientWidth < n.scrollWidth - 4); }
function openNav(){
  const cur = store.get('tab', 'games');
  $('#navsheet').innerHTML = `<div class="sec-head"><h2 class="h3" id="nav-title">All sections</h2><button class="btn tiny" data-navclose="">Close</button></div>
    <div class="navgrid">${NAV.map(([k, l, d]) => `<button class="navitem${k === cur ? ' on' : ''}" data-navgo="${k}"><b>${l}</b><span>${d}</span></button>`).join('')}</div>`;
  $('#navscrim').hidden = false; $('#navsheet').hidden = false; document.body.style.overflow = 'hidden';
  setTimeout(() => { const b = $('#navsheet .navitem.on') || $('#navsheet .navitem'); if (b) b.focus(); }, 0);
}
function closeNav(){ $('#navscrim').hidden = true; $('#navsheet').hidden = true; document.body.style.overflow = ''; }
const RENDER = {};
function show(view){
  if (!$('#v-' + view)) view = 'games';
  $$('.tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === view)));
  const tb = $(`.tab[data-view="${view}"]`), nav = tb && tb.parentElement;
  if (nav && nav.scrollWidth > nav.clientWidth) nav.scrollTo({left: Math.max(0, tb.offsetLeft - (nav.clientWidth - tb.offsetWidth) / 2), behavior: 'smooth'});
  $$('.view').forEach(v => v.hidden = v.id !== 'v-' + view);
  store.set('tab', view);
  try { history.replaceState(null, '', '#' + view); } catch(e){}
  if (RENDER[view] && view !== 'picks') RENDER[view]();
  window.scrollTo({top: 0});
}
$$('.tab').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));
$('.tabs').addEventListener('scroll', tabFade, {passive: true}); window.addEventListener('resize', tabFade); setTimeout(tabFade, 0);
$('#nav-open').addEventListener('click', openNav);
$('#navscrim').addEventListener('click', closeNav);
document.addEventListener('click', e => { const b = e.target.closest('[data-navgo], [data-navclose]'); if (!b) return; closeNav(); if (b.dataset.navgo) show(b.dataset.navgo); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#navsheet').hidden) closeNav(); });

/* ======================================================================
   GAMES
   ====================================================================== */
let DAY = DAYS.includes(store.get('day', '')) && store.get('daySet', '') === dayKey(new Date().toISOString()) ? store.get('day') : (M.slate || DAYS[0]);
const GOPEN = new Set();
let INJ_IDX = {};
const injNorm = n => String(n || '').normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase().replace(/\s+(jr|sr|ii|iii|iv|v)\.?$/, '').replace(/[^a-z]/g, '');
function buildInjIdx(){ INJ_IDX = {}; Object.entries(D.injuries || {}).forEach(([t, lst]) => lst.forEach(i => { INJ_IDX[t + '|' + injNorm(i.name)] = i; if (i.pid) INJ_IDX[t + '|#' + i.pid] = i; })); }
buildInjIdx();
const injOf = (team, name, id) => INJ_IDX[team + '|#' + id] || INJ_IDX[team + '|' + injNorm(name)] || null;
function injPill(team, name, id, lead){
  const i = injOf(team, name, id);
  return i && i.level !== 'likely' ? `${lead ? ' ' : ''}<span class="pill lvl-${i.level}" title="${esc(i.injury || '')}">${esc(LEVEL_WORD[i.level] || i.status)}</span>` : '';
}
const homeLine = g => { const o = g.odds || {}; if (o.spread != null) return o.spread; if (NHL && o.ml_h != null && o.ml_a != null) return o.ml_h < o.ml_a ? -1.5 : 1.5; return null; };
const lineFor = (g, team) => { const h = homeLine(g); return h == null ? null : (team === g.home ? h : -h); };
function gameLegs(g, side){
  const t = side === 'home' ? g.home : g.away, ln = lineFor(g, t), o = g.odds || {};
  const base = {game: g.id, mu: `${g.away} @ ${g.home}`, k: g.k, sub: `${g.away} @ ${g.home} · ${whenDay(g.k)}`};
  return {
    spread: ln == null ? null : Object.assign({market: 'spread', team: t, line: ln, odds: (side === 'home' ? o.sp_h : o.sp_a) ?? (NHL ? null : -110)}, base),
    total: o.total == null ? null : Object.assign({market: 'total', side: side === 'home' ? 'U' : 'O', line: o.total, odds: (side === 'home' ? o.u : o.o) ?? -110}, base),
    ml: (side === 'home' ? o.ml_h : o.ml_a) == null ? null : Object.assign({market: 'ml', team: t, odds: side === 'home' ? o.ml_h : o.ml_a}, base)
  };
}
function teamRow(g, side){
  const t = side === 'home' ? g.home : g.away, x = T[t] || {};
  const final = g.state === 'post', live = isLive(g);
  const sc = side === 'home' ? g.hs : g.as, oc = side === 'home' ? g.as : g.hs;
  const L = gameLegs(g, side);
  const right = (final || live) && sc != null ? `<div class="score ${final && sc < oc ? 'lost' : ''}">${sc}</div>` :
    `<div class="obs">${SB.oddsBtn(L.spread, fmtLine(lineFor(g, t)), L.spread && L.spread.odds != null ? fmtOdds(L.spread.odds) : '')}${SB.oddsBtn(L.total, L.total ? `${side === 'home' ? 'U' : 'O'} ${g.odds.total}` : '', L.total ? fmtOdds(L.total.odds) : '')}${SB.oddsBtn(L.ml, L.ml ? fmtOdds(L.ml.odds) : '', 'ML')}</div>`;
  const m = g.model, wp = m ? (side === 'home' ? m.wp_home : 1 - m.wp_home) : null;
  const pickB = m && m.pick_su === t ? `<span class="wbadge${final ? (sc > oc ? ' ok' : ' no') : ''}" title="Model's pick to win">${final ? (sc > oc ? '✓ ' : '✗ ') : ''}Model ${pct(wp)}</span>` : '';
  const gk = NHL && g.goalies ? g.goalies[side === 'home' ? 'h' : 'a'] : null;
  const rest = g.rest ? (side === 'home' ? g.rest.b2b_h : g.rest.b2b_a) : false;
  return `<div class="trow">
    <div style="display:flex;align-items:center;gap:2px">${chip(t)}</div>
    <div class="tname"><div class="n">${esc(x.nick || t)} <span class="rec num">${recTxt(x.rec)}</span>${pickB}</div>
      <div class="meta"><span>L5 ${resDots(x.last)}</span>${!NHL ? `<span>ATS ${wl(x.ats)}</span>` : `<span>${x.pts ?? 0} pts</span>`}<span>O/U ${ouTxt(x.ou)}</span>${rest ? '<span class="pill warn" style="padding:2px 6px">Back-to-back</span>' : ''}</div>
      ${gk && gk.name ? `<div class="meta"><span>Goalie <b>${esc(gk.name)}</b> ${gk.sv ? `(${(gk.sv * 100).toFixed(1)}%)` : ''} · <span class="${gk.src === 'Confirmed' ? 'gk-ok' : 'gk-maybe'}">${esc(gk.src || 'Expected')}</span></span></div>` : ''}</div>
    ${right}</div>`;
}
function modelBlock(g){
  const m = g.model; if (!m) return '';
  const o = g.odds || {};
  const wpH = m.wp_home, mk = m.mkt_wp_home;
  const bar = `<div class="wp"><div class="wp-labels"><span>${g.away} ${pct(1 - wpH)}</span><span class="wp-mid small">Model win chance${mk != null ? ' · yellow mark = the market' : ''}</span><span>${g.home} ${pct(wpH)}</span></div>
    <div class="wp-track"><span style="width:${((1 - wpH) * 100).toFixed(1)}%;background:${(T[g.away] || {}).c1 || '#888'}"></span><span style="width:${(wpH * 100).toFixed(1)}%;background:${(T[g.home] || {}).c1 || '#555'}"></span>${mk != null ? `<i class="wp-mkt" style="left:${((1 - mk) * 100).toFixed(1)}%"></i>` : ''}</div></div>`;
  let tiles;
  if (NHL){
    const pl = homeLine(g);
    tiles = [['Expected goals', `${fmtN(m.lam_a, 1)}–${fmtN(m.lam_h, 1)}`, `${g.away}–${g.home}`, ''],
      ['Model total', fmtN(m.total, 1), o.total != null ? `line ${o.total} · over ${pct(m.p_over)}` : 'no line yet', m.p_over != null && Math.abs(m.p_over - 0.5) >= 0.06 ? 'pick' : ''],
      ['Wins by 2+', `${pct(m.p_h_by2)}`, `${g.home} −1.5 · ${g.away} ${pct(m.p_a_by2)}`, ''],
      ['Model vs market', m.edge == null ? '–' : `${m.edge > 0 ? g.home : g.away} ${sign(Math.abs(m.edge) * 100, 0)}%`, m.value ? `value side: ${m.value}` : 'within 5%', m.value ? 'pick' : '']];
  } else {
    const ml = m.margin, mkt = o.spread != null ? -o.spread : null;
    tiles = [['Model line', `${ml >= 0 ? g.home : g.away} ${fmtLine(-Math.abs(ml))}`, `${g.home} by ${fmtN(ml, 1)}`, ''],
      ['Market line', mkt == null ? '–' : `${mkt >= 0 ? g.home : g.away} ${fmtLine(-Math.abs(mkt))}`, m.edge == null ? '' : `model ${m.edge > 0 ? g.home : g.away} by ${fmtN(Math.abs(m.edge), 1)} more`, m.pick_ats ? 'pick' : ''],
      ['Model total', fmtN(m.total, 1), o.total != null ? `line ${o.total} · ${m.total_edge > 0 ? '+' : ''}${fmtN(m.total_edge, 1)}` : 'no line yet', m.pick_total ? 'pick' : ''],
      ['Win chance', pct(Math.max(wpH, 1 - wpH)), `${m.pick_su}${mk != null ? ` · market ${pct(m.pick_su === g.home ? mk : 1 - mk)}` : ''}`, '']];
  }
  return bar + `<div class="mrow">${tiles.map(([k, v, s, c]) => `<div class="mc ${c}"><div class="k">${k}</div><div class="v num">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('')}</div>`;
}
function gameChips(g){
  const out = [];
  const m = g.model;
  if (m && !NHL && m.pick_ats) out.push(`<span class="pill stripe">Lean ${m.pick_ats} ${fmtLine(lineFor(g, m.pick_ats))}</span>`);
  if (m && !NHL && m.pick_total) out.push(`<span class="pill stripe">Lean ${m.pick_total === 'O' ? 'over' : 'under'} ${g.odds.total}</span>`);
  if (m && NHL && m.value) out.push(`<span class="pill stripe">Value: ${m.value} ML</span>`);
  ['a', 'h'].forEach(sd => {
    const t = sd === 'h' ? g.home : g.away;
    const outs = (D.injuries[t] || []).filter(i => i.key && (i.level === 'out' || i.level === 'doubt')).slice(0, 3);
    if (outs.length) out.push(`<span class="pill loss">${t} out: ${outs.map(i => esc(lastName(i.name))).join(', ')}</span>`);
    const q = (D.injuries[t] || []).filter(i => i.key && i.level === 'gtd').slice(0, 2);
    if (q.length) out.push(`<span class="pill warn">${t} questionable: ${q.map(i => esc(lastName(i.name))).join(', ')}</span>`);
  });
  return out.join('');
}
function gameSummary(g){
  const m = g.model, live = isLive(g), fin = g.state === 'post';
  const st = live ? `<span class="lv">${esc(liveTxt(g.detail))}</span>` : fin ? esc(g.detail || 'Final') : when(g.k, {hour: 'numeric', minute: '2-digit'});
  const ln = NHL ? (g.odds && g.odds.ml_h != null ? (g.odds.ml_h < g.odds.ml_a ? `${g.home} ${fmtOdds(g.odds.ml_h)}` : `${g.away} ${fmtOdds(g.odds.ml_a)}`) : '')
    : (homeLine(g) != null ? (homeLine(g) <= 0 ? `${g.home} ${fmtLine(homeLine(g))}` : `${g.away} ${fmtLine(-homeLine(g))}`) : '');
  const pk = m ? `<span class="pk2${fin ? ((m.pick_su === g.home) === (g.hs > g.as) ? ' ok' : ' no') : ''}">${m.pick_su} ${pct(Math.max(m.wp_home, 1 - m.wp_home))}</span>` : '';
  return `<button class="g-sum" data-gsum="${g.id}" aria-expanded="${GOPEN.has(g.id)}">
    <span class="r1"><span class="mu">${chip(g.away, 1)} <span class="rc">${recTxt((T[g.away] || {}).rec)}</span> @ ${chip(g.home, 1)} <span class="rc">${recTxt((T[g.home] || {}).rec)}</span></span>
      <span class="rt num">${(live || fin) && g.hs != null ? `${g.as}–${g.hs}` : esc(ln)}</span></span>
    <span class="r2">${st}${pk ? ' · ' + pk : ''}${g.rest && (g.rest.b2b_h || g.rest.b2b_a) ? ' · B2B' : ''}<span class="chev">${GOPEN.has(g.id) ? '▲' : '▼'}</span></span></button>`;
}
function gameCard(g){
  const live = isLive(g), fin = g.state === 'post';
  const flags = [live ? `<span class="pill loss">● ${esc(liveTxt(g.detail))}</span>` : '', fin ? `<span class="pill ghost">${esc(g.detail || 'Final')}</span>` : ''].join('');
  return `<article class="game${GOPEN.has(g.id) ? ' open' : ''}" id="g-${g.id}">
    ${gameSummary(g)}
    <div class="g-head"><div><div class="g-when">${esc(whenDay(g.k))}</div><div class="g-where">${esc(g.venue || '')}</div></div><div class="g-flags">${flags}</div></div>
    <div class="g-body">
      ${fin || live ? '' : `<div class="obh"><span></span><span>${CFG.spread}</span><span>Total</span><span>Money</span></div>`}
      ${teamRow(g, 'away')}${teamRow(g, 'home')}
      ${modelBlock(g)}
      <div class="g-chips">${gameChips(g)}</div>
    </div>
    <button class="g-more" data-more="${g.id}" aria-expanded="false"><span>Injuries, props, trends and why</span><span>＋</span></button>
    <div class="g-detail" id="d-${g.id}" hidden></div>
  </article>`;
}
const DETAIL_TABS = [['inj', 'Injuries'], ['props', 'Props'], ['trends', 'Trends'], ['why', 'Why']];
function detailHtml(g, which){
  which = which || 'inj';
  const tabs = `<div class="seg" role="group" aria-label="Details">${DETAIL_TABS.map(([k, l]) => `<button type="button" data-dtab="${k}" data-g="${g.id}" aria-pressed="${k === which}">${l}</button>`).join('')}</div>`;
  let body = '';
  if (which === 'inj') body = `<div class="twocol">${[g.away, g.home].map(t => injCol(t)).join('')}</div><div class="note">From ESPN's injury list, refreshed every few minutes while this page is open. Bold names are rotation regulars.</div>`;
  if (which === 'props') body = gamePropsHtml(g);
  if (which === 'trends') body = `<div class="twocol">${[g.away, g.home].map(t => teamTrendBox(t)).join('')}</div>`;
  if (which === 'why') body = whyHtml(g);
  return tabs + body;
}
function injCol(t){
  const lst = D.injuries[t] || [];
  const rows = lst.length ? lst.map(i => `<div class="inj"><div class="top"><span class="who">${i.key ? '<b>' + esc(i.name) + '</b>' : esc(i.name)} <small>${esc(i.pos || '')}${i.min ? ` · ${fmtN(i.min, 0)} min` : i.toi ? ` · ${fmtN(i.toi, 0)} min TOI` : ''}</small></span><span class="pill lvl-${i.level}">${esc(LEVEL_WORD[i.level] || i.status)}</span></div>
      <div class="ol">${esc(i.injury || '')}${i.ret ? ` · back around ${esc(new Date(i.ret).toLocaleDateString([], {month: 'short', day: 'numeric'}))}` : ''}</div>${i.comment ? `<div class="small">${esc(i.comment)}</div>` : ''}</div>`).join('')
    : '<div class="small">Nobody on the injury list.</div>';
  return `<div><div class="team-sub">${chip(t)} <b>${esc(nick(t))}</b></div>${rows}</div>`;
}
function teamTrendBox(t){
  const x = T[t] || {};
  const rows = [['Record', recTxt(x.rec)], ['Last 10', recTxt(x.l10)], ['Home', recTxt(x.home)], ['Road', recTxt(x.away)], NHL ? ['Goals for / against', `${fmtN(x.gf, 2)} / ${fmtN(x.ga, 2)}`] : ['Point diff / game', sign(x.pd, 1)],
    NHL ? ['Points', String(x.pts ?? '–')] : ['Against the spread', wl(x.ats)], ['Overs / unders', ouTxt(x.ou)], ['Streak', x.streak || '–']].filter(r => r[1] && r[1] !== 'undefined');
  const tr = (D.trends.team || []).filter(r => r.team === t).map(r => `<span class="pill ghost">${esc(r.what)} ${r.n} straight</span>`).join('');
  return `<div><div class="team-sub">${chip(t)} <b>${esc(nick(t))}</b></div><table class="tape"><tbody>${rows.map(([k, v]) => `<tr><td>${k}</td><td class="num" style="text-align:right">${esc(v)}</td></tr>`).join('')}</tbody></table>
    ${tr ? `<div class="g-chips" style="margin-top:8px">${tr}</div>` : ''}<button class="btn tiny" style="margin-top:8px" data-chart="t|${t}">Chart ${t}'s games</button></div>`;
}
function whyHtml(g){
  const m = g.model; if (!m) return '<div class="small">No model numbers for this game.</div>';
  const parts = m.parts || {};
  const L = NHL ? {home: 'Home ice', skaters: 'Skaters (goal and shot ratings)', goalies: 'Starting goalies'} : {home: 'Home court', ratings: 'Team efficiency ratings', rest: 'Rest and back-to-backs', lineups: "Who's available"};
  const mx = Math.max(0.5, ...Object.values(parts).map(v => Math.abs(v)));
  const rows = Object.entries(L).filter(([k]) => parts[k] != null).map(([k, lbl]) => { const v = parts[k], w = Math.abs(v) / mx * 50;
    return `<div class="fx"><div class="fx-l"><b>${lbl}</b><span>${v === 0 ? 'even' : (v > 0 ? 'favors ' + g.home : 'favors ' + g.away)}</span></div>
      <div class="fx-bar"><i class="mid"></i><span style="${v >= 0 ? 'left:50%' : 'right:50%'};width:${w.toFixed(1)}%;background:${v >= 0 ? ((T[g.home] || {}).c1 || 'var(--ink)') : ((T[g.away] || {}).c1 || 'var(--ink)')}"></span></div>
      <div class="fx-v">${sign(v, NHL ? 2 : 1)}</div></div>`; }).join('');
  const outs = !NHL && g.outs ? ['a', 'h'].map(sd => (g.outs[sd] || []).length ? `<div class="small"><b>${sd === 'h' ? g.home : g.away} missing:</b> ${(g.outs[sd] || []).map(o => `${esc(o.name)} (${fmtN(o.min, 0)} min, ${esc(LEVEL_WORD[o.level] || o.level)})`).join(', ')}</div>` : '').join('') : '';
  const gk = NHL && g.goalies ? ['a', 'h'].map(sd => { const x = g.goalies[sd]; return x && x.name ? `<div class="small"><b>${sd === 'h' ? g.home : g.away}:</b> ${esc(x.name)}, ${(x.sv * 100).toFixed(1)}% save rate after regressing toward the league (${esc(x.src || 'expected')})</div>` : ''; }).join('') : '';
  return `<div class="fxs"><div class="fx-axis"><span>◀ ${g.away}</span><span>${NHL ? 'goals a game' : 'points'}</span><span>${g.home} ▶</span></div>${rows}</div>${outs}${gk}
    <p class="small" style="margin:0">${NHL ? 'Expected goals come from each team\'s scoring and shot ratings, scaled by the opposing starting goalie. Win chance treats goals as Poisson, with a tie after regulation split evenly.'
      : 'The line is the sum of these pieces. Ratings are points per 100 possessions, adjusted for opponents and weighted toward recent games; who\'s available weighs each missing rotation player by his minutes and box-score value.'}</p>`;
}
function gamePropsHtml(g){
  const lst = (D.props || []).filter(p => p.game === g.id);
  const goalies = NHL ? (D.goalies || []).filter(x => x.game === g.id) : [];
  if (!lst.length && !goalies.length) return `<div class="small">${g.state === 'pre' ? 'No projections for this game yet.' : 'Props are shown before games start.'}</div>`;
  const keys = NHL ? ['sog', 'points', 'goals'] : ['pts', 'reb', 'ast', 'fg3m'];
  const row = p => `<div class="prow"><div><div class="pn">${chip(p.team, 1)} <span data-chart="p|${esc(p.id)}|${keys[0]}">${esc(p.name)}</span>${injPill(p.team, p.name, p.id, true)}</div><div class="ps">${esc(p.pos || '')} · ${fmtN(p.min ?? p.toi, 0)} min</div>${bumpTxt(p)}</div>
    ${keys.map(k => { const pr = k === 'goals' ? p.p_goal : p.proj[k], ln = (p.lines || {})[k];
      return `<div class="c-avg"><span class="proj num">${k === 'goals' ? pct(pr) : fmtN(pr, 1)}<small>${k === 'goals' ? 'to score' : CFG.short[k] || k}</small></span>${ln ? `<div class="small">line ${ln.line} · over ${pct(ln.p)}</div>` : ''}</div>`; }).join('')}</div>`;
  const byT = t => lst.filter(p => p.team === t).sort((a, b) => (b.proj[keys[0]] || 0) - (a.proj[keys[0]] || 0)).slice(0, 8);
  return [g.away, g.home].map(t => `<div class="team-sub">${chip(t)} <b>${esc(nick(t))}</b></div><div class="plist gp-props" style="--cols:${keys.length}">${byT(t).map(row).join('')}</div>`).join('')
    + (goalies.length ? `<div class="team-sub"><b>Goalies</b></div><div class="plist gp-props" style="--cols:2">${goalies.map(x => `<div class="prow"><div><div class="pn">${chip(x.team, 1)} ${esc(x.name)}</div><div class="ps">${esc(x.src)} · ${(x.sv_pct * 100).toFixed(1)}%</div></div><div class="c-avg"><span class="proj num">${fmtN(x.saves, 1)}<small>saves</small></span></div><div class="c-avg"><span class="proj num">${fmtN(x.shots, 0)}<small>shots</small></span></div></div>`).join('')}</div>` : '')
    + `<button class="btn tiny" data-goto="props">All props</button>`;
}
let GF = store.get('gf', 'all');
function renderGames(){
  const v = $('#v-games');
  const days = DAYS.filter(d => D.games.some(g => g.day === d));
  if (!days.includes(DAY)) DAY = days.includes(M.slate) ? M.slate : days[0];
  const gs = D.games.filter(g => g.day === DAY).sort((a, b) => (isLive(b) - isLive(a)) || a.k.localeCompare(b.k));
  const shown = gs.filter(g => GF === 'all' || (GF === 'picks' ? g.model && (g.model.pick_ats || g.model.pick_total || g.model.value) : GF === 'b2b' ? g.rest && (g.rest.b2b_h || g.rest.b2b_a) : GF === 'inj' ? [g.home, g.away].some(t => (D.injuries[t] || []).some(i => i.key && i.level !== 'likely')) : true));
  const live = gs.filter(isLive).length, fin = gs.filter(g => g.state === 'post').length;
  const strong = gs.filter(g => g.state === 'pre' && g.model).sort((a, b) => Math.abs(b.model.wp_home - .5) - Math.abs(a.model.wp_home - .5))[0];
  const hc = (D.high_chance || []).filter(x => x.kind !== 'ml')[0], ls = (D.long_shots || [])[0];
  const edges = [strong ? `<div class="edge"><div class="label">${Math.max(strong.model.wp_home, 1 - strong.model.wp_home) >= 0.6 ? "Model's surest winner" : "Model's strongest lean"}</div><div class="big">${strong.model.pick_su} ${pct(Math.max(strong.model.wp_home, 1 - strong.model.wp_home))}</div><div class="d">${strong.away} @ ${strong.home}, ${esc(when(strong.k, {hour: 'numeric', minute: '2-digit', weekday: 'short'}))}</div><a href="#" data-jump="${strong.id}">Open matchup →</a></div>` : '',
    hc ? `<div class="edge"><div class="label">Safest player leg</div><div class="big">${pct(hc.p)} · ${esc(hc.label)}</div><div class="d">Fair price ${fmtOdds(hc.fair)}${hc.book != null ? ` · book ${fmtOdds(hc.book)}` : ''}</div><a href="#" data-goto="hc">All high-chance picks →</a></div>` : '',
    ls ? `<div class="edge"><div class="label">Likeliest long shot</div><div class="big">${pct(ls.p)} · ${esc(ls.label)}</div><div class="d">Fair price ${fmtOdds(ls.fair)}${ls.book != null ? ` · book ${fmtOdds(ls.book)}` : ''}</div><a href="#" data-goto="ls">All long shots →</a></div>` : ''].join('');
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">${esc(dayLabel(DAY))}${DAY !== dayKey(new Date().toISOString()) && !['Today', 'Tomorrow', 'Yesterday'].includes(dayLabel(DAY)) ? '' : ''} · ${gs.length} game${gs.length === 1 ? '' : 's'}</h1>
      <p class="lede">${live ? `<b style="color:var(--loss)">${live} live</b> · ` : ''}${fin ? fin + ' final · ' : ''}${gs.length - live - fin} to play. Tap a line to add it to the bet slip.${NHL ? ' Starting goalies show under each team as they are confirmed.' : ''}</p></div></div>
    <div class="seg days" role="group" aria-label="Day">${days.map(d => `<button type="button" data-day="${d}" aria-pressed="${d === DAY}">${esc(dayLabel(d))}</button>`).join('')}</div>
    ${edges && DAY === M.slate ? `<div class="edges">${edges}</div>` : ''}
    <div class="toolbar gtools"><div class="seg" role="group" aria-label="Filter games">${[['all', 'All games'], ['picks', 'Model leans'], ['b2b', 'Back-to-backs'], ['inj', 'Key injuries']].map(([k, l]) => `<button type="button" data-gf="${k}" aria-pressed="${GF === k}">${l}</button>`).join('')}</div>
      <button class="btn" data-addpick="">+ Custom<span class="xs-hide"> bet</span></button></div>
    ${shown.length ? `<div class="games">${shown.map(gameCard).join('')}</div>` : `<div class="empty"><div class="h3">No games here</div><p class="lede" style="margin:0">${gs.length ? 'Nothing matches that filter.' : 'No games on this day. Try another day above.'}</p></div>`}`;
  const dz = $('.seg.days', v), dsel = dz && $('[aria-pressed="true"]', dz);
  if (dz && dsel && dz.scrollWidth > dz.clientWidth) dz.scrollLeft = Math.max(0, dsel.offsetLeft - dz.offsetLeft - (dz.clientWidth - dsel.offsetWidth) / 2);
  SB.refresh();
}
RENDER.games = renderGames;

/* ======================================================================
   PROPS: projections against the book's lines
   ====================================================================== */
let PPF = Object.assign({key: CFG.propTabs[0][0], game: 'all', q: '', sort: 'value'}, store.get('ppf', {}));
if (!CFG.propTabs.some(([k]) => k === PPF.key)) PPF.key = CFG.propTabs[0][0];
let PL = store.get('pl', {});
let PPSHOW = 30;
const PIDX = {};
(D.props || []).forEach(p => { PIDX[p.game + ':' + p.id] = p; });
function propVal(p, k){ return k === 'goals' ? p.p_goal : p.proj[k]; }
function bestEv(ln){ return ln ? Math.max(ln.ev_o ?? -9, ln.ev_u ?? -9) : -9; }
function verdict(ln, k){
  if (!ln) return '';
  const w = ((D.research || {}).blend || {})[k] ?? 0;
  const side = (ln.ev_o ?? -9) >= (ln.ev_u ?? -9) ? 'over' : 'under', ev = side === 'over' ? ln.ev_o : ln.ev_u;
  const c = Math.round(ev * 100), Side = side === 'over' ? 'Over' : 'Under';
  if (ev >= 0.03 && w > 0) return `<span class="ev pos">${Side} is a good price: about +${c}¢ per $1</span>`;
  if (c === 0) return `<span class="ev thin">${Side} is about break-even at these prices</span>`;
  if (ev >= 0) return `<span class="ev thin">${Side}: thin edge, +${c}¢ per $1</span>`;
  return `<span class="ev neg">No edge at these prices (the better side, ${side}, loses about ${Math.abs(c)}¢ per $1)</span>`;
}
function ppRow(p, k){
  const key = `${p.id}:${k}`, ln = (p.lines || {})[k], st = PL[key] || {};
  const proj = propVal(p, k);
  const typed = st.line != null && st.line !== '' ? numOf(st.line) : null;
  const L = typed ?? (ln ? ln.line : (proj != null ? Math.floor(proj) + 0.5 : null));
  const pm = L != null ? pOver(k, proj, L) : null;
  const pUse = ln && L === ln.line ? ln.p : pm;
  const O = parseOdds(st.odds);
  const avg = p.avg && p.avg[k] != null ? `avg ${fmtN(p.avg[k], 1)} last 10` : '';
  const book = ln ? `<div class="pp-h"><b>${esc(ln.book || 'Book')}</b> line <b>${ln.line}</b>${ln.open != null && ln.open !== ln.line ? ` (opened ${ln.open})` : ''} · Over <b>${fmtOdds(ln.o)}</b> · Under <b>${fmtOdds(ln.u)}</b></div>
      <div class="pp-pc">Over <b class="num">${pct(ln.p)}</b> <span class="small">· model ${pct(ln.p_model)} · book ${pct(ln.p_book)}</span></div>${verdict(ln, k)}` : `<div class="pp-h">No book line posted yet${proj != null ? ' · type one to check it' : ''}</div>`;
  const chk = L != null ? `<div class="pp-out"><span>${typed != null || !ln ? `At ${L}: over <b>${pct(pm)}</b> · under <b>${pct(pm == null ? null : 1 - pm)}</b> (model)` : ''}</span>${O != null && pm != null ? `<span class="ev ${evMsg(st.side === 'under' ? 1 - pm : pm, oddsNum(st.side === 'under' ? 1 - pm : pm), String(O)).c}">${esc(evMsg(st.side === 'under' ? 1 - pm : pm, oddsNum(st.side === 'under' ? 1 - pm : pm), String(O)).t)}</span>` : ''}</div>` : '';
  return `<article class="pp" data-pid="${esc(p.id)}" data-g="${p.game}" data-key="${k}">
    <div class="pp-who"><div class="pn"><span data-chart="p|${esc(p.id)}|${k === 'goals' ? 'goals' : k}">${esc(p.name)}</span>${injPill(p.team, p.name, p.id, true)}</div>
      <div class="ps">${chip(p.team, 1)} ${p.home ? 'vs' : '@'} ${chip(p.opp, 1)} <span class="small">${esc(p.pos || '')} · ${fmtN(p.min ?? p.toi, 0)} min · ${esc(when((gameOf(p.game) || {}).k || '', {hour: 'numeric', minute: '2-digit', weekday: 'short'}))}</span></div>${bumpTxt(p)}</div>
    <div class="pp-proj"><span class="proj num">${fmtN(proj, k === 'fg3m' || NHL ? 2 : 1)}<small>${esc(CFG.short[k] || k)}</small></span><span class="small">${avg}</span></div>
    <div class="pp-chk">${book}
      <div class="pp-in"><div class="f"><span class="clb-l">Line</span>${stepWrap(`<input type="text" inputmode="decimal" autocomplete="off" data-ppl="${esc(key)}" value="${esc(st.line ?? '')}" placeholder="${L ?? ''}" data-proj="${proj ?? ''}" aria-label="Line">`, 'line')}</div>
        <div class="f"><span class="clb-l">Odds</span>${stepWrap(`<input type="text" inputmode="numeric" autocomplete="off" data-ppo="${esc(key)}" value="${esc(st.odds ?? '')}" placeholder="${ln ? fmtOdds(st.side === 'under' ? ln.u : ln.o).replace('−', '-') : '-110'}" aria-label="Your odds">`, 'odds')}</div>
        <div class="seg pp-side" role="group" aria-label="Side"><button type="button" data-ppside="over" aria-pressed="${st.side !== 'under'}">Over</button><button type="button" data-ppside="under" aria-pressed="${st.side === 'under'}">Under</button></div></div>
      ${chk}
      <div class="pp-acts"><button class="btn tiny slipb" data-slipkey="${SP}:${k}:${p.game}:${esc(p.id)}" data-pppick="">+ Slip</button><button class="btn tiny" data-chart="p|${esc(p.id)}|${k === 'goals' ? 'goals' : k}">Chart</button></div></div>
  </article>`;
}
function goalsRow(p){
  const y = p.yes || {}, rows = [['atg', 'To score', p.p_goal], ['g2', '2+ goals', pAtLeastNHL('goals', p.proj.goals, 2)], ['first_goal', 'First goal', p.p_first]];
  return `<article class="pp" data-pid="${esc(p.id)}" data-g="${p.game}" data-key="goals">
    <div class="pp-who"><div class="pn"><span data-chart="p|${esc(p.id)}|goals">${esc(p.name)}</span>${injPill(p.team, p.name, p.id, true)}</div>
      <div class="ps">${chip(p.team, 1)} ${p.home ? 'vs' : '@'} ${chip(p.opp, 1)} <span class="small">${esc(p.pos || '')} · ${fmtN(p.toi, 0)} min</span></div>${bumpTxt(p)}</div>
    <div class="pp-proj"><span class="proj num">${fmtN(p.proj.goals, 2)}<small>expected goals</small></span><span class="small">${fmtN(p.proj.sog, 1)} shots · avg ${fmtN(p.avg.goals, 2)} goals</span></div>
    <div class="pp-chk">${rows.map(([k, l, pr]) => { const o = y[k]; const r = o != null && pr != null ? evMsg(pr, oddsNum(pr), String(o)) : null;
      return `<div class="pp-h" style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center"><span><b>${l}</b> ${pct(pr, pr < 0.1 ? 1 : 0)} · fair ${fairTxt(pr)}${o != null ? ` · book <b>${fmtOdds(o)}</b>` : ''}</span>
        ${r ? `<span class="ev ${r.c}">${r.c === 'pos' ? 'good price' : r.c === 'thin' ? 'thin edge' : 'no edge'}</span>` : ''}<button class="btn tiny slipb" data-slipkey="${SP}:${k}:${p.game}:${esc(p.id)}" data-ppyes="${k}">+ Slip</button></div>`; }).join('')}
      <div class="small">Anytime-goal prices carry a heavy margin: over the last three seasons the books' prices implied ${pct((((D.research || {}).props || {}).anytime_goal || {}).book_implied_mean, 1)} on average, and players scored ${pct((((D.research || {}).props || {}).anytime_goal || {}).hit, 1)}.</div></div>
  </article>`;
}
function goalieRow(x){
  const ln = (x.lines || {}).saves, key = `${x.id}:saves`, st = PL[key] || {};
  const typed = st.line != null && st.line !== '' ? numOf(st.line) : null, L = typed ?? (ln ? ln.line : Math.floor(x.saves) + 0.5);
  const pm = pSaves(x, L);
  return `<article class="pp" data-pid="${esc(x.id)}" data-g="${x.game}" data-key="saves" data-goalie="1">
    <div class="pp-who"><div class="pn"><span data-chart="g|${esc(x.id)}|saves">${esc(x.name)}</span> <span class="pill ${x.src === 'Confirmed' ? 'win' : 'ghost'}">${esc(x.src || 'Expected')}</span></div>
      <div class="ps">${chip(x.team, 1)} vs ${chip(x.opp, 1)} <span class="small">${(x.sv_pct * 100).toFixed(1)}% save rate · ${fmtN(x.shots, 0)} shots expected</span></div></div>
    <div class="pp-proj"><span class="proj num">${fmtN(x.saves, 1)}<small>saves</small></span></div>
    <div class="pp-chk">${ln ? `<div class="pp-h"><b>${esc(ln.book)}</b> line <b>${ln.line}</b> · Over <b>${fmtOdds(ln.o)}</b> · Under <b>${fmtOdds(ln.u)}</b></div><div class="pp-pc">Over <b class="num">${pct(ln.p)}</b> <span class="small">· model ${pct(ln.p_model)} · book ${pct(ln.p_book)}</span></div>${verdict(ln, 'saves')}` : '<div class="pp-h">No saves line posted yet</div>'}
      <div class="pp-in"><div class="f"><span class="clb-l">Line</span>${stepWrap(`<input type="text" inputmode="decimal" autocomplete="off" data-ppl="${esc(key)}" value="${esc(st.line ?? '')}" placeholder="${L}" aria-label="Line">`, 'line')}</div>
        <div class="seg pp-side" role="group" aria-label="Side"><button type="button" data-ppside="over" aria-pressed="${st.side !== 'under'}">Over</button><button type="button" data-ppside="under" aria-pressed="${st.side === 'under'}">Under</button></div></div>
      <div class="pp-out"><span>At ${L}: over <b>${pct(pm)}</b> · under <b>${pct(pm == null ? null : 1 - pm)}</b> (model)</span></div>
      <div class="pp-acts"><button class="btn tiny slipb" data-slipkey="${SP}:saves:${x.game}:${esc(x.id)}" data-pppick="">+ Slip</button><button class="btn tiny" data-chart="g|${esc(x.id)}|saves">Chart</button></div></div>
  </article>`;
}
function ppList(){
  const k = PPF.key, q = PPF.q.trim().toLowerCase();
  if (NHL && k === 'saves'){
    return (D.goalies || []).filter(x => (PPF.game === 'all' || x.game === PPF.game) && (!q || x.name.toLowerCase().includes(q) || x.team.toLowerCase() === q))
      .sort((a, b) => (!!(b.lines || {}).saves - !!(a.lines || {}).saves) || b.saves - a.saves);
  }
  const rows = (D.props || []).filter(p => (PPF.game === 'all' || p.game === PPF.game) && (!q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q))
    .filter(p => propVal(p, k) != null && (k === 'goals' || (p.lines || {})[k] || propVal(p, k) >= ({pts: 6, reb: 2.5, ast: 1.5, fg3m: 0.8, pra: 10, pr: 8, pa: 8, ra: 4, stl: 0.6, blk: 0.4, tov: 1, sog: 1.2, points: 0.25, assists: 0.15, blocks: 0.6}[k] ?? 0)));
  if (PPF.sort === 'value' && k !== 'goals') rows.sort((a, b) => (!!(b.lines || {})[k] - !!(a.lines || {})[k]) || bestEv((b.lines || {})[k]) - bestEv((a.lines || {})[k]) || propVal(b, k) - propVal(a, k));
  else if (k === 'goals') rows.sort((a, b) => ((b.yes || {}).atg != null) - ((a.yes || {}).atg != null) || b.p_goal - a.p_goal);
  else rows.sort((a, b) => propVal(b, k) - propVal(a, k));
  return rows;
}
function renderPPList(){
  const box = $('#pp-list'); if (!box) return;
  const rows = ppList(), k = PPF.key;
  const html = rows.slice(0, PPSHOW).map(p => NHL && k === 'saves' ? goalieRow(p) : NHL && k === 'goals' ? goalsRow(p) : ppRow(p, k)).join('');
  box.innerHTML = rows.length ? html + (rows.length > PPSHOW ? `<button class="btn more" data-ppmore="">Show more (${rows.length - PPSHOW} left)</button>` : '') :
    `<div class="empty"><div class="h3">No players match</div><p class="lede" style="margin:0">${(D.props || []).length ? 'Try another game or clear the search.' : 'Projections show once the next games are on the schedule.'}</p></div>`;
  $('#pp-count').textContent = `${rows.length} player${rows.length === 1 ? '' : 's'}${k !== 'goals' && k !== 'saves' ? ` · ${rows.filter(p => (p.lines || {})[k]).length} with a book line` : ''}`;
  SB.refresh();
}
function renderProps(){
  const v = $('#v-props');
  const games = D.games.filter(g => g.state === 'pre' && (D.props || []).some(p => p.game === g.id)).sort((a, b) => a.k.localeCompare(b.k));
  if (PPF.game !== 'all' && !games.some(g => g.id === PPF.game)) PPF.game = 'all';
  const R = (D.research || {}).props || {}, bm = R.by_market || {};
  const rk = NHL ? ({sog: 'shots_on_goal', points: 'points', assists: 'assists', blocks: 'blocked_shots'}[PPF.key]) : PPF.key;
  const bt = bm[rk];
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">Player props</h1><p class="lede">Every projection next to the sportsbook's line${(D.props || []).some(p => Object.keys(p.lines || {}).length) ? ' (DraftKings through ESPN)' : ''}. The chance blends the model with the book's own price, weighted by how much the model added in past seasons; the book is usually right. ${NHL ? 'When a regular is out, skaters at his position get part of his ice time (shots and points barely moved in past games, so those stay put).' : 'When a rotation player is out, teammates at his position get part of his minutes, mostly the bench players.'}</p></div></div>
    <div class="seg pp-types" role="group" aria-label="Market">${CFG.propTabs.map(([k, l]) => `<button type="button" data-ppk="${k}" aria-pressed="${PPF.key === k}">${l}</button>`).join('')}</div>
    <div class="toolbar"><div class="filters">
      <select id="pp-game" aria-label="Game"><option value="all">All games</option>${games.map(g => `<option value="${g.id}" ${PPF.game === g.id ? 'selected' : ''}>${g.away} @ ${g.home} · ${esc(whenDay(g.k))}</option>`).join('')}</select>
      <input type="text" id="pp-q" placeholder="Search a player or team" value="${esc(PPF.q)}" aria-label="Search players">
      ${PPF.key !== 'goals' && PPF.key !== 'saves' ? `<select id="pp-sort" aria-label="Sort"><option value="value" ${PPF.sort === 'value' ? 'selected' : ''}>Best price first</option><option value="proj" ${PPF.sort === 'proj' ? 'selected' : ''}>Highest projection</option></select>` : ''}</div>
      <span class="small" id="pp-count"></span></div>
    ${bt ? `<div class="tnote">Against ${bt.lines.toLocaleString()} past ${esc((CFG.mk[PPF.key] || PPF.key).toLowerCase())} lines, the book's price was ${bt.ll_book <= bt.ll_model ? 'closer to the result than the model' : 'about as good as the model'}, and betting the model's biggest disagreements returned ${bt.roi == null ? '–' : (bt.roi > 0 ? '+' : '') + (bt.roi * 100).toFixed(1) + '%'} per bet. Treat "good price" as a nudge, not a lock.</div>` : ''}
    <div class="pp-list" id="pp-list"></div>`;
  renderPPList();
  $('#pp-game').addEventListener('change', e => { PPF.game = e.target.value; store.set('ppf', PPF); PPSHOW = 30; renderPPList(); });
  $('#pp-q').addEventListener('input', e => { PPF.q = e.target.value; store.set('ppf', PPF); PPSHOW = 30; renderPPList(); });
  const so = $('#pp-sort'); if (so) so.addEventListener('change', e => { PPF.sort = e.target.value; store.set('ppf', PPF); renderPPList(); });
}
RENDER.props = renderProps;
document.addEventListener('input', e => {
  const el = e.target; if (!el.dataset) return;
  const key = el.dataset.ppl || el.dataset.ppo; if (!key) return;
  PL[key] = Object.assign({}, PL[key], el.dataset.ppl ? {line: el.value.trim()} : {odds: el.value.trim()}); store.set('pl', PL);
  const row = el.closest('.pp'); if (!row) return;
  clearTimeout(renderPPList._t); renderPPList._t = setTimeout(() => refreshPPRow(row), 120);
});
function refreshPPRow(row){
  const p = row.dataset.goalie ? (D.goalies || []).find(x => x.id === row.dataset.pid && x.game === row.dataset.g) : PIDX[row.dataset.g + ':' + row.dataset.pid];
  if (!p) return;
  const focus = document.activeElement && row.contains(document.activeElement) ? {sel: document.activeElement.dataset.ppl ? 'ppl' : 'ppo', pos: document.activeElement.selectionStart} : null;
  const tmp = document.createElement('div'); tmp.innerHTML = row.dataset.goalie ? goalieRow(p) : ppRow(p, row.dataset.key);
  const fresh = tmp.firstElementChild;
  // swap only the computed parts so the input being typed in keeps focus
  ['.pp-out', '.pp-h', '.pp-pc'].forEach(sel => { const a = $(sel, row), b = $(sel, fresh); if (a && b) a.outerHTML = b.outerHTML; });
  const evA = $$('.ev', row), evB = $$('.ev', fresh); evA.forEach((x, i) => { if (evB[i]) x.outerHTML = evB[i].outerHTML; });
  if (focus){ const inp = $(`[data-${focus.sel}]`, row); if (inp && document.activeElement !== inp){ inp.focus(); } }
}
document.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.ppk){ PPF.key = b.dataset.ppk; store.set('ppf', PPF); PPSHOW = 30; renderProps(); return; }
  if (b.hasAttribute('data-ppmore')){ PPSHOW += 30; renderPPList(); return; }
  const row = b.closest('.pp'); if (!row) return;
  const k = row.dataset.key, key = `${row.dataset.pid}:${k}`;
  if (b.dataset.ppside){ PL[key] = Object.assign({}, PL[key], {side: b.dataset.ppside}); store.set('pl', PL);
    $$('[data-ppside]', row).forEach(x => x.setAttribute('aria-pressed', String(x.dataset.ppside === b.dataset.ppside))); refreshPPRow(row); }
});

/* ======================================================================
   MODEL: who the model likes, why, and its record
   ====================================================================== */
const confWord = p => p >= .72 ? 'Strong' : p >= .62 ? 'Solid' : p >= .55 ? 'Lean' : 'Toss-up';
const confCls = p => p >= .72 ? 'c-strong' : p >= .62 ? 'c-solid' : p >= .55 ? 'c-lean' : 'c-tossup';
function mpCard(g){
  const m = g.model, t = m.pick_su, wp = t === g.home ? m.wp_home : 1 - m.wp_home, o = g.odds || {};
  const ml = t === g.home ? o.ml_h : o.ml_a, mk = m.mkt_wp_home == null ? null : (t === g.home ? m.mkt_wp_home : 1 - m.mkt_wp_home);
  const fin = g.state === 'post', won = fin ? ((t === g.home) === (g.hs > g.as)) : null;
  const val = ml != null ? evOf(wp, ml) : null;
  return `<article class="mp${fin ? ' done' : ''}" style="--pc:${(T[t] || {}).c1 || 'var(--ink)'}">
    <div class="mp-top"><div class="mp-mu">${chip(g.away, 1)} <span class="small">@</span> ${chip(g.home, 1)} <span class="small">${esc(whenDay(g.k))}</span></div>
      ${fin ? `<span class="wbadge ${won ? 'ok' : 'no'}">${won ? 'Won' : 'Lost'} ${g.as}–${g.hs}</span>` : `<span class="mp-conf ${confCls(wp)}">${confWord(wp)}</span>`}</div>
    <div class="mp-pick"><div class="mp-team">${chip(t)}<span class="mp-nick">${esc(nick(t))}</span></div><div class="mp-p"><span class="num">${pct(wp)}</span><span class="small">to win</span></div></div>
    <div class="mp-price"><div><div class="k">Fair price</div><div class="v num">${fmtOdds(oddsNum(wp))}</div></div><div><div class="k">Book</div><div class="v num">${ml != null ? fmtOdds(ml) : '–'}</div></div>
      <div class="mp-val">${val == null ? '<span class="small">No moneyline posted yet</span>' : val >= 0.03 ? `<b class="pos">+${Math.round(val * 100)}¢</b> per $1 at the book's price` : `The book's price ${mk != null ? `(${pct(mk)} after the margin)` : ''} is ${val >= 0 ? 'about fair' : 'already better than the model sees it'}`}</div></div>
    ${whyHtml(g)}
    <div class="mp-foot"><span class="small">${NHL ? `${fmtN(m.lam_a, 1)}–${fmtN(m.lam_h, 1)} expected goals` : `Model line ${t} ${fmtLine(-Math.abs(m.margin))}${o.spread != null ? ` · market ${fmtLine(lineFor(g, t))}` : ''}`}</span>
      <span style="display:flex;gap:8px">${fin || ml == null ? '' : `<button class="btn tiny slipb" data-slipkey="${SP}:ml:${g.id}:${t}" data-mpick="${g.id}">+ Slip ${t} ML</button>`}<button class="btn tiny" data-jump="${g.id}">Matchup</button></span></div>
  </article>`;
}
function recTile(label, w, l, sub){ return `<div class="tile"><div class="label">${label}</div><div class="v num">${w}-${l}</div><div class="small">${w + l ? pct(w / (w + l), 1) : '–'}${sub ? ' · ' + sub : ''}</div></div>`; }
function renderModel(){
  const v = $('#v-model'), R = D.model.record || {}, B = D.model.backtest || {};
  const up = D.games.filter(g => g.model && g.state === 'pre').sort((a, b) => a.k.localeCompare(b.k));
  const recent = D.games.filter(g => g.model && g.state === 'post' && g.day >= DAYS[1]).sort((a, b) => b.k.localeCompare(a.k));
  const tiles = NHL ? [recTile('Picking winners', R.su[0], R.su[1], 'this season'), recTile('Value moneylines', R.ml[0], R.ml[1], `${sign(R.ml[2], 2)}u · when 5%+ off the market`), recTile('Totals', R.ou[0], R.ou[1], 'when 6%+ off 50/50')]
    : [recTile('Picking winners', R.su[0], R.su[1], 'this season'), recTile('Against the spread', R.ats_all[0], R.ats_all[1], 'every game'), recTile('Spread leans', R.ats[0], R.ats[1], '3+ points off the line'), recTile('Totals', R.ou[0], R.ou[1], '5+ points off the line')];
  const bt = NHL ? `Tested on ${B.games?.toLocaleString()} games since 2015-16 against closing moneylines: the model picked the winner ${pct(B.su_model, 1)} of the time and the market's favorite ${pct(B.su_market, 1)}. Betting the model when it was 5%+ more confident than the market returned ${B.roi && B.roi['0.05'] ? (B.roi['0.05'][1] * 100).toFixed(1) + '%' : '–'} per bet over ${B.roi && B.roi['0.05'] ? B.roi['0.05'][0].toLocaleString() : '–'} bets.`
    : `Tested on ${B.games?.toLocaleString()} games from 2015-16 to 2025-26: the model's line missed the final margin by ${B.rmse_model} points (typical), the closing line by ${B.rmse_line}. When it disagreed with the line by 3+ points it went ${B.ats && B.ats['3'] ? B.ats['3'].join('-') : '–'} against the spread (${B.ats && B.ats['3'] ? pct(B.ats['3'][0] / (B.ats['3'][0] + B.ats['3'][1]), 1) : '–'}), below the 52.4% needed at −110.`;
  const byDay = {}; (D.model.log || []).slice().reverse().forEach(r => { (byDay[r.day] = byDay[r.day] || []).push(r); });
  const dayRows = Object.entries(byDay).slice(0, 12).map(([d, rows]) => `<details><summary class="small" style="cursor:pointer;padding:8px 0">${esc(dayLabel(d))}: winners ${rows.filter(r => r.su === 'W').length}-${rows.filter(r => r.su === 'L').length}${!NHL ? ` · spread ${rows.filter(r => r.ats === 'W').length}-${rows.filter(r => r.ats === 'L').length}` : ''}</summary>
      <div class="trend-list" style="box-shadow:none;border:1px solid var(--rule)">${rows.map(r => `<div class="pk"><span class="rp ${r.su}">${r.su}</span><div><div class="d">${esc(r.pick)} to win · ${esc(r.a)} ${r.as}, ${esc(r.h)} ${r.hs}</div>
        <div class="m">${NHL ? `model ${pct(r.pick === r.h ? r.wp_home : 1 - r.wp_home)}${r.mkt != null ? ` · market ${pct(r.pick === r.h ? r.mkt : 1 - r.mkt)}` : ''}` : `model ${r.pick} by ${fmtN(Math.abs(r.margin), 1)}${r.line != null ? ` · line ${r.h} ${fmtLine(r.line)} · ${r.ats_pick} ${r.ats === 'W' ? 'covered' : r.ats === 'L' ? 'missed' : 'pushed'}` : ''}`}</div></div><div></div></div>`).join('')}</div></details>`).join('');
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">The model</h1><p class="lede">${NHL ? 'Goals and shot ratings for every team, adjusted for opponents and weighted toward recent games, then scaled by the starting goalies.' : 'Opponent-adjusted efficiency ratings, home court, rest, and the value of every rotation player who is out.'} It is a fair-price reference: the market beats it over time, so the useful moments are when your book's price is better than both.</p></div></div>
    <div class="tiles">${tiles.join('')}</div>
    <div class="tnote">${esc(bt)}</div>
    ${up.length ? `<div class="sec-head"><h2 class="h3">Upcoming</h2><span class="small">Most confident first</span></div><div class="mp-grid">${up.sort((a, b) => Math.abs(b.model.wp_home - .5) - Math.abs(a.model.wp_home - .5)).map(mpCard).join('')}</div>` : ''}
    ${recent.length ? `<div class="sec-head"><h2 class="h3">Recent results</h2></div><div class="mp-grid">${recent.slice(0, 6).map(mpCard).join('')}</div>` : ''}
    <div class="sec-head"><h2 class="h3">Every pick this season</h2></div><div>${dayRows || '<div class="small">Results appear after the first games.</div>'}</div>`;
  SB.refresh();
}
RENDER.model = renderModel;

/* ======================================================================
   HIGH-CHANCE AND LONG SHOTS
   ====================================================================== */
let MY_ODDS = store.get('odds', {});
function valueBox(key, p, fair, book){
  const raw = MY_ODDS[key] || '', r = evMsg(p, fair, raw || (book != null ? String(book) : ''));
  return `<div class="vchk"><span class="fair">Fair price <b>${fmtOdds(fair)}</b>${book != null ? ` · book <b>${fmtOdds(book)}</b>` : ''}</span>
    <span class="vlab">Your odds ${stepWrap(`<input type="text" inputmode="numeric" autocomplete="off" spellcheck="false" placeholder="${book != null ? fmtOdds(book).replace('−', '-') : fmtOdds(fair).replace('−', '-')}" data-odds="${esc(key)}" data-p="${p}" data-fair="${fair}" data-book="${book ?? ''}" value="${esc(raw)}" aria-label="Your sportsbook odds">`, 'odds')}</span>
    <span class="ev ${r.c}" data-ev="${esc(key)}" aria-live="polite">${esc(r.t)}</span></div>`;
}
const hcKey = x => `hc:${x.game}:${x.id || x.team}:${x.key || 'ml'}:${x.t || ''}`;
const lsKey = x => `ls:${x.game}:${x.id}:${x.type}`;
const oddsFor = (key, fallback) => parseOdds(MY_ODDS[key]) ?? fallback;
function cardChartBtn(x){
  if (x.kind === 'ml') return `<button class="hc-chart" data-chart="t|${x.team}|margin|-0.5"><span class="hc-cw"><b>${esc(x.team)} game by game</b><span class="small">Wins, losses and margins</span></span><span></span><span class="go">Chart →</span></button>`;
  const stat = x.kind === 'goalie' ? 'saves' : NHL ? ({sog: 'sog', blocks: 'blocks', atg: 'goals', g2: 'goals', first_goal: 'goals', pts2: 'points', pts3: 'points', sog5: 'sog'}[x.key] || 'points') : ({dd: 'pts', td3: 'pra'}[x.key] || x.key);
  const t = x.t != null ? x.t : ({atg: 1, g2: 2, first_goal: 1, pts2: 2, pts3: 3, sog5: 5}[x.key] ?? null);
  const hits = x.hits ? `${x.hits[0]} of ${x.hits[1]}` : '';
  return `<button class="hc-chart" data-chart="${x.kind === 'goalie' ? 'g' : 'p'}|${esc(x.id)}|${stat}${t != null ? '|' + (t - 0.5) : ''}"><span class="hc-cw"><b>${hits ? `Hit in ${hits} recent games` : 'Game-by-game chart'}</b><span class="small">${t != null ? `${t}+ ${esc(CFG.short[stat] || stat)}` : esc(x.label)}${x.proj != null ? ` · projected ${fmtN(x.proj, NHL ? 2 : 1)}` : ''}</span></span><span>${x.avg != null ? `<span class="small">avg</span> <b class="num">${fmtN(x.avg, 1)}</b>` : ''}</span><span class="go">Chart →</span></button>`;
}
function hcCard(x, i){
  const g = gameOf(x.game) || {};
  const book = x.book;
  return `<article class="hc">
    <div class="hc-top"><div class="hc-p"><span class="big num">${Math.round(x.p * 100)}%</span><span class="small">chance</span></div>
      <div style="min-width:0"><div class="hc-label">${esc(x.label)}</div>
      <div class="small" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px">${chip(x.team, 1)} vs ${chip(x.opp, 1)} <span>${esc(whenDay(x.k || g.k))}</span>${x.kind === 'goalie' ? `<span class="pill ${x.src === 'Confirmed' ? 'win' : 'ghost'}">${esc(x.src || '')}</span>` : ''}${x.id ? injPill(x.team, x.name, x.id) : ''}</div></div></div>
    <div class="hc-meter" aria-hidden="true"><span style="width:${(x.p * 100).toFixed(0)}%"></span></div>
    ${cardChartBtn(x)}
    <p class="hc-why">${esc(x.reason)}</p>
    ${valueBox(hcKey(x), x.p, x.fair, book)}
    <div class="hc-acts"><span class="small">${book != null ? `The book's ${fmtOdds(book)} implies ${pct(impProb(book))}` : 'Add to the slip to bet it alone or build a parlay'}</span>
      <button class="btn tiny slipb" data-slipkey="${SP}:${x.kind === 'ml' ? 'ml' : x.key}:${x.game}:${esc(x.id || x.team)}" data-hcpick="${i}">+ Slip</button></div>
  </article>`;
}
/* the research's replay of these lists on recent seasons: [lo, hi, legs, average chance, hit rate] */
const PRB = (D.research || {}).props || {};
const seasonsTxt = s => s && s.length === 2 ? `${s[0] - 1}-${String(s[0]).slice(2)} to ${s[1] - 1}-${String(s[1]).slice(2)}` : 'recent seasons';
const rangeTxt = r => `${Math.round(r[0] * 100)}–${Math.round(Math.min(r[1], 1) * 100)}%`;
function hcCalNote(){
  if (NHL) return 'Chances come from Poisson counts calibrated on 2015-16 to 2025-26: when the model said 85%, shots and blocks happened 84–87% of the time.';
  const rows = (PRB.hc_check || []).filter(r => r[2] >= 200);
  if (!rows.length) return 'Chances come from the projection and how far real games land from it.';
  return `Chances come from the projection and how far real games land from it. Replaying this list on ${seasonsTxt(PRB.check_seasons)}: ` +
    rows.map((r, i) => `legs rated ${rangeTxt(r)} hit ${pct(r[4], 1)} of the time${i ? '' : ` (the model said ${pct(r[3], 1)} on average)`}`).join('; ') + '.';
}
function lsCalNote(){
  const rows = (PRB.ls_check || []).filter(r => r[2] >= 200 && [0.05, 0.1, 0.2].includes(r[0]));
  if (!rows.length) return 'Tail chances are mapped to how often games like these really happened.';
  return `Tail chances are mapped to how often games like these happened through 2022-23, then checked on ${seasonsTxt(PRB.check_seasons)}: ` +
    rows.map(r => `legs rated ${rangeTxt(r)} hit ${pct(r[4], 1)}`).join(', ') + '.';
}
function renderHC(){
  const v = $('#v-hc'), L = (D.high_chance || []).filter(x => (gameOf(x.game) || {}).state !== 'post');
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">High-chance picks</h1><p class="lede">Legs the model rates 80% or better: ${NHL ? 'shots on goal and blocked shots for steady players, goalie saves, and the biggest favorites' : 'round-number points, rebounds and assists for players in big roles, and the biggest favorites'}. Likely is not the same as good value: check the price before you bet.</p></div></div>
    <div class="tnote">${esc(hcCalNote())} A parlay of three 85% legs only hits about 61% of the time, and books price these legs short.</div>
    ${L.length ? `<div class="hc-grid">${L.map((x) => hcCard(x, D.high_chance.indexOf(x))).join('')}</div>` : '<div class="empty"><div class="h3">Nothing rated 80% or better right now</div><p class="lede" style="margin:0">New picks appear when the next games are on the schedule.</p></div>'}`;
  SB.refresh();
}
RENDER.hc = renderHC;
let LS_F = store.get('lsf', 'all');
function lsCard(x, i){
  const g = gameOf(x.game) || {}, started = g.state && g.state !== 'pre';
  return `<article class="hc ls">
    <div class="hc-top"><div class="hc-p"><span class="big num">${pct(x.p, x.p < 0.1 ? 1 : 0)}</span><span class="small">chance</span></div>
      <div style="min-width:0"><div class="hc-label">${esc(x.label)}</div>
      <div class="small" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px">${chip(x.team, 1)} vs ${chip(x.opp, 1)} <span>${esc(whenDay(x.k || g.k))}</span>${started ? '<span class="pill ghost">Started</span>' : ''}${injPill(x.team, x.name, x.id)}</div></div></div>
    <div class="hc-meter" aria-hidden="true"><span style="width:${Math.min(100, x.p * 100 * 2).toFixed(0)}%"></span></div>
    ${cardChartBtn(x)}
    <p class="hc-why">${esc(x.reason)}</p>
    ${valueBox(lsKey(x), x.p, x.fair, x.book)}
    <div class="hc-acts"><span class="small">${x.book != null ? `Book ${fmtOdds(x.book)} · fair ${fmtOdds(x.fair)}` : `Fair ${fmtOdds(x.fair)}: take anything longer`}</span>
      <button class="btn tiny slipb" data-slipkey="${SP}:${lsMarket(x).market}:${x.game}:${esc(x.id)}" data-lspick="${i}">+ Slip</button></div>
  </article>`;
}
function renderLS(){
  const v = $('#v-ls'), all = (D.long_shots || []).filter(x => (gameOf(x.game) || {}).state !== 'post');
  const groups = CFG.lsGroups.filter(([k]) => k === 'all' || all.some(x => x.group === k));
  if (!groups.some(([k]) => k === LS_F)) LS_F = 'all';
  const L = all.filter(x => LS_F === 'all' || x.group === LS_F);
  const AG = ((D.research || {}).props || {}).anytime_goal;
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">Long shots</h1><p class="lede">${NHL ? 'Goal scorers, multi-point nights, the first goal of the game and big shot totals' : 'Big scoring, rebounding and assist nights, plus double- and triple-doubles'}, each with the model's chance and the fair price. These lose most of the time; they're only worth it when your price beats fair.</p></div></div>
    <div class="seg" role="group" aria-label="Kind">${groups.map(([k, l]) => `<button type="button" data-lsf="${k}" aria-pressed="${LS_F === k}">${l}</button>`).join('')}</div>
    <div class="tnote">${NHL && AG ? `Anytime-goal prices run long on margin: over ${AG.lines.toLocaleString()} past lines the books implied ${pct(AG.book_implied_mean, 1)} on average and players scored ${pct(AG.hit, 1)}. Betting every player the model rated above the price returned ${(AG.bets_model_above_price[1] * 100).toFixed(1)}% per bet.` : esc(lsCalNote())}</div>
    ${L.length ? `<div class="hc-grid">${L.map(x => lsCard(x, D.long_shots.indexOf(x))).join('')}</div>` : '<div class="empty"><div class="h3">No long shots right now</div><p class="lede" style="margin:0">They appear when the next games are on the schedule.</p></div>'}`;
  SB.refresh();
}
RENDER.ls = renderLS;
function lsMarket(x){
  if (NHL){
    const m = {atg: ['atg', 'Y', null], g2: ['g2', 'Y', null], first_goal: ['first_goal', 'Y', null], pts2: ['points', 'O', 1.5], pts3: ['points', 'O', 2.5], sog5: ['sog', 'O', 4.5]}[x.key] || ['other', 'Y', null];
    return {market: m[0], side: m[1], line: m[2]};
  }
  if (x.key === 'dd' || x.key === 'td3') return {market: x.key, side: 'Y', line: null};
  return {market: x.key, side: 'O', line: x.t - 0.5};
}
document.addEventListener('input', e => {
  const el = e.target; if (!el.dataset || el.dataset.odds == null) return;
  const k = el.dataset.odds; if (el.value.trim()) MY_ODDS[k] = el.value.trim(); else delete MY_ODDS[k]; store.set('odds', MY_ODDS);
  const m = evMsg(Number(el.dataset.p), Number(el.dataset.fair), el.value.trim() || el.dataset.book);
  $$(`[data-ev="${CSS.escape(k)}"]`).forEach(o => { o.textContent = m.t; o.className = 'ev ' + m.c; });
});

/* ======================================================================
   TRENDS
   ====================================================================== */
let TSUB = store.get('tsub', 'players');
function carryNote(){
  const C = (D.research || {}).carry || {};
  if (NHL){
    const s = C.nhl_shots_on_goal || {}, g = C.nhl_goal_streak3 || {};
    return `Do runs last? Skaters who beat their shot projection 4 games running beat it next time ${pct((s['4'] || {}).next_beat_rate)} of the time, versus ${pct((s.all || {}).next_beat_rate)} for everyone; that's about ${fmtN((s['4'] || {}).next_resid, 2)} extra shots. Players who scored in 3 straight scored next time ${pct(g.next_goal_rate, 1)}, right where the projection had them (${pct(g.projected, 1)}). Hot streaks are mostly noise; the projection already knows the player.`;
  }
  const p = C.nba_pts || {}, t = C.nba_team_ats || {};
  return `Do runs last? Players who beat their points projection 4 straight games beat it next time ${pct((p['4'] || {}).next_beat_rate)} of the time, versus ${pct((p.all || {}).next_beat_rate)} for everyone. Teams that covered 4 straight covered the next one ${pct((t['4'] || {}).next_rate, 1)}. Streaks describe the past; the line already knows about them.`;
}
function playerTrendRow(x, i){
  const g = gameOf(x.game) || {}, base = x.line;
  const s = spark((x.vals || []).map((v, j) => [j, v]), {base, w: 110, h: 30});
  const word = CFG.short[x.key] || x.key;
  return `<div class="tr" data-chart="p|${esc(x.id)}|${x.key}|${base}">
    <span class="wk">${x.n}</span>
    <div><div class="tt">${esc(x.name)} ${x.dir === 'over' ? 'over' : 'under'} ${base} ${esc(word)} in ${x.n} straight</div>
      <div class="td">${chip(x.team, 1)} next: ${x.team === g.home ? 'vs' : '@'} ${chip(x.opp, 1)} ${esc(whenDay(g.k || ''))} · projected ${fmtN(x.proj, NHL ? 2 : 1)}${x.book ? ' · that is the book line' : ''}</div></div>
    <div class="side ${x.dir === 'over' ? 'up' : 'down'}">${s}<span class="go">Chart →</span>${g.state === 'pre' && (CFG.ou.includes(x.key) || x.key === 'goals') ? `<button class="btn tiny slipb" data-trleg="${i}">+ Slip</button>` : ''}</div></div>`;
}
function teamTrendRow(x){
  const nx = D.games.find(g => g.state === 'pre' && (g.home === x.team || g.away === x.team));
  return `<div class="tr" data-chart="t|${x.team}"><span class="wk">${x.n}</span>
    <div><div class="tt">${esc(nick(x.team))} have ${esc(x.what)} ${x.n} straight</div>
      <div class="td">${chip(x.team, 1)} ${resDots(x.seq.map(s => s === 'O' ? 'W' : s === 'U' ? 'L' : s), 10)}${nx ? ` · next ${nx.home === x.team ? 'vs' : '@'} ${chip(nx.home === x.team ? nx.away : nx.home, 1)} ${esc(whenDay(nx.k))}` : ''}</div></div>
    <div class="side"><span class="go">Chart →</span></div></div>`;
}
function renderTrends(){
  const v = $('#v-trends'), P = D.trends.player || [], Tm = D.trends.team || [];
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">Trends</h1><p class="lede">Players and teams on runs of ${NHL ? '3' : '4'} or more games, measured against the book's line when there is one and the projection when there isn't.</p></div></div>
    <div class="seg" role="group" aria-label="Trend type"><button type="button" data-tsub="players" aria-pressed="${TSUB === 'players'}">Players (${P.length})</button><button type="button" data-tsub="teams" aria-pressed="${TSUB === 'teams'}">Teams (${Tm.length})</button></div>
    <p class="tnote">${esc(carryNote())}</p>
    ${TSUB === 'players' ? (P.length ? `<div class="trend-list">${P.map(playerTrendRow).join('')}</div>` : '<div class="empty">No player runs right now.</div>')
      : (Tm.length ? `<div class="trend-list">${Tm.map(teamTrendRow).join('')}</div>` : '<div class="empty">No team runs right now.</div>')}`;
  SB.refresh();
}
RENDER.trends = renderTrends;

/* ======================================================================
   TIPS
   ====================================================================== */
function tipCard(n, title, stat, statTxt, why, today, how){
  return `<article class="tip"><div class="tip-n">${n}</div><div class="tip-b"><h2 class="h3">${title}</h2>
    ${stat ? `<div class="tip-stat"><span class="big">${stat}</span><span>${statTxt}</span></div>` : ''}
    <p class="tip-why">${why}</p>${today ? `<div class="tip-wk">${today}</div>` : ''}<p class="tip-how">${how}</p></div></article>`;
}
const tw = (chips, txt) => `<div class="tw">${chips ? `<span class="tw-g">${chips}</span>` : ''}<span class="tw-t">${txt}</span></div>`;
function renderTips(){
  const v = $('#v-tips'), up = D.games.filter(g => g.state === 'pre' && g.day <= (DAYS.find(d => d > M.slate) || M.slate));
  const S = (D.research || {}).situational || {}, PR = ((D.research || {}).props || {}).by_market || {};
  const cards = [];
  if (NHL){
    const gk = up.flatMap(g => ['a', 'h'].map(sd => ({g, sd, x: (g.goalies || {})[sd]}))).filter(o => o.x && o.x.name);
    const conf = gk.filter(o => o.x.src === 'Confirmed').length;
    cards.push(tipCard(1, 'Know the starting goalie', `${conf}/${gk.length}`, 'starters confirmed so far today',
      'The goalie is the biggest single input to an NHL price, and books move fast when a backup is announced. A backup start is not a free bet against that team: betting against backup starters lost about 4–5% per bet in 2019-20 through 2025-26, because the market already prices it.',
      gk.filter(o => o.x.src !== 'Confirmed').slice(0, 8).map(o => tw(chip(o.sd === 'h' ? o.g.home : o.g.away, 1), `${esc(o.x.name)} expected, not yet confirmed (${esc(o.g.away)} @ ${esc(o.g.home)}, ${esc(when(o.g.k, {hour: 'numeric', minute: '2-digit'}))})`)).join('') || tw('', 'Every probable starter is confirmed.'),
      '<b>How:</b> wait for confirmation (usually after the morning skate) before betting a side or a total, or bet early only when you have the news first.'));
    const ag = ((D.research || {}).props || {}).anytime_goal || {};
    cards.push(tipCard(2, 'Goal-scorer prices are steep', pct(ag.book_implied_mean, 1), `book implied vs ${pct(ag.hit, 1)} actual`,
      'Anytime-goal and first-goal markets carry more margin than sides and totals. Over the last three seasons the average posted price implied a 17% scorer; 15% actually scored. Betting every player the model liked more than the price still lost 8% per bet.',
      (D.long_shots || []).filter(x => x.type === 'atg' && x.book != null && x.p > impProb(x.book)).slice(0, 5).map(x => tw(chip(x.team, 1), `${esc(x.name)}: model ${pct(x.p)} vs book ${fmtOdds(x.book)} (${pct(impProb(x.book))})`)).join('') || tw('', 'No scorer is priced longer than the model today.'),
      '<b>How:</b> treat scorer props as entertainment-size bets, and shop several books: prices on the same player often differ by 50+ cents.'));
    cards.push(tipCard(3, 'Puck line or moneyline', '', '',
      'A favorite at −1.5 needs a two-goal win, including empty-netters. The model gives each team\'s chance of winning by two or more; compare it to the puck-line price instead of laying a big moneyline.',
      up.filter(g => g.model && g.odds).slice(0, 6).map(g => { const fav = g.model.wp_home >= 0.5 ? g.home : g.away, p2 = fav === g.home ? g.model.p_h_by2 : g.model.p_a_by2, pr = fav === g.home ? g.odds.sp_h : g.odds.sp_a;
        return tw(chip(fav, 1), `${esc(fav)} by 2+: model ${pct(p2)} (fair ${fairTxt(p2)})${pr != null && lineFor(g, fav) < 0 ? ` · book ${fmtOdds(pr)}` : ''}`); }).join(''),
      '<b>How:</b> if the puck-line price is longer than fair, it can be the better way to back a favorite you like.'));
  } else {
    const outs = up.flatMap(g => [g.home, g.away].flatMap(t => (D.injuries[t] || []).filter(i => i.key && i.level !== 'likely').map(i => ({g, t, i}))));
    cards.push(tipCard(1, 'Injury news is the edge', String(outs.length), 'rotation players on today\'s injury list',
      'Who plays moves NBA lines more than anything else, and statuses change through the day. In the research, the value of the rotation players who sat explained more of the final margin than rest did, and the market moves within minutes of the news.',
      outs.slice(0, 10).map(o => tw(chip(o.t, 1), `<b>${esc(o.i.name)}</b> ${esc(LEVEL_WORD[o.i.level] || o.i.status)}${o.i.min ? ` · ${fmtN(o.i.min, 0)} min a game` : ''} (${esc(o.g.away)} @ ${esc(o.g.home)})`)).join('') || tw('', 'No rotation players listed today.'),
      '<b>How:</b> check 30–60 minutes before tip, when teams confirm. If you hear first, bet first; if the line already moved, it\'s gone.'));
    const b2b = up.flatMap(g => [['h', g.home], ['a', g.away]].filter(([sd]) => g.rest && g.rest['b2b_' + sd]).map(([sd, t]) => ({g, t})));
    const r = S['Rested team vs. a team on a back-to-back (bet the rested team, road)'] || {}, rh = S['Rested team vs. a team on a back-to-back (bet the rested team, home)'] || {};
    const rr = [r, rh].filter(x => x.checked).map(x => x.checked[2]).sort();
    const fe = D.model.features || [], cf = D.model.coef || [], ib = fe.indexOf('b2b_h'), ia = fe.indexOf('b2b_a');
    const b2bPts = ib >= 0 && ia >= 0 ? Math.round((Math.abs(cf[ib + 1]) + Math.abs(cf[ia + 1])) / 2 * 2) / 2 : 2;
    cards.push(tipCard(2, 'Back-to-backs are already in the line', r.checked ? pct(r.checked[2], 1) : '–', 'rested road teams vs. tired home teams ATS, 2019-20 to 2025-26',
      `Fatigue is real (the model takes about ${b2bPts} points off a team on the second night), but the line knows. Betting the rested team against a team on a back-to-back has come in ${rr.length === 2 ? `between ${pct(rr[0], 1)} and ${pct(rr[1], 1)}` : 'near 50%'} against the spread, short of the 52.4% needed at −110.`,
      b2b.map(o => tw(chip(o.t, 1), `${esc(o.t)} on the second night of a back-to-back (${esc(o.g.away)} @ ${esc(o.g.home)})`)).join('') || tw('', 'No back-to-backs today.'),
      '<b>How:</b> use rest as a tiebreaker on top of a real reason, not as the reason.'));
    const best = (D.props || []).flatMap(p => ['reb', 'stl', 'blk'].map(k => ({p, k, ln: (p.lines || {})[k]}))).filter(o => o.ln && Math.max(o.ln.ev_o, o.ln.ev_u) >= 0.03).sort((a, b) => Math.max(b.ln.ev_o, b.ln.ev_u) - Math.max(a.ln.ev_o, a.ln.ev_u)).slice(0, 6);
    cards.push(tipCard(3, 'Pick your prop markets', PR.pts ? (PR.pts.roi * 100).toFixed(1) + '%' : '–', 'per bet on the model\'s biggest points disagreements',
      `Books price points, PRA and the combos sharply: betting the model against them lost money. Rebounds (${PR.reb ? (PR.reb.roi * 100).toFixed(1) : '–'}%), steals (${PR.stl ? (PR.stl.roi * 100).toFixed(1) : '–'}%) and blocks (${PR.blk ? (PR.blk.roi * 100).toFixed(1) : '–'}%) were close to even, and they're where the model adds a little to the book's price.`,
      best.map(o => tw(chip(o.p.team, 1), `${esc(o.p.name)} ${o.ln.ev_o >= o.ln.ev_u ? 'over' : 'under'} ${o.ln.line} ${esc(CFG.short[o.k])} (${fmtOdds(o.ln.ev_o >= o.ln.ev_u ? o.ln.o : o.ln.u)}): about +${Math.round(Math.max(o.ln.ev_o, o.ln.ev_u) * 100)}¢ per $1`)).join('') || tw('', 'Nothing in those markets beats the price by 3¢ right now.'),
      '<b>How:</b> keep prop bets small and spread out; the edge, if any, is thin.'));
  }
  const moved = up.filter(g => g.odds && (NHL ? (g.odds.ml_h_open != null && g.odds.ml_h != null && Math.abs(impProb(g.odds.ml_h) - impProb(g.odds.ml_h_open)) >= 0.03) : (g.odds.spread_open != null && g.odds.spread != null && Math.abs(g.odds.spread - g.odds.spread_open) >= 1)));
  cards.push(tipCard(cards.length + 1, 'Shop the number, and watch it move', String(moved.length), `game${moved.length === 1 ? '' : 's'} with a real move since the open`,
    'The price you get matters more than the side you pick. Lines move when money or news arrives; getting a better number than the close is the most reliable sign of skill there is.',
    moved.map(g => tw(`${chip(g.away, 1)} @ ${chip(g.home, 1)}`, NHL ? `${esc(g.home)} moneyline ${fmtOdds(g.odds.ml_h_open)} → ${fmtOdds(g.odds.ml_h)}` : `${esc(g.home)} ${fmtLine(g.odds.spread_open)} → ${fmtLine(g.odds.spread)}`)).join('') || tw('', 'No big moves since the open.'),
    '<b>How:</b> compare two or three books before every bet, and log the line you got; My bets shows whether you beat the close.'));
  const cl = SB.bets().flatMap(b => b.legs.filter(l => l.sport === SP).map(SB.clv)).filter(c => c && c.closed);
  const beat = cl.filter(c => c.v > 0).length;
  cards.push(tipCard(cards.length + 1, 'Parlays multiply the margin', '+596', 'is fair for three −110 legs; most books pay about +600',
    'Each leg carries the book\'s margin, and a parlay stacks them: three coin-flip legs at −110 are a 12.5% shot, and you need every one. Same-game legs are correlated, so their real chance isn\'t the multiplication either.',
    cl.length ? tw('', `Your ${SP.toUpperCase()} legs beat the closing price ${beat} of ${cl.length} times.`) : '',
    '<b>How:</b> build parlays from legs that are each a good price on their own, or keep them small.'));
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">Betting tips</h1><p class="lede">What the research says actually moves the needle in the ${SP.toUpperCase()}, applied to today's games.</p></div></div><div class="tips">${cards.join('')}</div>`;
}
RENDER.tips = renderTips;

/* ======================================================================
   WHAT MATTERS
   ====================================================================== */
function renderMatters(){
  const v = $('#v-matters'), B = D.model.backtest || {}, R = D.research || {}, PR = (R.props || {}).by_market || {}, S = R.situational || {};
  const facts = NHL ? [
    [pct(B.su_model, 1), `of winners picked by the model (${B.games?.toLocaleString()} games since 2015-16); the market's favorite won ${pct(B.su_market, 1)}`],
    [(B.ll_model || 0).toFixed(3), `the model's log loss against ${(B.ll_market || 0).toFixed(3)} for closing moneylines (lower is better): the market knows more`],
    ['Goalies', 'a starter\'s save rate, regressed hard toward average, moves the line more than any team stat'],
    ['Shots', 'shot ratings predict future goals better than past goals do, so the model leans on them (60/40)']]
    : [[`${B.rmse_model}`, `points: how far the model's line typically misses the final margin; the closing line misses by ${B.rmse_line}`],
      [pct(B.su_model, 1), `winners picked by the model; the closing favorite won ${pct(B.su_market, 1)}`],
      [String(((B.factor_corr || {})['Efficiency ratings'] || 0).toFixed(2)), 'correlation of efficiency ratings with the final margin, the strongest single input'],
      [String(((B.factor_corr || {})['Who is missing'] || 0).toFixed(2)), 'for the value of rotation players who sat, the second strongest']];
  const mk = Object.entries(PR).sort((a, b) => b[1].lines - a[1].lines);
  const nameOf = k => NHL ? ({points: 'Points', assists: 'Assists', shots_on_goal: 'Shots on goal', blocked_shots: 'Blocked shots'}[k] || k) : (CFG.mk[k] || k);
  const sit = Object.entries(S).map(([k, x]) => { const f = x.found || [], c = x.checked || [];
    const fmt = a => !a.length ? '–' : a.length === 3 ? `${a[0]}-${a[1]} (${pct(a[2], 1)})` : `${a[0]} bets, ${a[1] == null ? '–' : (a[1] * 100).toFixed(1) + '%'}`;
    return `<tr><td>${esc(k)}</td><td class="r num">${fmt(f)}</td><td class="r num">${fmt(c)}</td></tr>`; }).join('');
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">What matters</h1><p class="lede">The research behind the ${SP.toUpperCase()} page: ${NHL ? 'every game since 2010-11, closing lines since 2010-11 (most seasons), and ' : 'every game since 2011-12, closing lines throughout, and '}real player-prop lines since 2023-24. Every test predicts each game using only what was known before it.</p></div></div>
    <div class="facts">${facts.map(([v_, t]) => `<div class="fact"><div class="v num">${esc(v_)}</div><p>${esc(t)}</p></div>`).join('')}</div>
    <div class="sec-head"><h2 class="h3">Player props against the books</h2><span class="small">${mk.reduce((a, [, x]) => a + x.lines, 0).toLocaleString()} real lines</span></div>
    <div class="tbl-wrap"><table class="grid"><thead><tr><th>Market</th><th class="r">Lines</th><th class="r">Over hit</th><th class="r">Book error</th><th class="r">Model error</th><th class="r">Model's best bets</th></tr></thead>
      <tbody>${mk.map(([k, x]) => `<tr><td>${esc(nameOf(k))}</td><td class="r num">${x.lines.toLocaleString()}</td><td class="r num">${pct(x.over_rate, 1)}</td><td class="r num">${x.ll_book.toFixed(3)}</td><td class="r num">${x.ll_model.toFixed(3)}</td><td class="r num" style="color:${x.roi > 0 ? 'var(--win)' : 'var(--loss)'}">${x.bets.toLocaleString()} bets, ${(x.roi * 100).toFixed(1)}%</td></tr>`).join('')}</tbody></table></div>
    <p class="small" style="margin:0">Error is log loss on the over/under result (lower is better). Unders hit more often than overs in every market: books shade overs because that's what people bet.</p>
    <div class="sec-head"><h2 class="h3">Popular angles, tested twice</h2><span class="small">Found on older seasons, checked on recent ones</span></div>
    <div class="tbl-wrap"><table class="grid"><thead><tr><th>Angle</th><th class="r">${NHL ? '2010-11 to 2018-19' : '2011-12 to 2018-19'}</th><th class="r">2019-20 to 2025-26</th></tr></thead><tbody>${sit}</tbody></table></div>
    <p class="small" style="margin:0">${NHL ? 'Moneyline angles show bets and return per bet at closing prices.' : 'Spread and total angles show wins and losses at the closing line; 52.4% breaks even at −110.'} None holds up well enough to bet on its own.</p>
    <div class="sec-head"><h2 class="h3">Do streaks carry over?</h2></div><p class="tnote">${esc(carryNote())}</p>`;
}
RENDER.matters = renderMatters;

/* ======================================================================
   TEAMS
   ====================================================================== */
let TS = store.get('ts', {k: NHL ? 'pts' : 'net', dir: 'desc'});
function renderTeams(){
  const v = $('#v-teams');
  const cols = NHL ? [['team', 'Team'], ['rec', 'W-L-OTL'], ['pts', 'Pts'], ['l10', 'Last 10'], ['gf', 'GF/G'], ['ga', 'GA/G'], ['att', 'Attack rk'], ['def', 'Defense rk'], ['gk', 'Usual goalie'], ['ou', 'O/U'], ['streak', 'Streak'], ['inj', 'Out']]
    : [['team', 'Team'], ['rec', 'W-L'], ['l10', 'Last 10'], ['net', 'Net rating'], ['off', 'Offense rk'], ['def', 'Defense rk'], ['pace', 'Pace'], ['ats', 'ATS'], ['ou', 'O/U'], ['pd', 'Diff/G'], ['streak', 'Streak'], ['inj', 'Out']];
  const val = (t, k) => { const x = T[t]; switch (k){
    case 'team': return x.nick; case 'rec': return x.rec ? (x.rec.W - x.rec.L) / Math.max(1, x.gp || 1) : 0; case 'pts': return x.pts ?? 0; case 'l10': return x.l10 ? x.l10.W : 0;
    case 'gf': return x.gf ?? 0; case 'ga': return -(x.ga ?? 9); case 'att': return -(x.rk || {}).att; case 'def': return -(x.rk || {}).def; case 'gk': return (x.rating || {}).gk_sv ?? 0;
    case 'net': return (x.rating || {}).net ?? 0; case 'off': return -(x.rk || {}).off; case 'pace': return (x.rating || {}).pace ?? 0;
    case 'ats': return x.ats ? x.ats.W - x.ats.L : 0; case 'ou': return x.ou ? x.ou.O - x.ou.U : 0; case 'pd': return x.pd ?? 0; case 'streak': return (x.streak || '').startsWith('W') ? Number(x.streak.slice(1)) : -Number((x.streak || 'L0').slice(1)); case 'inj': return x.inj || 0; } return 0; };
  const rows = Object.keys(T).sort((a, b) => { const va = val(a, TS.k), vb = val(b, TS.k); const c = typeof va === 'string' ? va.localeCompare(vb) : va - vb; return TS.dir === 'desc' ? -c : c; });
  const cell = (t, k) => { const x = T[t], r = x.rating || {}, rk = x.rk || {}; switch (k){
    case 'team': return `<td>${chip(t, 1)} ${esc(x.nick)}</td>`; case 'rec': return `<td class="r num">${recTxt(x.rec)}</td>`; case 'pts': return `<td class="r num">${x.pts ?? 0}</td>`;
    case 'l10': return `<td class="r num">${recTxt(x.l10)}</td>`; case 'gf': return `<td class="r num">${fmtN(x.gf, 2)}</td>`; case 'ga': return `<td class="r num">${fmtN(x.ga, 2)}</td>`;
    case 'att': return `<td class="r num">${rk.att ?? '–'}</td>`; case 'def': return `<td class="r num">${rk.def ?? '–'}</td>`; case 'gk': return `<td>${esc(r.gk_name || '–')} <span class="small">${r.gk_sv ? (r.gk_sv * 100).toFixed(1) + '%' : ''}</span></td>`;
    case 'net': return `<td class="r num">${sign(r.net, 1)} <span class="small">#${rk.net ?? '–'}</span></td>`; case 'off': return `<td class="r num">${rk.off ?? '–'}</td>`; case 'pace': return `<td class="r num">${fmtN(r.pace, 1)}</td>`;
    case 'ats': return `<td class="r num">${wl(x.ats)}</td>`; case 'ou': return `<td class="r num">${ouTxt(x.ou)}</td>`; case 'pd': return `<td class="r num">${sign(x.pd, 1)}</td>`;
    case 'streak': return `<td class="r num">${esc(x.streak || '–')}</td>`; case 'inj': return `<td class="r num">${x.inj || ''}</td>`; } return '<td></td>'; };
  v.innerHTML = `<div class="sec-head"><div><h1 class="h2">Teams</h1><p class="lede">${NHL ? 'Records, goals for and against, the model\'s attack and defense ranks, and each team\'s usual starting goalie.' : 'Records, the model\'s efficiency ratings (points per 100 possessions better than an average team), against-the-spread and over/under records from the closing lines.'} Tap a column to sort.</p></div></div>
    <div class="tbl-wrap"><table class="grid tight"><thead><tr>${cols.map(([k, l]) => `<th class="sortable${k === 'team' || k === 'gk' ? '' : ' r'}" data-sort="${k}" tabindex="0" aria-sort="${TS.k === k ? (TS.dir === 'desc' ? 'descending' : 'ascending') : 'none'}">${l}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(t => `<tr data-chart="t|${t}">${cols.map(([k]) => cell(t, k)).join('')}</tr>`).join('')}</tbody></table></div>`;
}
RENDER.teams = renderTeams;
document.addEventListener('click', e => {
  const th = e.target.closest('th[data-sort]'); if (!th) return;
  const k = th.dataset.sort; TS = {k, dir: TS.k === k && TS.dir === 'desc' ? 'asc' : 'desc'}; store.set('ts', TS); renderTeams();
});

/* ======================================================================
   CHARTS: any player, goalie or team, game by game, against a line
   ====================================================================== */
let LOGS = null, LOGS_P = null, CH = null;
function loadLogs(){
  if (LOGS) return Promise.resolve(LOGS);
  if (!LOGS_P) LOGS_P = fetch('data/logs.json?t=' + Math.floor(Date.now() / 600000), {cache: 'no-cache'}).then(r => r.ok ? r.json() : null).then(j => { LOGS = j || {players: {}, teams: {}, goalies: {}}; return LOGS; }).catch(() => { LOGS = {players: {}, teams: {}, goalies: {}}; return LOGS; });
  return LOGS_P;
}
const rowObj = (cols, r) => { const o = {}; cols.forEach((c, i) => o[c] = r[i]); return o; };
function chartRows(){
  if (!LOGS || !CH) return [];
  if (CH.kind === 'p'){ const P = (LOGS.players || {})[CH.id]; return P ? P.rows.map(r => rowObj(LOGS.pcols, r)) : []; }
  if (CH.kind === 'g'){ const P = (LOGS.goalies || {})[CH.id]; return P ? P.rows.map(r => rowObj(LOGS.gcols, r)).filter(r => r.start || r.shots > 10) : []; }
  return ((LOGS.teams || {})[CH.id] || []).map(r => rowObj(LOGS.tcols, r));
}
function statOf(r, k){
  if (CH.kind === 't'){ if (k === 'margin') return (r.pf ?? r.gf) - (r.pa ?? r.ga); if (k === 'total') return (r.pf ?? r.gf) + (r.pa ?? r.ga); return null; }
  if (k === 'pra') return r.pts + r.reb + r.ast; if (k === 'pr') return r.pts + r.reb; if (k === 'pa') return r.pts + r.ast; if (k === 'ra') return r.reb + r.ast;
  return r[k];
}
function nextFor(){
  if (CH.kind === 't') return D.games.find(g => g.state === 'pre' && (g.home === CH.id || g.away === CH.id)) || null;
  const p = CH.kind === 'g' ? (D.goalies || []).find(x => x.id === CH.id) : (D.props || []).find(x => x.id === CH.id);
  return p ? {item: p, g: gameOf(p.game)} : null;
}
function chartStats(){
  if (CH.kind === 't') return NHL ? [['margin', 'Goal diff'], ['total', 'Total goals']] : [['margin', 'Margin'], ['total', 'Total points']];
  if (CH.kind === 'g') return CFG.goalieStats;
  return CFG.chartStats;
}
function openChart(spec){
  const [kind, id, stat, line] = spec.split('|');
  CH = {kind, id, stat: stat || null, win: store.get('cwin', 'l10'), line: line != null && line !== '' ? Number(line) : null, side: 'over', odds: ''};
  if (!CH.stat || !chartStats().some(([k]) => k === CH.stat)) CH.stat = chartStats()[0][0];
  $('#cscrim').hidden = false; $('#csheet').hidden = false; document.body.style.overflow = 'hidden';
  $('#csheet').innerHTML = '<div class="small">Loading…</div>';
  loadLogs().then(() => renderChart(true));
}
function closeChart(){ $('#cscrim').hidden = true; $('#csheet').hidden = true; $('#csheet').innerHTML = ''; document.body.style.overflow = ''; CH = null; }
/* a team's margin chart is read against its spread (covered or not); everything else against an over/under line */
const isSpreadChart = () => !!CH && CH.kind === 't' && CH.stat === 'margin';
const half5 = v => Math.round(v * 2) / 2 || 0;
function defaultLine(){
  if (CH.kind === 't'){
    const nx = nextFor(); if (!nx) return null; const o = nx.odds || {}, m = nx.model;
    if (CH.stat === 'total') return o.total ?? (m && m.total != null ? (NHL ? Math.floor(m.total) + 0.5 : half5(m.total)) : null);
    const ln = lineFor(nx, CH.id); if (ln != null) return ln;
    if (!m) return null;
    if (NHL) return (CH.id === nx.home ? m.wp_home : 1 - m.wp_home) >= 0.5 ? -1.5 : 1.5;
    return half5(-(CH.id === nx.home ? m.margin : -m.margin));
  }
  const n = nextFor(); if (!n) return null;
  const ln = ((n.item.lines || {})[CH.stat] || {}).line; if (ln != null) return ln;
  const pj = CH.stat === 'goals' ? null : CH.kind === 'g' ? n.item.saves : (n.item.proj || {})[CH.stat];
  return pj != null ? Math.floor(pj) + 0.5 : (CH.stat === 'goals' ? 0.5 : null);
}
/* did game value v beat the line? true, false, or null for a push */
function hitOf(v, L){
  if (L == null || v == null) return null;
  if (isSpreadChart()){ const d = v + L; return d > 0 ? true : d < 0 ? false : null; }
  if (v === L) return null;
  return CH.side === 'under' ? v < L : v > L;
}
/* bars for each game, the line dashed across them, and a divider where this season starts */
function barSvg(vals, labels, ref, refLabel, hits, sep){
  const W = 720, H = 230, pl = 34, pr = 10, pt = 18, pb = 30, n = vals.length;
  const mx = Math.max(1, ...vals, ref ?? 0) * 1.12, mn = Math.min(0, ...vals, ref ?? 0);
  const x = i => pl + (i + 0.5) * (W - pl - pr) / n, bw = Math.max(6, (W - pl - pr) / n * 0.62);
  const y = v => pt + (mx - v) * (H - pt - pb) / ((mx - mn) || 1);
  const ticks = []; const step = Math.max(1, Math.ceil((mx - mn) / 5)); for (let t = Math.ceil(mn); t <= mx; t += step) ticks.push(t);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Game by game">`;
  ticks.forEach(t => { s += `<line class="ax" x1="${pl}" x2="${W - pr}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="yl" x="${pl - 6}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${t}</text>`; });
  vals.forEach((v, i) => {
    const h = hits[i], cls = h == null ? '' : h ? 'hi' : 'lo';
    const y0 = y(Math.max(0, mn)), y1 = y(v);
    s += `<rect class="bar ${cls}" x="${(x(i) - bw / 2).toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1.5, Math.abs(y0 - y1)).toFixed(1)}" rx="2"/>`;
    s += `<text class="pv" x="${x(i).toFixed(1)}" y="${(Math.min(y0, y1) - 4).toFixed(1)}">${Number.isInteger(v) ? v : v.toFixed(1)}</text>`;
    if (n <= 20 || i % 2 === 0) s += `<text class="xl" x="${x(i).toFixed(1)}" y="${H - 12}" text-anchor="middle">${esc(labels[i])}</text>`;
  });
  if (sep > 0 && sep < n){ const xs = (x(sep - 1) + x(sep)) / 2; s += `<line class="sdiv" x1="${xs.toFixed(1)}" x2="${xs.toFixed(1)}" y1="${pt - 10}" y2="${H - pb}"/><text class="slab" x="${(xs + 5).toFixed(1)}" y="${pt - 3}">${esc(M.season)}</text>`; }
  if (ref != null) s += `<line class="refl" x1="${pl}" x2="${W - pr}" y1="${y(ref).toFixed(1)}" y2="${y(ref).toFixed(1)}" stroke-dasharray="6 4"/><text class="avgt" x="${W - pr}" y="${(y(ref) - 5).toFixed(1)}" text-anchor="end">${esc(refLabel)}</text>`;
  return s + '</svg>';
}
const PREV_SEASON = (() => { const y0 = Number(String(M.season || '').slice(0, 4)); return y0 ? `${y0 - 1}-${String(y0).slice(2)}` : 'Last'; })();
function renderChart(first){
  const sh = $('#csheet'); if (!CH || !sh) return;
  const all = chartRows().filter(r => statOf(r, CH.stat) != null);
  if (CH.kind !== 't' && !all.length && !nextFor()){ sh.innerHTML = `<div class="cs-head"><h2 class="h3" id="cs-title">No game log yet</h2><button class="btn tiny" data-cclose="">Close</button></div><p class="small">This player hasn't played enough games for a chart.</p>`; return; }
  if (first && CH.line == null) CH.line = defaultLine();
  const rows = CH.win === 'l10' ? all.slice(-10) : CH.win === 'l20' ? all.slice(-20) : all;
  const vals = rows.map(r => statOf(r, CH.stat));
  const labels = rows.map(r => (r.home ? '' : '@') + r.opp);
  const L = CH.line, spread = isSpreadChart();
  const hitArr = vals.map(v => hitOf(v, L));
  const hits = hitArr.filter(h => h === true).length, pushes = L == null ? 0 : hitArr.filter(h => h == null).length;
  const sep = rows.findIndex(r => r.day >= SEASON_START);
  const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  const n = nextFor(), ng = CH.kind === 't' ? n : (n && n.g) || null;
  const meta = CH.kind === 't' ? {n: T[CH.id].name, t: CH.id, p: recTxt((T[CH.id] || {}).rec)} : (((CH.kind === 'g' ? LOGS.goalies : LOGS.players) || {})[CH.id] || {n: n && n.item ? n.item.name : '', t: n && n.item ? n.item.team : '', p: ''});
  const toWin = spread && L === -0.5;
  const sideWord = toWin ? `${CH.id} wins` : spread ? `${CH.id} ${fmtLine(L)}` : `${CH.side} ${L}`;
  /* the model's chance for the next game at this line, and what a price would be worth */
  let model = '';
  if (L != null && ng && ng.state === 'pre'){
    let p = null, bookO = null, bookTxt = '';
    if (CH.kind === 't'){
      const o = ng.odds || {};
      p = modelP(toWin ? {market: 'ml', game: ng.id, team: CH.id} : spread ? {market: 'spread', game: ng.id, team: CH.id, line: L} : {market: 'total', game: ng.id, line: L, side: CH.side === 'under' ? 'U' : 'O'});
      if (toWin){ bookO = CH.id === ng.home ? o.ml_h : o.ml_a; if (bookO != null) bookTxt = ` · book moneyline ${fmtOdds(bookO)}`; }
      else if (spread && lineFor(ng, CH.id) === L) bookO = CH.id === ng.home ? o.sp_h : o.sp_a;
      if (!spread && o.total === L) bookO = CH.side === 'under' ? o.u : o.o;
      if (spread && !toWin && lineFor(ng, CH.id) != null) bookTxt = ` · book line ${CH.id} ${fmtLine(lineFor(ng, CH.id))}`;
      if (!spread && o.total != null) bookTxt = ` · book total ${o.total}`;
    } else if (n && n.item){
      let pm = null;
      if (CH.kind === 'g') pm = pSaves(n.item, L);
      else if (CH.stat === 'goals') pm = pAtLeastNHL('goals', n.item.proj.goals, Math.floor(L) + 1);
      else if ((n.item.proj || {})[CH.stat] != null) pm = pOver(CH.stat, n.item.proj[CH.stat], L);
      const ln = (n.item.lines || {})[CH.stat];
      if (pm != null) p = CH.side === 'under' ? 1 - pm : pm;
      if (ln && ln.line === L) bookO = CH.side === 'under' ? ln.u : ln.o;
      if (ln) bookTxt = ` · book line ${ln.line} (${fmtOdds(ln.o)}/${fmtOdds(ln.u)})`;
    }
    if (p != null){
      const O = parseOdds(CH.odds) ?? bookO, r = O != null ? evMsg(p, oddsNum(p), String(O)) : null;
      model = `<div class="clb-m"><span class="big num">${pct(p)}</span><span>model chance ${esc(sideWord)} next game · fair ${fairTxt(p)}${bookTxt}</span></div>${r ? `<div class="ev ${r.c}">${esc(r.t)}${parseOdds(CH.odds) == null ? ` (at the book's ${fmtOdds(O)})` : ''}</div>` : ''}`;
    }
  }
  const stats = chartStats();
  const sub = [meta.p, ng ? `next ${ng.home === meta.t ? 'vs' : '@'} ${ng.home === meta.t ? ng.away : ng.home} ${whenDay(ng.k)}` : ''].filter(Boolean).map(esc).join(' · ');
  const head = `<div class="cs-head"><div><h2 class="h3" id="cs-title">${chip(meta.t, 1)} ${esc(meta.n)}</h2>${sub ? `<div class="cs-sub">${sub}</div>` : ''}</div><button class="btn tiny" data-cclose="" id="cs-close">Close</button></div>
    <div class="cs-pick"><div class="seg" role="group" aria-label="Stat">${stats.map(([k, l]) => `<button type="button" data-cstat="${k}" aria-pressed="${CH.stat === k}">${l}</button>`).join('')}</div>
      <div class="seg" role="group" aria-label="Games">${[['l10', 'Last 10'], ['l20', 'Last 20'], ['all', 'All']].map(([k, l]) => `<button type="button" data-cwin="${k}" aria-pressed="${CH.win === k}">${l}</button>`).join('')}</div></div>`;
  const shown = vals.length - pushes;
  const hist = L == null ? `<div class="clb-hist">Average <b>${fmtN(avg, 1)}</b> over ${vals.length} games</div>`
    : spread ? `<div class="clb-hist">${toWin ? `${esc(CH.id)} won <b>${hits} of ${shown}</b> games shown` : `${esc(CH.id)} ${fmtLine(L)} would have covered in <b>${hits} of ${shown}</b> games shown`} (${shown ? pct(hits / shown) : '–'})${pushes ? ` · ${pushes} push${pushes > 1 ? 'es' : ''}` : ''} · average margin <b>${sign(avg, 1)}</b></div>`
    : `<div class="clb-hist">${CH.side === 'under' ? 'Under' : 'Over'} ${L} in <b>${hits} of ${shown}</b> games shown (${shown ? pct(hits / shown) : '–'})${pushes ? ` · ${pushes} push${pushes > 1 ? 'es' : ''}` : ''} · average <b>${fmtN(avg, 1)}</b></div>`;
  const box = `<div class="clb"><div class="clb-in"><div class="f"><span class="clb-l">${spread ? CFG.spread : 'Line'}</span>${stepWrap(`<input type="text" inputmode="decimal" autocomplete="off" data-cl="line" value="${L ?? ''}" aria-label="${spread ? CFG.spread : 'Line'}">`, spread ? 'spread' : 'line')}</div>
      <div class="f"><span class="clb-l">Odds</span>${stepWrap(`<input type="text" inputmode="numeric" autocomplete="off" data-cl="odds" value="${esc(CH.odds)}" placeholder="-110" aria-label="Odds">`, 'odds')}</div>
      ${spread ? '' : `<div class="seg" role="group" aria-label="Side"><button type="button" data-clside="over" aria-pressed="${CH.side === 'over'}">Over</button><button type="button" data-clside="under" aria-pressed="${CH.side === 'under'}">Under</button></div>`}</div>
    <div class="clb-out" id="clb-out">${hist}${model}</div>
    ${ng && ng.state === 'pre' && L != null ? '<div class="clb-act"><button class="btn tiny stripe" data-cladd="">+ Slip this line</button></div>' : ''}</div>`;
  const cols = CH.kind === 't' ? 5 : 2 + stats.length;
  const cv = (h, txt) => `<span class="${h == null ? '' : h ? 'cv-w' : 'cv-l'}">${txt}</span>`;
  const teamCells = r => {
    const pf = r.pf ?? r.gf, pa = r.pa ?? r.ga, tot = pf + pa, wl_ = pf > pa ? 'W' : pf < pa ? 'L' : 'T';
    const ouC = r.total == null ? '–' : cv(tot > r.total ? true : tot < r.total ? false : null, `${r.total} ${tot > r.total ? 'o' : tot < r.total ? 'u' : 'p'}`);
    if (NHL) return `<td class="r num">${cv(wl_ === 'W' ? true : wl_ === 'L' ? false : null, wl_)} ${pf}–${pa}</td><td class="r num">${r.ml != null ? fmtOdds(r.ml) : '–'}</td><td class="r num">${ouC}</td>`;
    const c = r.line == null ? null : (pf - pa + r.line > 0 ? true : pf - pa + r.line < 0 ? false : null);
    return `<td class="r num">${cv(wl_ === 'W' ? true : wl_ === 'L' ? false : null, wl_)} ${pf}–${pa}</td><td class="r num">${r.line == null ? '–' : cv(c, fmtLine(r.line))}</td><td class="r num">${ouC}</td>`;
  };
  let seen = false;
  const body = rows.slice().reverse().map(r => {
    const old = r.day < SEASON_START, div = old && !seen ? `<tr class="sea"><td colspan="${cols}">${esc(PREV_SEASON)} season</td></tr>` : '';
    if (old) seen = true;
    return div + `<tr><td>${esc(shortDay(r.day))}</td><td>${r.home ? '' : '@'}${esc(r.opp)}</td>${CH.kind === 't' ? teamCells(r) : stats.map(([k]) => `<td class="r num${k === CH.stat ? ' sel' : ''}">${statOf(r, k) ?? '–'}</td>`).join('')}</tr>`;
  }).join('');
  const tbl = `<div class="cs-tbl"><table class="grid"><thead><tr><th>Date</th><th>Opp</th>${CH.kind === 't' ? `<th class="r">Result</th><th class="r">${NHL ? 'Moneyline' : 'Spread'}</th><th class="r">Total</th>` : stats.map(([k, l]) => `<th class="r${k === CH.stat ? ' sel' : ''}">${l}</th>`).join('')}</tr></thead>
    <tbody>${body}</tbody></table></div>`;
  const ref = L == null ? null : spread ? -L : L;
  sh.innerHTML = head + `<div class="cs-chart">${vals.length ? barSvg(vals, labels, ref, toWin ? 'win' : spread ? `${CH.id} ${fmtLine(L)}` : String(L), hitArr, sep) : '<div class="small">No games yet.</div>'}</div>` + box + tbl;
}
document.addEventListener('click', e => {
  const c = e.target.closest('[data-chart]'); if (c && !e.target.closest('button:not([data-chart]), a, input, select, label')){ openChart(c.dataset.chart); return; }
  const b = e.target.closest('button'); if (!b || !CH) return;
  if (b.dataset.cstat){ CH.stat = b.dataset.cstat; CH.line = defaultLine(); renderChart(); return; }
  if (b.dataset.cwin){ CH.win = b.dataset.cwin; store.set('cwin', CH.win); renderChart(); return; }
  if (b.dataset.clside){ CH.side = b.dataset.clside; renderChart(); return; }
  if (b.hasAttribute('data-cclose')) closeChart();
});
document.addEventListener('input', e => {
  const el = e.target; if (!el.dataset || !el.dataset.cl || !CH) return;
  if (el.dataset.cl === 'line'){ const n = numOf(el.value); CH.line = n; } else CH.odds = el.value.trim();
  clearTimeout(renderChart._t); renderChart._t = setTimeout(() => { const keep = el.dataset.cl, pos = el.selectionStart; renderChart(); const inp = $(`[data-cl="${keep}"]`); if (inp){ inp.focus(); try { inp.setSelectionRange(pos, pos); } catch(err){} } }, 250);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && CH){ closeChart(); return; }
  const c = e.target.closest && e.target.closest('[data-chart]');
  if (c && (e.key === 'Enter' || e.key === ' ') && e.target === c){ e.preventDefault(); openChart(c.dataset.chart); }
});
$('#cscrim').addEventListener('click', closeChart);

/* ======================================================================
   BETS: the shared slip; this page supplies the model's chance for each leg
   ====================================================================== */
const half = L => Number.isInteger(Number(L)) ? 0.5 : 0;
function skellam(lh, la){ const m = []; for (let i = 0; i < 13; i++){ m[i] = []; for (let j = 0; j < 13; j++) m[i][j] = poisPmf(i, lh) * poisPmf(j, la); } return m; }
function modelP(l){
  const g = gameOf(l.game); if (!g || g.state !== 'pre') return null;
  const m = g.model, home = l.team === g.home, L = l.line == null || l.line === '' ? null : Number(l.line);
  if (m && l.market === 'ml') return home ? m.wp_home : 1 - m.wp_home;
  if (m && (l.market === 'spread' || l.market === 'total' || l.market === 'team_total')){
    if (L == null) return null;
    if (NHL){
      const M_ = skellam(m.lam_h, m.lam_a); let p = 0;
      for (let i = 0; i < 13; i++) for (let j = 0; j < 13; j++){
        const d = home ? i - j : j - i, tot = i + j, tt = home ? i : j;
        // a tie after regulation ends in a one-goal game either way, split evenly (as the model's win chance does)
        if (l.market === 'spread') p += d !== 0 ? (d + L > 0 ? M_[i][j] : 0) : Math.abs(L) < 1 ? M_[i][j] / 2 : L > 0 ? M_[i][j] : 0;
        if (l.market === 'total' && (l.side === 'U' ? tot < L : tot > L)) p += M_[i][j];
        if (l.market === 'team_total' && (l.side === 'U' ? tt < L : tt > L)) p += M_[i][j];
      }
      return Math.min(0.995, Math.max(0.005, p));
    }
    const SD = M.resid_sd || 13.3, SDT = M.resid_t || 19.2;
    if (l.market === 'spread'){ const mm = home ? m.margin : -m.margin; return ncdf((mm + L - half(L)) / SD); }
    if (l.market === 'total') return l.side === 'U' ? ncdf((L - half(L) - m.total) / SDT) : 1 - ncdf((L + half(L) - m.total) / SDT);
    const tt = (m.total + (home ? m.margin : -m.margin)) / 2;
    return l.side === 'U' ? ncdf((L - half(L) - tt) / (SDT * 0.7)) : 1 - ncdf((L + half(L) - tt) / (SDT * 0.7));
  }
  if (!l.player) return null;
  if (NHL && (l.market === 'saves' || l.market === 'ga')){
    const gx = (D.goalies || []).find(x => x.id === String(l.player) && x.game === g.id); if (!gx || L == null || l.market !== 'saves') return null;
    const ln = (gx.lines || {}).saves, pm = pSaves(gx, L), p = ln && ln.line === L ? blendP('saves', pm, ln.p_book) : pm;
    return l.side === 'U' ? 1 - p : p;
  }
  const p = PIDX[g.id + ':' + String(l.player)]; if (!p) return null;
  if (NHL){
    if (l.market === 'atg') return p.p_goal; if (l.market === 'g2') return pAtLeastNHL('goals', p.proj.goals, 2); if (l.market === 'first_goal') return p.p_first;
    const k = l.market === 'goals' ? 'goals' : l.market; if (p.proj[k] == null || L == null) return null;
    const ln = (p.lines || {})[k], pm = pOver(k, p.proj[k], L), pp = ln && ln.line === L ? blendP(k, pm, ln.p_book) : pm;
    return pp == null ? null : (l.side === 'U' ? 1 - pp : pp);
  }
  if (l.market === 'dd' || l.market === 'td3'){ const x = (D.long_shots || []).find(z => z.id === String(l.player) && z.game === g.id && z.key === l.market); return x ? x.p : null; }
  if (p.proj[l.market] == null || L == null) return null;
  const ln = (p.lines || {})[l.market], pm = pOver(l.market, p.proj[l.market], L), pp = ln && ln.line === L ? blendP(l.market, pm, ln.p_book) : pm;
  return pp == null ? null : (l.side === 'U' ? 1 - pp : pp);
}
const addLeg = (l, o) => {
  const g = gameOf(l.game);
  if (g){ l.mu = `${g.away} @ ${g.home}`; l.k = g.k; l.sub = `${l.mu} · ${whenDay(g.k)}`; }
  SB.addLeg(l, o);
};
function propLegFrom(row, side){
  const k = row.dataset.key, key = `${row.dataset.pid}:${k}`, st = PL[key] || {};
  const p = row.dataset.goalie ? (D.goalies || []).find(x => x.id === row.dataset.pid && x.game === row.dataset.g) : PIDX[row.dataset.g + ':' + row.dataset.pid];
  if (!p) return null;
  const ln = (p.lines || {})[k];
  const typed = st.line != null && st.line !== '' ? numOf(st.line) : null;
  const L = typed ?? (ln ? ln.line : (k === 'saves' ? Math.floor(p.saves) + 0.5 : Math.floor(propVal(p, k)) + 0.5));
  side = side || st.side || 'over';
  const O = parseOdds(st.odds) ?? (ln && L === ln.line ? (side === 'under' ? ln.u : ln.o) : -110);
  return {market: k, game: p.game, player: p.id, player_name: p.name, team: p.team, side: side === 'under' ? 'U' : 'O', line: L, odds: O};
}
const SLIP_SEL2 = '[data-pppick],[data-ppyes],[data-mpick],[data-hcpick],[data-lspick],[data-trleg],[data-cladd]';
document.addEventListener('click', e => {
  const t = e.target.closest(SLIP_SEL2); if (!t) return;
  e.stopPropagation();
  const d = t.dataset;
  if (d.pppick != null){ const row = t.closest('.pp'); const l = row && propLegFrom(row); if (l) addLeg(l); return; }
  if (d.ppyes){ const row = t.closest('.pp'), p = row && PIDX[row.dataset.g + ':' + row.dataset.pid]; if (!p) return;
    const pr = d.ppyes === 'atg' ? p.p_goal : d.ppyes === 'g2' ? pAtLeastNHL('goals', p.proj.goals, 2) : p.p_first;
    addLeg({market: d.ppyes, game: p.game, player: p.id, player_name: p.name, team: p.team, side: 'Y', odds: (p.yes || {})[d.ppyes] ?? oddsNum(pr), oddsFair: (p.yes || {})[d.ppyes] == null || undefined, p: pr}); return; }
  if (d.mpick){ const g = gameOf(d.mpick); if (!g || !g.model) return; const tm = g.model.pick_su; addLeg({market: 'ml', game: g.id, team: tm, odds: (tm === g.home ? (g.odds || {}).ml_h : (g.odds || {}).ml_a) ?? -110}); return; }
  if (d.hcpick != null){
    const x = D.high_chance[Number(d.hcpick)]; if (!x) return;
    const mine = parseOdds(MY_ODDS[hcKey(x)]);
    if (x.kind === 'ml') addLeg({market: 'ml', game: x.game, team: x.team, odds: mine ?? x.book ?? x.fair, oddsFair: mine == null && x.book == null || undefined});
    else addLeg({market: x.key, game: x.game, player: x.id, player_name: x.name, team: x.team, side: 'O', line: x.t - 0.5, odds: mine ?? x.book ?? x.fair, oddsFair: mine == null && x.book == null || undefined, p: x.p});
    return;
  }
  if (d.lspick != null){
    const x = D.long_shots[Number(d.lspick)]; if (!x) return;
    const mk = lsMarket(x), mine = parseOdds(MY_ODDS[lsKey(x)]);
    addLeg(Object.assign({game: x.game, player: x.id, player_name: x.name, team: x.team, odds: mine ?? x.book ?? x.fair, oddsFair: mine == null && x.book == null || undefined, p: x.p}, mk)); return;
  }
  if (d.trleg != null){
    const x = D.trends.player[Number(d.trleg)]; if (!x) return;
    const p = PIDX[x.game + ':' + x.id], ln = p && (p.lines || {})[x.key];
    if (NHL && x.key === 'goals'){ addLeg({market: 'atg', game: x.game, player: x.id, player_name: x.name, team: x.team, side: 'Y', odds: (p && (p.yes || {}).atg) ?? oddsNum(p ? p.p_goal : 0.2)}); return; }
    addLeg({market: x.key, game: x.game, player: x.id, player_name: x.name, team: x.team, side: x.dir === 'under' ? 'U' : 'O', line: x.line, odds: ln && ln.line === x.line ? (x.dir === 'under' ? ln.u : ln.o) : -110}); return;
  }
  if (d.cladd != null){
    if (!CH) return;
    if (CH.kind === 't'){
      const g = nextFor(); if (!g || CH.line == null) return toast('Type a line first.');
      const O = parseOdds(CH.odds), o = g.odds || {};
      if (CH.stat === 'margin' && CH.line === -0.5) addLeg({market: 'ml', game: g.id, team: CH.id, odds: O ?? (CH.id === g.home ? o.ml_h : o.ml_a) ?? -110});
      else if (CH.stat === 'margin') addLeg({market: 'spread', game: g.id, team: CH.id, line: CH.line, odds: O ?? (lineFor(g, CH.id) === CH.line ? (CH.id === g.home ? o.sp_h : o.sp_a) : null) ?? -110});
      else addLeg({market: 'total', game: g.id, side: CH.side === 'under' ? 'U' : 'O', line: CH.line, odds: O ?? (o.total === CH.line ? (CH.side === 'under' ? o.u : o.o) : null) ?? -110});
      return;
    }
    const n = nextFor(); if (!n || !n.g || CH.line == null) return toast('Type a line first.');
    const O = parseOdds(CH.odds);
    if (NHL && CH.stat === 'goals') addLeg({market: CH.line < 1 ? 'atg' : 'g2', game: n.g.id, player: CH.id, player_name: n.item.name, team: n.item.team, side: 'Y', odds: O ?? -110});
    else if (CH.stat === 'toi' || CH.stat === 'min' || CH.stat === 'shots' || CH.stat === 'hits' && !NHL) return toast('That stat isn\'t a bettable market here.');
    else { const ln = (n.item.lines || {})[CH.stat]; addLeg({market: CH.stat, game: n.g.id, player: CH.id, player_name: n.item.name, team: n.item.team, side: CH.side === 'under' ? 'U' : 'O', line: CH.line, odds: O ?? (ln && ln.line === CH.line ? (CH.side === 'under' ? ln.u : ln.o) : -110)}); }
    return;
  }
}, true);
function playersFor(gid){
  const out = (D.props || []).filter(p => p.game === gid).map(p => ({id: p.id, n: p.name, p: p.pos, t: p.team}));
  if (NHL) (D.goalies || []).filter(x => x.game === gid).forEach(x => out.push({id: x.id, n: x.name, p: 'G', t: x.team}));
  const g = gameOf(gid) || {};
  return out.sort((a, b) => (a.t === b.t ? 0 : a.t === g.away ? -1 : 1) || a.n.localeCompare(b.n));
}
SB.init({sport: SP, root: '../', grade: null, modelP,
  periodOf: gid => { const g = gameOf(gid); return g ? {key: g.day, label: dayLabel(g.day, {plain: true})} : null; },
  customGames: () => D.games.map(g => ({id: g.id, a: g.away, h: g.home, k: g.k, final: g.state === 'post', per: g.day, perLabel: dayLabel(g.day)})),
  players: playersFor, betsEl: '#v-picks', countEl: '#pick-count', otherHint: NHL ? 'e.g. McDavid 2+ assists' : 'e.g. Jokic 12+ assists'});

/* ======================================================================
   EVENTS, LIVE SCORES, FRESH DATA
   ====================================================================== */
document.addEventListener('click', e => {
  const t = e.target.closest('button, a'); if (!t) return;
  if (t.dataset.gsum){
    const id = t.dataset.gsum, art = $('#g-' + id), open = !GOPEN.has(id);
    open ? GOPEN.add(id) : GOPEN.delete(id); art.classList.toggle('open', open);
    t.setAttribute('aria-expanded', String(open)); const ch = $('.chev', t); if (ch) ch.textContent = open ? '▲' : '▼';
    return;
  }
  if (t.dataset.day){ DAY = t.dataset.day; store.set('day', DAY); store.set('daySet', dayKey(new Date().toISOString())); renderGames(); return; }
  if (t.dataset.gf){ GF = t.dataset.gf; store.set('gf', GF); renderGames(); return; }
  if (t.dataset.more){
    const id = t.dataset.more, det = $('#d-' + id), open = det.hidden;
    det.hidden = !open; t.setAttribute('aria-expanded', String(open)); t.lastElementChild.textContent = open ? '－' : '＋';
    if (open) det.innerHTML = detailHtml(gameOf(id));
    return;
  }
  if (t.dataset.dtab){ const g = gameOf(t.dataset.g); $('#d-' + g.id).innerHTML = detailHtml(g, t.dataset.dtab); SB.refresh(); return; }
  if (t.dataset.jump){ e.preventDefault(); const g = gameOf(t.dataset.jump); if (!g) return; DAY = g.day; GF = 'all'; GOPEN.add(g.id); if ($('#v-games').hidden) show('games'); renderGames();
    const el = $('#g-' + g.id); if (el){ el.scrollIntoView({block: 'start'}); const b = $('[data-more]', el); if (b && b.getAttribute('aria-expanded') === 'false') b.click(); } return; }
  if (t.dataset.goto){ e.preventDefault(); show(t.dataset.goto); return; }
  if (t.dataset.tsub){ TSUB = t.dataset.tsub; store.set('tsub', TSUB); renderTrends(); return; }
  if (t.dataset.lsf){ LS_F = t.dataset.lsf; store.set('lsf', LS_F); renderLS(); return; }
});
const ABBR = NHL ? {NJ: 'NJD', SJ: 'SJS', TB: 'TBL', LA: 'LAK', UTAH: 'UTA'} : {GSW: 'GS', NYK: 'NY', SAS: 'SA', NOP: 'NO', UTA: 'UTAH', WAS: 'WSH', PHO: 'PHX'};
let liveTimer = null;
async function liveScores(){
  if (!D.games.some(g => g.state !== 'post' && new Date(g.k).getTime() < Date.now() + 10 * 60000 && new Date(g.k).getTime() > Date.now() - 6 * 3600e3)) return;
  try {
    const ctl = new AbortController(); const tm = setTimeout(() => ctl.abort(), 7000);
    const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${M.espn}/scoreboard`, {signal: ctl.signal, cache: 'no-store'});
    clearTimeout(tm); if (!r.ok) return;
    const j = await r.json(); let changed = false, anyLive = false;
    (j.events || []).forEach(ev => {
      const comp = (ev.competitions || [])[0]; if (!comp) return;
      const cs = comp.competitors || [], h = cs.find(c => c.homeAway === 'home'), a = cs.find(c => c.homeAway === 'away'); if (!h || !a) return;
      const ab = c => { const x = (c.team || {}).abbreviation || ''; return ABBR[x] || x; };
      const g = D.games.find(x => (x.eid && x.eid === ev.id) || x.id === ev.id || (x.home === ab(h) && x.away === ab(a) && Math.abs(new Date(x.k) - new Date(ev.date)) < 12 * 3600e3)); if (!g) return;
      const st = ((comp.status || ev.status || {}).type) || {}, hs = parseInt(h.score, 10), as = parseInt(a.score, 10);
      if (st.state === 'in'){ anyLive = true; if (g.state !== 'in' || g.hs !== hs || g.as !== as){ Object.assign(g, {state: 'in', hs, as, detail: st.shortDetail || 'Live'}); changed = true; } }
      else if (st.state === 'post' && g.state !== 'post' && !isNaN(hs)){ Object.assign(g, {state: 'post', hs, as, detail: st.shortDetail || 'Final'}); changed = true; }
    });
    if (changed && !$('#v-games').hidden && !$$('.g-detail').some(d => !d.hidden)) renderGames();
    clearTimeout(liveTimer);
    if (anyLive) liveTimer = setTimeout(() => { if (!document.hidden) liveScores(); }, 60000);
  } catch(e){ /* live scores are a bonus */ }
}
/* injury statuses straight from ESPN between data refreshes */
let INJ_AT = 0;
const TEAMNAME = {}; Object.entries(T).forEach(([ab, x]) => { TEAMNAME[x.name] = ab; });
Object.assign(TEAMNAME, NHL ? {'Montreal Canadiens': 'MTL', 'Utah Hockey Club': 'UTA', 'Utah Mammoth': 'UTA'} : {'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC'});
const LVL = s => { s = String(s || '').toLowerCase(); return s.includes('out') || s.includes('injured reserve') || s.includes('suspen') ? 'out' : s.includes('doubt') ? 'doubt' : s.includes('prob') ? 'likely' : 'gtd'; };
async function liveInjuries(){
  if (Date.now() - INJ_AT < 4 * 60000) return; INJ_AT = Date.now();
  try {
    const ctl = new AbortController(); const tm = setTimeout(() => ctl.abort(), 12000);
    const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${M.espn}/injuries`, {signal: ctl.signal, cache: 'no-store'});
    clearTimeout(tm); if (!r.ok) return;
    const j = await r.json(); let changed = false, n = 0;
    (j.injuries || []).forEach(team => { const t = TEAMNAME[team.displayName]; if (!t) return;
      (team.injuries || []).forEach(it => { n++;
        const ath = it.athlete || {}, name = ath.displayName || ath.fullName; if (!name) return;
        const lvl = LVL(it.status), cur = (D.injuries[t] || []).find(x => injNorm(x.name) === injNorm(name));
        if (cur){ if (cur.level !== lvl || cur.status !== it.status){ cur.level = lvl; cur.status = it.status; changed = true; } }
        else { const p = (D.props || []).find(x => x.team === t && injNorm(x.name) === injNorm(name));
          (D.injuries[t] = D.injuries[t] || []).push({name, pos: (ath.position || {}).abbreviation, status: it.status, level: lvl, injury: ((it.details || {}).type) || '', comment: it.shortComment || '', key: !!(p && (p.min || p.toi || 0) >= (NHL ? 16 : 20)), min: p ? p.min : null, toi: p ? p.toi : null}); changed = true; } }); });
    if (n < 20) return;
    if (changed){ buildInjIdx(); if (!$('#v-games').hidden && !$$('.g-detail').some(d => !d.hidden)) renderGames(); }
  } catch(e){}
}
async function checkForNewData(){
  if (Date.now() - LOADED_AT < 10 * 60000) return;
  try {
    const r = await fetch(DATA_URL + '?t=' + Date.now(), {cache: 'no-store'}); if (!r.ok) return;
    const j = await r.json(); LOADED_AT = Date.now();
    if (j.meta.asof !== M.asof && !$('#fresh')){
      const b = document.createElement('div'); b.id = 'fresh'; b.className = 'toast'; b.setAttribute('role', 'status');
      b.innerHTML = 'Newer numbers are available. <button class="btn tiny stripe" style="margin-left:8px" id="fresh-go">Reload</button>';
      document.body.appendChild(b); $('#fresh-go').addEventListener('click', () => location.reload());
    }
  } catch(e){}
}
document.addEventListener('visibilitychange', () => { if (!document.hidden){ checkForNewData(); liveScores(); liveInjuries(); } });
setInterval(() => { if (!document.hidden){ liveInjuries(); checkForNewData(); } }, 60000);

/* ---------------- boot ---------------- */
renderGames();
const h0 = location.hash.replace('#', '');
let start = h0 || store.get('tab', 'games');
if (start.startsWith('g-')){ const g = gameOf(decodeURIComponent(start.slice(2))); if (g){ DAY = g.day; GOPEN.add(g.id); renderGames(); setTimeout(() => { const el = $('#g-' + g.id); if (el) el.scrollIntoView({block: 'start'}); }, 60); } start = 'games'; }
if (start === 'bets') start = 'picks';
if (start !== 'games' && $('#v-' + start)) show(start);
liveScores(); liveInjuries();
})();
