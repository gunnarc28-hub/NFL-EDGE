/* Sports Edge: quarters, halves and periods, and props for the 1st quarter and 1st half.
   The builds write each part of a game as a small model (pipeline/parts.py); this file prices any line against it with
   the same rules, draws the Quarters / Periods tab of a game card, and lists part props. Every button carries the leg it
   adds as JSON in data-pleg; the page passes it to the slip. Loaded after core.js and bets.js. */
(function(){
'use strict';
const {esc, fmtOdds, fmtLine, pct, ncdf, oddsNum, impProb, evMsg} = SE;
const LABEL = {q1: '1st quarter', q2: '2nd quarter', q3: '3rd quarter', q4: '4th quarter', h1: '1st half', h2: '2nd half', p1: '1st period', p2: '2nd period', p3: '3rd period'};
const SHORT = {q1: 'Q1', q2: 'Q2', q3: 'Q3', q4: 'Q4', h1: '1st half', h2: '2nd half', p1: '1st', p2: '2nd', p3: '3rd'};
const sgm = x => 1 / (1 + Math.exp(-x));

/* ---------- chances ---------- */
/* one side of a part line: {p: wins, push}. kind 'spread' (side 'h'/'a', line from that team's view), 'total' (side 'O'/'U'),
   'ml' (side 'h'/'a'/'draw') */
function prob(m, kind, side, line){
  if (!m) return null;
  line = line == null ? null : Number(line);
  if (m.k === 'p'){
    const ph = m.ph, pt = m.pt, pa = 1 - ph - pt;
    if (kind === 'ml') return {p: side === 'h' ? ph : side === 'a' ? pa : pt, push: 0};
    if (kind === 'total'){ const o = (m.po || {})[String(line)] ?? (m.po || {})[line.toFixed(1)]; return o == null ? null : {p: side === 'U' ? 1 - o : o, push: 0}; }
    const win = side === 'h' ? ph : pa, by2 = side === 'h' ? m.pb : m.pa2, oppBy2 = side === 'h' ? m.pa2 : m.pb;
    if (line === -0.5) return {p: win, push: 0}; if (line === 0.5) return {p: win + pt, push: 0};
    if (line === -1.5) return {p: by2, push: 0}; if (line === 1.5) return {p: 1 - oppBy2, push: 0};
    return null;
  }
  if (m.k === 'n'){
    const gt = (x, mu, sd) => Number.isInteger(x) ? 1 - ncdf((x + 0.5 - mu) / sd) : 1 - ncdf((x - mu) / sd);
    const eq = (x, mu, sd) => Number.isInteger(x) ? ncdf((x + 0.5 - mu) / sd) - ncdf((x - 0.5 - mu) / sd) : 0;
    if (kind === 'total'){ const o = gt(line, m.t, m.st), pu = eq(line, m.t, m.st); return {p: side === 'U' ? 1 - o - pu : o, push: pu}; }
    const mu = side === 'h' ? m.m : -m.m;
    if (kind === 'ml') return {p: gt(0, mu, m.sm), push: eq(0, mu, m.sm)};
    return {p: gt(-line, mu, m.sm), push: eq(-line, mu, m.sm)};
  }
  // real score shapes, in 1/10,000ths
  let w = 0, pu = 0;
  if (kind === 'total'){
    let o = 0; (m.tp || []).forEach((v, i) => { const t = m.t0 + i; if (t > line) o += v; if (t === line) pu += v; });
    o /= 1e4; pu /= 1e4; return {p: side === 'U' ? 1 - o - pu : o, push: pu};
  }
  const sg = side === 'h' ? 1 : -1, x = kind === 'ml' ? 0 : -line;
  (m.mp || []).forEach((v, i) => { const d = sg * (m.m0 + i); if (d > x) w += v; if (d === x) pu += v; });
  return {p: w / 1e4, push: pu / 1e4};
}
/* the chance that matters for a price: when a push refunds the stake, wins among the bets that don't push */
const effP = r => r == null ? null : (r.push > 0 ? r.p / Math.max(1e-9, 1 - r.push) : r.p);
const fairOf = r => { const p = effP(r); return p == null || p <= 0 || p >= 1 ? null : oddsNum(p); };

/* player props for a part: P(at least t). NBA: one logistic curve per threshold in log(mean) (never more likely to reach t than
   a lower number); NFL: the real distribution of results among players with similar projections (bins, like the full game),
   and past the top bin its curve stretched with the projection (research/16_player_periods.py, chance()). */
function atLeastNBA(curves, mean, t){
  if (!curves || mean == null || t <= 0) return t <= 0 ? 1 : null;
  const lm = Math.log(Math.max(mean, 0.02)); let p = 1;
  for (let u = 1; u <= t; u++){ const c = curves[String(u)]; if (!c) break; p = Math.min(p, sgm(c[0] + c[1] * lm + c[2] * lm * lm)); }
  return p;
}
function survNFL(dist, proj, t){
  if (!dist || proj == null) return null;
  const g = dist.grid, cs = dist.bins.map(b => b.center), last = cs.length - 1;
  const surv = (b, t) => { if (t <= g[0]) return b.surv[0]; if (t >= g[g.length - 1]) return b.surv[b.surv.length - 1];
    let j = 0; while (j < g.length - 1 && g[j + 1] <= t) j++; const w = (t - g[j]) / (g[j + 1] - g[j]); return b.surv[j] * (1 - w) + b.surv[j + 1] * w; };
  if (proj <= cs[0]) return surv(dist.bins[0], t);
  if (proj >= cs[last]) return surv(dist.bins[last], t * cs[last] / proj);
  let k = 0; while (k < last && cs[k + 1] <= proj) k++;
  const w = (proj - cs[k]) / (cs[k + 1] - cs[k]); return surv(dist.bins[k], t) * (1 - w) + surv(dist.bins[k + 1], t) * w;
}

/* ---------- a priced button ---------- */
function legAttr(l){ return esc(JSON.stringify(l)); }
function btn(label, r, odds, leg, opts){
  opts = opts || {};
  const p = effP(r), fair = fairOf(r), O = odds != null && odds !== '' ? Number(odds) : null;
  const push = !!r && r.push >= 0.005;          // shown as its own line: the win chance, then the chance it's a push (the price allows for that)
  const ev = p != null && O != null ? evMsg(p, fair, String(O)) : null;
  const cls = ev ? (ev.c === 'pos' ? ' pos' : ev.c === 'thin' ? ' thin' : '') : '';
  leg = Object.assign({}, leg, {odds: O ?? fair, oddsFair: O == null || undefined, p: p ?? undefined});
  return `<button type="button" class="pb${cls}" data-pleg="${legAttr(leg)}" aria-label="${esc(label)}${p != null ? `, model ${pct(push ? r.p : p)}` : ''}${push ? `, push ${pct(r.push)}` : ''}${O != null ? `, book ${fmtOdds(O)}` : ''}">
    <span class="pb-l">${esc(label)}</span><span class="pb-p">${p != null ? pct(push ? r.p : p) : '–'}</span>
    <span class="pb-o num">${O != null ? fmtOdds(O) : `<span class="pb-f">fair </span>${fair != null ? fmtOdds(fair) : '–'}`}</span>${push ? `<span class="pb-u">push ${pct(r.push)}</span>` : ''}</button>`;
}

/* ---------- the Quarters / Periods tab of a game ---------- */
/* g: the game with g.parts (and g.f10 for the NHL); o.chip(team) draws a team chip */
function tabHtml(g, o){
  const P = g.parts; if (!P) return '<div class="small">Quarter and half lines show up for games that haven\'t started.</div>';
  const nhl = o.sport === 'nhl', order = nhl ? ['p1', 'p2', 'p3'] : ['q1', 'q2', 'q3', 'q4', 'h1', 'h2'];
  const H = g.home, A = g.away;
  const rows = order.filter(k => P[k]).map(k => {
    const m = P[k], b = m.book || {};
    const sp = b.sp && b.sp[0] != null ? b.sp : [m.fl, null, -m.fl, null];          // the book's spread, or the model's own number
    const tot = b.tot && b.tot[0] != null ? b.tot : [m.ft, null, null];
    const ml = b.ml || [null, null, null];
    const base = {game: g.id};
    const sprRow = `<div class="pt-r"><span class="pt-k">Spread</span>
      ${btn(`${A} ${fmtLine(sp[2])}`, prob(m, 'spread', 'a', sp[2]), sp[3], Object.assign({market: `${k}_spread`, team: A, line: sp[2]}, base))}
      ${btn(`${H} ${fmtLine(sp[0])}`, prob(m, 'spread', 'h', sp[0]), sp[1], Object.assign({market: `${k}_spread`, team: H, line: sp[0]}, base))}</div>`;
    const totRow = `<div class="pt-r"><span class="pt-k">Total</span>
      ${btn(`Over ${tot[0]}`, prob(m, 'total', 'O', tot[0]), tot[1], Object.assign({market: `${k}_total`, side: 'O', line: tot[0]}, base))}
      ${btn(`Under ${tot[0]}`, prob(m, 'total', 'U', tot[0]), tot[2], Object.assign({market: `${k}_total`, side: 'U', line: tot[0]}, base))}</div>`;
    const mlRow = `<div class="pt-r${nhl ? ' three' : ''}"><span class="pt-k">${nhl ? '3-way' : 'Winner'}</span>
      ${btn(`${A}`, prob(m, 'ml', 'a'), ml[1], Object.assign({market: `${k}_ml`, team: A}, base))}
      ${nhl ? btn('Tie', prob(m, 'ml', 'draw'), ml[2], Object.assign({market: `${k}_ml`, side: 'D', team: ''}, base)) : ''}
      ${btn(`${H}`, prob(m, 'ml', 'h'), ml[0], Object.assign({market: `${k}_ml`, team: H}, base))}</div>`;
    const lead = nhl ? `${pct(m.ph)} ${H} · ${pct(m.pt)} tied · ${pct(1 - m.ph - m.pt)} ${A}` :
      `Model: ${m.fl <= 0 ? H : A} ${fmtLine(-Math.abs(m.fl))} · total ${m.ft} · ${H} wins ${pct(m.ph)}${m.pt >= 0.01 ? `, ties ${pct(m.pt)}` : ''}`;
    return `<div class="pt"><div class="pt-h"><b>${esc(LABEL[k][0].toUpperCase() + LABEL[k].slice(1))}</b><span class="small">${esc(lead)}</span></div>${sprRow}${totRow}${mlRow}</div>`;
  }).join('');
  const f10 = nhl && g.f10 != null ? `<div class="pt"><div class="pt-h"><b>Goal in the first 10 minutes</b><span class="small">Model ${pct(g.f10)} from the teams' expected goals</span></div>
    <div class="pt-r"><span class="pt-k">Yes / no</span>${btn('Yes', {p: g.f10, push: 0}, null, {game: g.id, market: 'f10', side: 'Y'})}${btn('No', {p: 1 - g.f10, push: 0}, null, {game: g.id, market: 'f10', side: 'N'})}</div></div>` : '';
  const anyBook = order.some(k => P[k] && P[k].book);
  const note = nhl ? `Each team's expected goals split by period (the 1st period has the fewest goals), with the chance of a tie and of each total checked on 2024-25 and 2025-26.${anyBook ? ' Prices are DraftKings\' through ESPN.' : ''}`
    : `Each part of the game priced from the model's full-game margin and total.${o.sport === 'nfl' ? ' Football scores come in 3s and 7s, so these use real score shapes from teams with similar outlooks.' : ''} The 2nd half includes overtime; the 4th quarter doesn't. A tied quarter or half pushes the winner bet.${anyBook ? ' Book lines are DraftKings\' through ESPN; with no price posted, the button shows the fair price.' : ' No book lines yet: the buttons use the model\'s own numbers at the fair price.'}`;
  return `<div class="parts">${f10}${rows}<p class="small" style="margin:6px 0 0">${esc(note)} Green means the book pays more than the model's fair price.</p></div>`;
}

/* ---------- NBA first basket ---------- */
function firstBasketHtml(g, o){
  const F = g.fb; if (!F || !F.pl || !F.pl.length) return '<div class="small">First-basket chances show up for today\'s and tomorrow\'s games.</div>';
  const H = g.home, A = g.away, nm = id => { const r = F.pl.find(x => x[0] === id); return r ? r[1].split(' ').slice(-1)[0] : null; };
  const ft = F.ft || {};
  const team = `<div class="pt"><div class="pt-h"><b>First team to score</b><span class="small">${esc(H)} wins the tip ${pct(F.tip)}${F.jh && nm(F.jh) ? ` (${esc(nm(F.jh))} jumping)` : ''}; the team that wins the tip scores first about 65% of the time. Free throws count here.</span></div>
    <div class="pt-r"><span class="pt-k">Team</span>${btn(A, {p: 1 - F.pts, push: 0}, ft[A], {game: g.id, market: 'first_team', team: A})}${btn(H, {p: F.pts, push: 0}, ft[H], {game: g.id, market: 'first_team', team: H})}</div></div>`;
  const rows = F.pl.slice(0, 10).map(r => {
    const [id, name, tm, p, bk] = r, fair = oddsNum(p), ev = bk != null ? evMsg(p, fair, String(bk)) : null;
    return `<div class="fb-r"><span class="fb-n">${o.chip(tm, 1)} ${esc(name)}</span><span class="num">${pct(p, 1)}</span><span class="small num">fair ${fmtOdds(fair)}</span>
      <span class="small num ${ev ? ev.c : ''}">${bk != null ? 'book ' + fmtOdds(bk) : '–'}</span>
      <button class="btn tiny slipb" data-pleg="${legAttr({game: g.id, market: 'first_basket', player: id, player_name: name, team: tm, side: 'Y', odds: bk ?? fair, oddsFair: bk == null || undefined, p})}">+ Slip</button></div>`;
  }).join('');
  return `<div class="parts">${team}<div class="pt"><div class="pt-h"><b>Player to make the first basket</b><span class="small">Free throws don't count (DraftKings' rule; FanDuel counts them)</span></div><div class="fb-list">${rows}</div></div>
    <p class="small" style="margin:6px 0 0">The team's chance times the player's share: starters who take the most shots. Checked on 2024-25 and 2025-26, players rated 8-14% made it about as often as rated. Books hold a lot on this market, so the fair price is usually well short of theirs.</p></div>`;
}

window.SE.parts = {LABEL, SHORT, prob, effP, fairOf, atLeastNBA, survNFL, btn, legAttr, tabHtml, firstBasketHtml};
})();
