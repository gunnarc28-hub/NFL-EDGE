/* Sports Edge: one bet slip and one list of bets across the NFL, NBA and NHL pages.
   Legs from any sport go in the same slip, so a parlay can mix sports. Every leg carries its sport and a description,
   so a page can show (and grade) legs from the other sports by loading that sport's small grade.json.

   A page starts it with SB.init(adapter):
     sport        'nfl' | 'nba' | 'nhl' (null on the home page)
     root         path back to the site root from this page ('' on the home page, '../' on a sport page)
     grade        this sport's grade data {games, players, pkey?}; other sports load theirs on demand
     modelP(l)    the model's chance for a leg of this sport, or null
     periodOf(gid) {key, label} for a game ('Week 7', or a day)
     customGames() games for the custom-leg form: [{id, a, h, k, final, per, perLabel}]
     players(gid) [{id, n, p, t}] for the custom-leg form
     extraBetsHtml() optional block under My bets (the model's own record)
     betsEl, countEl  where My bets and its open count render
     onChange()   optional, after the slip changes */
(function(){
'use strict';
const {$, $$, esc, sign, fmtLine, fmtOdds, pct, numOf, parseOdds, dec, amOf, impProb, oddsNum, evOf, evMsg, uid, unitsTxt, kick, toast, stepWrap, SPORTS} = SE;
const LS = SE.mkStore('sportsedge.');

/* ---------- markets: labels, and how each grades from the box-score arrays each build writes ----------
   s: sum of these stat columns; y: a yes bet that needs at least this many; dd: count the columns at 10 or more; first: first scorer
   NFL columns: cmp, att, pass_yds, pass_td, int, carries, rush_yds, rush_td, rec, targets, rec_yds, rec_td
   NBA columns: min, pts, reb, ast, fg3m, stl, blk, tov
   NHL columns: goals, assists, points, sog, hits, blocks, toi, saves, goals_against, shots_against */
const GAME_MK = {spread: {label: 'Spread', cat: 'Game'}, ml: {label: 'Moneyline', cat: 'Game'}, total: {label: 'Game total', cat: 'Game'}, team_total: {label: 'Team total', cat: 'Game'}};
const MK = {
  nfl: Object.assign({}, GAME_MK, {
    pass_yds: {label: 'Passing yards', cat: 'Player', s: [2]}, pass_td: {label: 'Passing TDs', cat: 'Player', s: [3]}, completions: {label: 'Completions', cat: 'Player', s: [0]},
    pass_att: {label: 'Pass attempts', cat: 'Player', s: [1]}, ints: {label: 'Interceptions', cat: 'Player', s: [4]}, rush_yds: {label: 'Rushing yards', cat: 'Player', s: [6]},
    carries: {label: 'Rush attempts', cat: 'Player', s: [5]}, rec_yds: {label: 'Receiving yards', cat: 'Player', s: [10]}, receptions: {label: 'Receptions', cat: 'Player', s: [8]},
    targets: {label: 'Targets', cat: 'Player', s: [9]}, rush_rec: {label: 'Rush + rec yards', cat: 'Player', s: [6, 10]},
    any_td: {label: 'Anytime TD', cat: 'Player', s: [7, 11], y: 1, yes: 'anytime TD'}, first_td: {label: 'First TD scorer', cat: 'Player', first: 1, yes: 'first TD'},
    td2: {label: '2+ TDs', cat: 'Player', s: [7, 11], y: 2, yes: '2+ TDs'}, other: {label: 'Other', cat: 'Other'}}),
  nba: Object.assign({}, GAME_MK, {
    pts: {label: 'Points', cat: 'Player', s: [1]}, reb: {label: 'Rebounds', cat: 'Player', s: [2]}, ast: {label: 'Assists', cat: 'Player', s: [3]},
    fg3m: {label: '3-pointers made', cat: 'Player', s: [4]}, pra: {label: 'Pts + reb + ast', cat: 'Player', s: [1, 2, 3]}, pr: {label: 'Pts + reb', cat: 'Player', s: [1, 2]},
    pa: {label: 'Pts + ast', cat: 'Player', s: [1, 3]}, ra: {label: 'Reb + ast', cat: 'Player', s: [2, 3]}, stl: {label: 'Steals', cat: 'Player', s: [5]},
    blk: {label: 'Blocks', cat: 'Player', s: [6]}, sb: {label: 'Steals + blocks', cat: 'Player', s: [5, 6]}, tov: {label: 'Turnovers', cat: 'Player', s: [7]},
    dd: {label: 'Double-double', cat: 'Player', dd: [1, 2, 3, 5, 6], y: 2, yes: 'double-double'}, td3: {label: 'Triple-double', cat: 'Player', dd: [1, 2, 3, 5, 6], y: 3, yes: 'triple-double'},
    other: {label: 'Other', cat: 'Other'}}),
  nhl: Object.assign({}, GAME_MK, {spread: {label: 'Puck line', cat: 'Game'},
    atg: {label: 'Anytime goal', cat: 'Player', s: [0], y: 1, yes: 'to score'}, g2: {label: '2+ goals', cat: 'Player', s: [0], y: 2, yes: '2+ goals'},
    first_goal: {label: 'First goal scorer', cat: 'Player', first: 1, yes: 'first goal'},
    points: {label: 'Points', cat: 'Player', s: [2]}, goals: {label: 'Goals', cat: 'Player', s: [0]}, assists: {label: 'Assists', cat: 'Player', s: [1]},
    sog: {label: 'Shots on goal', cat: 'Player', s: [3]}, hits: {label: 'Hits', cat: 'Player', s: [4]}, blocks: {label: 'Blocked shots', cat: 'Player', s: [5]},
    saves: {label: 'Goalie saves', cat: 'Player', s: [7]}, ga: {label: 'Goals against', cat: 'Player', s: [8]},
    other: {label: 'Other', cat: 'Other'}})
};
const TEASERS = {nfl: {pts: 6, prices: {2: -120, 3: 160, 4: 260, 5: 400, 6: 600}}};
const VOID_DNP = {nba: true, nhl: true};       // the box score lists everyone who played, so a missing line means he sat (books void those)
const RWORD = {W: 'Won', L: 'Lost', P: 'Push', V: 'Void', C: 'Check'};
const TYPE_LABEL = {single: 'Single', parlay: 'Parlay', teaser: 'Teaser'};
const SL = s => (SPORTS[s] || {}).label || String(s || '').toUpperCase();
const mkOf = l => (MK[l.sport] || MK.nfl)[l.market] || {};
const noLine = l => { const m = mkOf(l); return l.market === 'ml' || l.market === 'other' || m.y != null || !!m.first; };
const isOU = l => l.market === 'total' || l.market === 'team_total' || (mkOf(l).cat === 'Player' && !noLine(l));

let A = {sport: null, root: '', modelP: () => null};
const G = {}, GLOAD = {};

/* ---------- grade data for every sport in the slip or the bets ---------- */
function needGrade(sport){
  if (!sport || G[sport] || GLOAD[sport] || !SPORTS[sport]) return;
  GLOAD[sport] = fetch(`${A.root}${SPORTS[sport].path}data/grade.json?v=${Math.floor(Date.now() / 600000)}`, {cache: 'no-cache'})
    .then(r => r.ok ? r.json() : null).then(j => { if (j && j.games){ G[sport] = j; regrade(); } })
    .catch(() => {});
}
function regrade(){ refreshSlipUI(); if (A.betsEl && $(A.betsEl)) renderBets(); if (A.onGrade) A.onGrade(); }
const gameG = l => { const S = G[l.sport]; return S && S.games ? S.games[l.game] : null; };
function plName(l){ const S = G[l.sport]; const p = S && S.players && S.players[l.player]; return p ? p.n : null; }

/* ---------- words for a leg ---------- */
function legLabel(l){
  const m = mkOf(l), nm = l.player_name || plName(l) || 'Player', ou = l.side === 'U' ? 'under' : 'over';
  if (l.market === 'spread') return `${l.team} ${fmtLine(Number(l.line))}`;
  if (l.market === 'ml') return `${l.team} to win`;
  if (l.market === 'total') return `${l.side === 'U' ? 'Under' : 'Over'} ${l.line}`;
  if (l.market === 'team_total') return `${l.team} team total ${ou} ${l.line}`;
  if (m.cat === 'Player'){
    if (m.yes) return `${nm} ${m.yes}`;
    return `${nm} ${ou} ${l.line} ${(m.label || '').toLowerCase()}`;
  }
  if (l.market === 'other') return l.label || 'Bet';
  return l.desc || l.label || m.label || 'Bet';
}
const marketLabel = l => mkOf(l).label || l.market;
function legWhen(g){ return kick(g.k, {weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: undefined}); }
function legSub(l){
  const g = gameG(l), T = TEASERS[l.sport];
  const tease = l.tease ? ` · teased ${T ? T.pts : 6} pts from ${l.market === 'total' ? (l.side === 'U' ? l.line - l.tease : l.line + l.tease) : fmtLine(l.from)}` : '';
  if (!g) return (l.sub || l.mu || '') + tease;
  const when = g.hs != null ? `final ${g.as}–${g.hs}` : legWhen(g);
  return `${g.a} @ ${g.h} · ${when}${tease}`;
}
function legStart(l){ const g = gameG(l); return g && g.k ? g.k : l.k || null; }
function legStarted(l){ const g = gameG(l); if (g && g.hs != null) return true; const k = legStart(l); return !!k && Date.now() > new Date(k).getTime(); }
function legFinal(l){ const g = gameG(l); return !!g && g.hs != null; }
/* what a leg needs to describe itself on a page that doesn't have its sport's data */
function decorate(l){
  const g = gameG(l);
  l.desc = legLabel(l);
  if (g){ l.mu = `${g.a} @ ${g.h}`; l.k = g.k; l.sub = `${g.a} @ ${g.h} · ${legWhen(g)}`; }
  if (A.periodOf && l.sport === A.sport){ const p = A.periodOf(l.game); if (p){ l.per = p.label; if (l.sport === 'nfl' && p.key != null) l.week = p.key; } }
  return l;
}

/* ---------- grading ---------- */
function boxIn(S, g){ return Object.values(S.players).some(x => (x.t === g.h || x.t === g.a) && x.w && x.w[g.wk]); }
function statLine(S, l, g){ const p = S.players && S.players[l.player]; if (!p) return null; return S.pkey === 'wk' ? (p.w || {})[g.wk] : (p.g || {})[l.game]; }
function gradeLeg(l){
  if (l.manual) return {r: l.manual};
  const S = G[l.sport], g = S && S.games ? S.games[l.game] : null;
  if (!g || g.hs == null) return l.res ? {r: l.res, actual: l.act, stored: true} : {r: null};
  const margin = l.team === g.h ? g.hs - g.as : g.as - g.hs;
  const ou = val => { const d = val - Number(l.line); return {r: d === 0 ? 'P' : ((d > 0) === (l.side !== 'U') ? 'W' : 'L'), actual: val}; };
  if (l.market === 'spread'){ const v = margin + Number(l.line); return {r: v > 0 ? 'W' : v < 0 ? 'L' : 'P', actual: margin}; }
  if (l.market === 'ml') return {r: margin > 0 ? 'W' : margin < 0 ? 'L' : 'P', actual: margin};
  if (l.market === 'total') return ou(g.hs + g.as);
  if (l.market === 'team_total') return ou(l.team === g.h ? g.hs : g.as);
  const m = mkOf(l); if (m.cat !== 'Player') return {r: l.res || null};
  if (m.first){
    if (g.f === undefined) return {r: null};
    if (!g.f) return {r: 'L', actual: 'no scorer'};
    return {r: g.f === l.player ? 'W' : 'L', actual: 'first by ' + (g.f === l.player ? (l.player_name || 'him') : (g.fn || 'another player'))};
  }
  const w = statLine(S, l, g);
  if (!w){
    if (VOID_DNP[l.sport]) return g.b ? {r: 'V', actual: "didn't play"} : {r: null};
    return {r: S.pkey === 'wk' && boxIn(S, g) ? 'C' : null};
  }
  let val;
  if (m.dd) val = m.dd.filter(i => (w[i] || 0) >= 10).length;
  else val = (m.s || []).reduce((a, i) => a + (w[i] || 0), 0);
  if (m.y != null) return {r: val >= m.y ? 'W' : 'L', actual: m.dd ? `${val} categories in double figures` : val};
  return ou(val);
}
const settled = r => r === 'W' || r === 'L' || r === 'P' || r === 'V';
function gradeBet(b){
  const legs = b.legs.map(l => Object.assign({}, gradeLeg(l), {leg: l}));
  if (b.manual) return {r: b.manual, legs};
  const rs = legs.map(x => x.r);
  if (rs.some(r => r === 'L')) return {r: 'L', legs};
  if (rs.some(r => !settled(r))) return {r: null, legs, check: rs.some(r => r === 'C')};
  const won = rs.filter(r => r === 'W').length;
  if (!won) return {r: 'P', legs, voided: rs.every(r => r === 'V')};
  if (b.type === 'teaser' && won < 2) return {r: 'P', legs};
  return {r: 'W', legs};
}
function betProfit(b, gr){
  const st = Number(b.stake) || 1, r = gr.r;
  if (r === 'L') return -st;
  if (r !== 'W') return 0;
  const rs = gr.legs.map(x => x.r);
  if (b.manual || b.type === 'single' || rs.every(x => x === 'W')) return st * (dec(b.odds) - 1);
  const won = b.legs.filter((l, i) => rs[i] === 'W');
  if (b.type === 'teaser'){ const T = TEASERS[(b.legs[0] || {}).sport] || TEASERS.nfl; return won.length < 2 ? 0 : st * (dec(T.prices[won.length] || b.odds) - 1); }
  const all = b.legs.reduce((a, l) => a * dec(l.odds || -110), 1), w = won.reduce((a, l) => a * dec(l.odds || -110), 1);
  return st * (w * (dec(b.odds) / all) - 1);                 // pushed and voided legs drop out; the book's price scales the rest
}
const toWin = b => (Number(b.stake) || 1) * (dec(b.odds) - 1);
/* closing line value: your number against the last line before the game started */
function clvLeg(l){
  const g = gameG(l); if (!g) return null;
  const started = g.hs != null || (g.k && Date.now() > new Date(g.k).getTime());
  let out = null;
  if (l.market === 'spread' && l.sport !== 'nhl' && g.sp != null && l.line != null && l.line !== '' && !l.tease){ const close = l.team === g.h ? -g.sp : g.sp; out = {v: Number(l.line) - close, txt: fmtLine(close), unit: 'pts'}; }
  else if (l.market === 'total' && g.tl != null && l.line != null && l.line !== '' && !l.tease){ out = {v: l.side === 'U' ? Number(l.line) - g.tl : g.tl - Number(l.line), txt: String(g.tl), unit: 'pts'}; }
  else if (l.market === 'ml'){ const cl = l.team === g.h ? g.mlh : g.mla; const o = parseOdds(l.odds); if (cl != null && o != null) out = {v: (impProb(cl) - impProb(o)) * 100, txt: fmtOdds(cl), unit: '%'}; }
  if (out) out.closed = started;
  return out;
}

/* ---------- the slip ---------- */
let SLIP = {legs: [], mode: 'single', stake: 1, book: '', modeSet: false};
const LEGREG = {};
const slipKey = l => [l.sport, l.market, l.game, l.player || l.team || ''].join(':');
const sameLeg = (a, b) => a.key === b.key && String(a.side || '') === String(b.side || '') && String(a.line ?? '') === String(b.line ?? '') && !!a.tease === !!b.tease;
function saveSlip(){ LS.set('slip', SLIP); }
function loadSlip(){
  let s = LS.get('slip', null), moved = false;
  if (s == null){                                                        // first visit since the NFL-only version: carry its slip over
    try { const old = JSON.parse(LS.raw('nfledge.slip') || 'null'); if (old && old.legs){ s = old; moved = true; } } catch(e){}
  }
  SLIP = Object.assign({legs: [], mode: 'single', stake: 1, book: '', modeSet: false}, s || {});
  const stale = Date.now() - 2 * 864e5;
  SLIP.legs = (SLIP.legs || []).filter(l => l && l.market && l.game).map(l => { if (!l.sport) l.sport = 'nfl'; l.key = slipKey(l); return l; })
    .filter(l => !l.k || new Date(l.k).getTime() > stale);
  if (SLIP.legs.length < 2) SLIP.mode = 'single';
  if (moved || s == null) saveSlip();
}
function legP(l){ return l.sport === A.sport && A.modelP ? A.modelP(l) : (l.p ?? null); }
function addLeg(l, opts){
  opts = opts || {};
  l = Object.assign({}, l); l.sport = l.sport || A.sport; l.key = slipKey(l); l.id = l.id || uid('leg');
  if (l.line != null && l.line !== '') l.line = Number(l.line);
  if (l.p == null && l.sport === A.sport && A.modelP) l.p = A.modelP(l);
  decorate(l);
  const i = SLIP.legs.findIndex(x => x.key === l.key);
  if (i >= 0 && sameLeg(SLIP.legs[i], l) && opts.toggle){ SLIP.legs.splice(i, 1); toast('Removed from slip'); }
  else if (i >= 0){ SLIP.legs[i] = Object.assign({}, SLIP.legs[i], l, {id: SLIP.legs[i].id}); toast(`Updated · ${legLabel(l)}`); }
  else {
    SLIP.legs.push(l); toast(`Added · ${legLabel(l)}`);
    if (l.tease) SLIP.mode = 'teaser';
    else if (SLIP.legs.length === 2 && !SLIP.modeSet) SLIP.mode = 'parlay';
  }
  if (SLIP.mode === 'teaser' && !teaserOk()) SLIP.mode = 'parlay';
  if (SLIP.legs.length < 2 && SLIP.mode !== 'single') SLIP.mode = 'single';
  saveSlip(); refreshSlipUI();
  if (opts.open) openSlip();
}
function removeLeg(id){ SLIP.legs = SLIP.legs.filter(l => l.id !== id); if (SLIP.legs.length < 2) SLIP.mode = 'single'; else if (SLIP.mode === 'teaser' && !teaserOk()) SLIP.mode = 'parlay'; saveSlip(); refreshSlipUI(); }
function clearSlip(){ SLIP.legs = []; SLIP.mode = 'single'; SLIP.book = ''; SLIP.modeSet = false; saveSlip(); refreshSlipUI(); }
function teaserOf(){ const s = SLIP.legs.length ? SLIP.legs[0].sport : null; return s && SLIP.legs.every(l => l.sport === s) ? TEASERS[s] || null : null; }
const teaserOk = () => { const T = teaserOf(); return !!T && SLIP.legs.length >= 2 && SLIP.legs.length <= 6 && SLIP.legs.every(l => l.market === 'spread' || l.market === 'total'); };
/* a leg as it will be bet in the current mode: teaser mode moves un-teased spreads and totals by the teaser's points */
function effLeg(l){
  const T = teaserOf();
  if (SLIP.mode !== 'teaser' || !T || l.tease || !(l.market === 'spread' || l.market === 'total') || l.line == null || l.line === '') return l;
  const e = Object.assign({}, l, {tease: T.pts, from: Number(l.line)});
  e.line = l.market === 'spread' ? Number(l.line) + T.pts : (l.side === 'U' ? Number(l.line) + T.pts : Number(l.line) - T.pts);
  e.p = l.sport === A.sport && A.modelP ? A.modelP(e) : null;
  return e;
}
function slipMath(){
  const legs = SLIP.legs.map(effLeg), n = legs.length, T = teaserOf();
  const ps = legs.map(l => l.p), known = ps.filter(p => p != null).length;
  const p = known === n && n ? ps.reduce((a, b) => a * b, 1) : null;
  const same = new Set(legs.map(l => l.sport + ':' + l.game)).size < n;
  let computed = null;
  if (SLIP.mode === 'parlay') computed = legs.every(l => parseOdds(l.odds) != null) ? amOf(legs.reduce((a, l) => a * dec(parseOdds(l.odds)), 1)) : null;
  if (SLIP.mode === 'teaser' && T) computed = T.prices[n] ?? null;
  const book = parseOdds(SLIP.book);
  const price = book ?? computed;
  const stake = Number(SLIP.stake) || 1;
  return {legs, n, p, known, same, computed, book, price, stake, win: price != null ? stake * (dec(price) - 1) : null, T};
}
function fairHtml(p, price, same, n){
  if (p == null) return `<div class="small">Give every leg a model chance to see the fair price. Team totals and custom legs have none.</div>`;
  const fair = oddsNum(p);
  let h = `<div class="sf-m"><span class="big num">${pct(p, p < 0.1 ? 1 : 0)}</span><span>model chance all ${n} legs hit · fair price <b>${fmtOdds(fair)}</b></span></div>`;
  if (price != null){ const r = evMsg(p, fair, String(price)); h += `<div class="ev ${r.c}">${esc(r.t)}</div>`; }
  if (same) h += `<div class="small" style="color:var(--warn)">Two legs come from the same game, so they rise and fall together. The true chance is different from this multiplication, and most books won't let you parlay them straight.</div>`;
  if (SLIP.mode !== 'teaser' && SLIP.legs.some(l => l.tease)) h += `<div class="small" style="color:var(--warn)">A teased leg only exists inside a teaser. Remove the other legs or switch to Teaser.</div>`;
  return h;
}
function legFairHtml(l){
  const O = parseOdds(l.odds), p = l.p;
  if (p == null) return `<span class="small">No model chance for this leg${O != null ? ` · needs ${pct(impProb(O))} to break even` : ''}</span>`;
  const fair = oddsNum(p);
  if (O == null || SLIP.mode === 'teaser' || l.oddsFair) return `<span class="small">Model <b>${pct(p)}</b> · fair ${fmtOdds(fair)}${l.psrc === 'history' ? ' (from past legs like it)' : ''}${l.oddsFair && SLIP.mode !== 'teaser' ? ' · <b>type your book\'s odds</b>' : ''}</span>`;
  const r = evMsg(p, fair, String(O)), words = r.c === 'pos' ? 'good price' : r.c === 'thin' ? 'thin edge' : 'bad price';
  return `<span class="small">Model <b>${pct(p)}</b> · fair ${fmtOdds(fair)} · <b class="ev ${r.c}" style="font-size:12.5px">${words}</b></span>`;
}
const otherSport = l => l.sport !== A.sport;
function editHref(l){ return `${A.root}${SPORTS[l.sport].path}#slip`; }
function sportTag(s){ return `<span class="spb spb-${esc(s)}">${esc(SL(s))}</span>`; }
const mixed = () => new Set(SLIP.legs.map(l => l.sport)).size > 1 || (A.sport && SLIP.legs.some(otherSport));
function slipLegHtml(l0){
  const l = effLeg(l0), g = gameG(l) || {}, ro = otherSport(l0);
  const ou = isOU(l), hasLine = !noLine(l);
  const started = legStarted(l);
  const sideSeg = ou && !ro ? `<div class="seg" role="group" aria-label="Over or under"><button type="button" data-slside="O" data-lid="${l0.id}" aria-pressed="${l0.side !== 'U'}">Over</button><button type="button" data-slside="U" data-lid="${l0.id}" aria-pressed="${l0.side === 'U'}">Under</button></div>` : '';
  const lineIn = hasLine && !ro ? `<div class="f"><span class="clb-l">${l.market === 'spread' ? (l.sport === 'nhl' ? 'Puck line' : 'Spread') : 'Line'}${l.tease ? ' (teased)' : ''}</span>${stepWrap(`<input type="text" inputmode="decimal" autocomplete="off" data-slline="${l0.id}" value="${esc(l0.line ?? '')}" placeholder="${l.market === 'spread' ? '-2.5' : '0.5'}" aria-label="Line">`, l.market === 'spread' ? 'spread' : 'line')}</div>` : '';
  const oddsIn = SLIP.mode === 'teaser' ? '' : `<div class="f"><span class="clb-l">Odds</span>${stepWrap(`<input type="text" inputmode="numeric" autocomplete="off" data-slodds="${l0.id}" value="${esc(l0.odds == null || l0.odds === '' ? '' : fmtOdds(Number(l0.odds)).replace('−', '-'))}" placeholder="-110" aria-label="Odds">`, 'odds')}</div>`;
  const stakeIn = SLIP.mode === 'single' ? `<div class="f"><span class="clb-l">Stake</span>${stepWrap(`<input type="text" inputmode="decimal" autocomplete="off" data-slstake="${l0.id}" value="${esc(l0.stake ?? SLIP.stake ?? 1)}" aria-label="Stake in units">`, 'units')}</div>` : '';
  const O = parseOdds(l0.odds), single = SLIP.mode === 'single' && O != null ? `<span class="small">to win <b>${unitsTxt((Number(l0.stake ?? SLIP.stake) || 1) * (dec(O) - 1))}</b></span>` : '';
  const roNote = ro && (hasLine || ou) && A.sport != null ? `<a class="small sl-ed" href="${editHref(l0)}">Change the line on the ${SL(l0.sport)} page</a>` : '';
  return `<div class="sl" data-lid="${l0.id}">
    <div class="sl-top"><div class="sl-l"><div class="sl-n">${mixed() ? sportTag(l0.sport) + ' ' : ''}${esc(legLabel(l))}${l.tease ? ` <span class="pill ghost">${fmtLine(l.from)} → ${fmtLine(l.line)}</span>` : ''}</div>
      <div class="small">${esc(marketLabel(l))} · ${esc(legSub(l))}${started ? ` · <b style="color:var(--warn)">${g.hs != null ? 'final' : 'started'}</b>` : ''}</div></div>
      <button type="button" class="sl-x" data-sldel="${l0.id}" aria-label="Remove ${esc(legLabel(l))}">×</button></div>
    <div class="sl-row">${sideSeg}${lineIn}${oddsIn}${stakeIn}${roNote}</div>
    <div class="sl-fair" data-slfair="${l0.id}">${legFairHtml(l)}${single ? ' · ' + single : ''}</div></div>`;
}
function slipSumHtml(M){
  if (!M.n) return '';
  if (SLIP.mode === 'single'){
    const risk = SLIP.legs.reduce((a, l) => a + (Number(l.stake ?? SLIP.stake) || 1), 0);
    const win = SLIP.legs.reduce((a, l) => { const O = parseOdds(l.odds); return a + (O != null ? (Number(l.stake ?? SLIP.stake) || 1) * (dec(O) - 1) : 0); }, 0);
    return `<div class="slip-sum"><div class="ss-row"><span>${M.n} single bet${M.n === 1 ? '' : 's'}</span><span>risk <b>${unitsTxt(risk)}</b> · to win <b>${unitsTxt(win)}</b></span></div></div>`;
  }
  const teaser = SLIP.mode === 'teaser', pts = M.T ? M.T.pts : 6;
  return `<div class="slip-sum">
    <div class="ss-row"><span>${M.n}-leg ${teaser ? `${pts}-point teaser` : 'parlay'} odds</span><span class="big num">${M.price != null ? fmtOdds(M.price) : '–'}</span></div>
    <div class="small">${sumNote(M)}</div>
    <div class="ss-in"><div class="f"><span class="clb-l">Book's ${teaser ? 'teaser' : 'parlay'} price</span>${stepWrap(`<input type="text" inputmode="numeric" autocomplete="off" id="slip-book" value="${esc(SLIP.book || '')}" placeholder="${M.computed != null ? fmtOdds(M.computed).replace('−', '-') : '+600'}" aria-label="Book's parlay price">`, 'odds')}</div>
      <div class="f"><span class="clb-l">Stake</span>${stepWrap(`<input type="text" inputmode="decimal" autocomplete="off" id="slip-stake" value="${esc(SLIP.stake)}" aria-label="Stake in units">`, 'units')}</div>
      <div class="ss-win"><span class="clb-l">To win</span><b class="num">${M.win != null ? unitsTxt(M.win) : '–'}</b><span class="small">${M.win != null ? `pays ${unitsTxt(M.win + M.stake)}` : ''}</span></div></div>
    <div class="slip-fair" id="slip-fair">${fairHtml(M.p, M.price, M.same, M.n)}</div>
    ${teaser ? `<div class="small">Pushes drop a leg: a ${M.n}-teamer with one push pays as a ${M.n - 1}-teamer${M.n === 2 ? ', and a 2-teamer with a push is refunded' : ''}.</div>` : M.n > 1 ? `<div class="small">A pushed or voided leg drops out and the rest pays at its own odds.</div>` : ''}
  </div>`;
}
function sumNote(M){
  if (SLIP.mode === 'teaser') return `Typical ${M.n}-team teaser price. Type your book's price below if it differs.`;
  return M.computed != null ? `Multiplied from the legs: ${fmtOdds(M.computed)}${M.book != null && M.book !== M.computed ? ` · your book's ${fmtOdds(M.book)} is ${M.book > M.computed ? 'better' : 'worse'} than the multiply` : ''}` : 'Give every leg a price and the parlay odds multiply out here.';
}
function renderSlip(){
  const sh = $('#slipsheet'); if (!sh || sh.hidden) return;
  const M = slipMath(), T = teaserOf();
  const modes = [['single', 'Singles'], ['parlay', 'Parlay'], ['teaser', `Teaser ${T ? T.pts : ''}`]].filter(([k]) => k === 'single' || M.n >= 2).filter(([k]) => k !== 'teaser' || teaserOk());
  const sports = [...new Set(SLIP.legs.map(l => l.sport))];
  const emptyHelp = A.sport ? `Tap any spread, total or moneyline on a game card, or <b>+ Slip</b> next to a player prop, high-chance pick or long shot. Legs from the NFL, NBA and NHL pages all land in this one slip, so a parlay can mix sports.`
    : `Open a sport and tap any line on a game card, or <b>+ Slip</b> next to a prop, high-chance pick or long shot. Legs from every sport land in this one slip.`;
  sh.innerHTML = `<div class="sec-head"><h2 class="h3" id="slip-title">Bet slip <span class="small" style="text-transform:none;letter-spacing:0;font-family:var(--f-body);font-weight:600">${M.n ? `${M.n} leg${M.n === 1 ? '' : 's'}${sports.length > 1 ? ' · ' + sports.map(SL).join(' + ') : ''}` : ''}</span></h2>
      <div style="display:flex;gap:6px">${M.n ? '<button class="btn tiny" data-slipclear="">Clear</button>' : ''}<button class="btn tiny" data-slipclose="">Close</button></div></div>
    ${M.n ? `<div class="seg slip-mode" role="group" aria-label="Bet type">${modes.map(([k, l]) => `<button type="button" data-slmode="${k}" aria-pressed="${SLIP.mode === k}">${l}</button>`).join('')}</div>
      <div class="sl-list">${SLIP.legs.map(slipLegHtml).join('')}</div>${slipSumHtml(M)}
      <div class="sheet-actions"><span class="note" id="slip-err" role="alert"></span><span style="display:flex;gap:8px">${customBtn()}<button class="btn primary" data-slipplace="">${SLIP.mode === 'single' ? (M.n === 1 ? 'Place bet' : `Place ${M.n} bets`) : `Place ${SLIP.mode}`}</button></span></div>`
    : `<div class="empty"><div class="h3">Your slip is empty</div><p class="lede" style="margin:0">${emptyHelp}</p></div>
      <div class="sheet-actions"><span></span>${customBtn()}</div>`}`;
}
function customBtn(){ return A.sport ? '<button class="btn" data-slipcustom="">+ Custom leg</button>' : ''; }
function refreshSlipUI(){
  const fab = $('#slip-fab'), n = SLIP.legs.length;
  if (fab){
    fab.hidden = n === 0; document.body.classList.toggle('has-slip', n > 0);
    if (n){ const M = slipMath(); $('#sf-n', fab).textContent = String(n); $('#sf-t', fab).textContent = n === 1 ? 'Bet slip' : SLIP.mode === 'single' ? `${n} singles` : SLIP.mode === 'teaser' ? `${n}-leg teaser` : `${n}-leg parlay`; $('#sf-o', fab).textContent = SLIP.mode !== 'single' && M.price != null ? fmtOdds(M.price) : ''; }
  }
  $$('[data-ob]').forEach(b => { const l = LEGREG[b.dataset.ob]; b.setAttribute('aria-pressed', String(!!l && inSlip(l))); });
  $$('[data-slipkey]').forEach(b => b.classList.toggle('on', SLIP.legs.some(x => x.key === b.dataset.slipkey)));
  renderSlip();
  if (A.onChange) A.onChange();
}
function inSlip(l){ const k = slipKey(l); return SLIP.legs.some(x => x.key === k && sameLeg(Object.assign({key: k}, l), x)); }
function openSlip(){ const sh = $('#slipsheet'); if (!sh) return; $('#slipscrim').hidden = false; sh.hidden = false; document.body.style.overflow = 'hidden'; renderSlip(); setTimeout(() => { const b = $('#slipsheet [data-slipclose]'); if (b) b.focus(); }, 0); }
function closeSlip(){ const sh = $('#slipsheet'); if (!sh) return; $('#slipscrim').hidden = true; sh.hidden = true; document.body.style.overflow = ''; }
/* an odds button on a game card: tapping it toggles that leg in the slip */
function oddsBtn(leg, main, sub, cls){
  if (!leg) return `<span class="ob off" aria-hidden="true"><span class="ob-m">–</span><span class="ob-s"></span></span>`;
  leg = Object.assign({sport: A.sport}, leg);
  const k = [slipKey(leg), leg.side || '', leg.line ?? ''].join('|'); LEGREG[k] = leg;
  return `<button type="button" class="ob${cls ? ' ' + cls : ''}" data-ob="${esc(k)}" aria-pressed="${inSlip(leg)}" aria-label="${esc(legLabel(leg))} at ${esc(fmtOdds(leg.odds))}"><span class="ob-m">${main}</span><span class="ob-s">${sub}</span></button>`;
}

/* ---------- placing ---------- */
function placeSlip(){
  const err = $('#slip-err'), M = slipMath();
  for (const l of M.legs){
    if (!noLine(l) && (l.line == null || l.line === '' || isNaN(l.line))) return err.textContent = `Enter the line for ${legLabel(l)}.`;
    if (SLIP.mode !== 'teaser' && parseOdds(l.odds) == null) return err.textContent = `Enter American odds for ${legLabel(l)}, like -110 or +150.`;
  }
  if (SLIP.mode !== 'single' && M.price == null) return err.textContent = 'Enter the parlay price.';
  const now = new Date().toISOString(), made = [];
  const snap = l => { const c = decorate(Object.assign({}, l)); delete c.stake; c.odds = parseOdds(c.odds) ?? c.odds; c.p = c.p == null ? null : Math.round(c.p * 10000) / 10000; return c; };
  const wkOf = legs => { const w = legs.filter(l => l.sport === 'nfl' && l.week).map(l => l.week); return w.length === legs.length && w.length ? Math.max.apply(null, w) : undefined; };
  if (SLIP.mode === 'single'){
    M.legs.forEach(l => { const c = snap(l); made.push({kind: 'bet', id: uid('bet'), created: now, week: wkOf([c]), type: 'single', stake: Number(l.stake ?? SLIP.stake) || 1, odds: parseOdds(l.odds), legs: [c],
                                                         fair: l.p == null ? null : {p: l.p, odds: oddsNum(l.p)}}); });
  } else {
    const legs = M.legs.map(snap);
    made.push({kind: 'bet', id: uid('bet'), created: now, week: wkOf(legs), type: SLIP.mode, stake: M.stake, odds: M.price, legs,
               fair: M.p == null ? null : {p: M.p, odds: oddsNum(M.p), same: M.same}, computed: M.computed, pts: SLIP.mode === 'teaser' && M.T ? M.T.pts : undefined});
  }
  BETS = BETS.concat(made); saveBets();
  clearSlip(); closeSlip(); renderBets();
  toast(made.length === 1 ? `Bet placed · ${made[0].type === 'single' ? legLabel(made[0].legs[0]) : made[0].legs.length + '-leg ' + made[0].type}` : `${made.length} bets placed`);
}

/* ---------- storage, and the move from the NFL-only keys ---------- */
let BETS = [];
function migratePick(p){
  const other = ['parlay', 'teaser', 'other'].includes(p.type);
  const leg = other ? {id: 'leg_' + p.id, sport: 'nfl', market: 'other', game: p.game, week: p.week, label: p.note || (p.type === 'parlay' ? 'Parlay' : p.type === 'teaser' ? 'Teaser' : 'Bet'), odds: p.odds, manual: p.manual || null}
    : {id: 'leg_' + p.id, sport: 'nfl', market: p.type, game: p.game, week: p.week, team: p.team || null, player: p.player || null, player_name: p.player_name || null, side: p.side === 'U' ? 'U' : (['any_td', 'first_td', 'td2'].includes(p.type) ? 'Y' : 'O'), line: p.line, odds: p.odds, manual: p.manual || null};
  return {kind: 'bet', id: p.id, created: p.created, week: p.week, type: p.type === 'parlay' ? 'parlay' : p.type === 'teaser' ? 'teaser' : 'single', stake: Number(p.units) || 1, odds: p.odds, legs: [leg], note: other ? '' : (p.note || ''), legacy: true};
}
function normBet(b){ (b.legs || []).forEach(l => { if (!l.sport) l.sport = 'nfl'; if (l.res === 'C') delete l.res; }); return b; }
function loadBets(){
  let b = LS.get('bets', null);
  if (b == null){
    let old = null; try { old = JSON.parse(LS.raw('nfledge.bets') || 'null'); } catch(e){}
    if (old == null){ let picks = []; try { picks = JSON.parse(LS.raw('nfledge.picks') || '[]') || []; } catch(e){} old = picks.filter(p => p && p.id && p.type).map(migratePick); }
    b = (old || []).map(normBet); LS.set('bets', b);
  } else b = b.map(normBet);
  return b;
}
function saveBets(){ LS.set('bets', BETS.map(x => { const c = Object.assign({}, x); delete c._g; delete c._fix; return c; })); }
function deleteBet(id){ BETS = BETS.filter(x => x.id !== id); saveBets(); renderBets(); }
function setBetResult(id, r){ const b = BETS.find(x => x.id === id); if (!b) return; b.manual = b.manual === r ? null : r; saveBets(); renderBets(); }
function setLegResult(bid, lid, r){ const b = BETS.find(x => x.id === bid); const l = b && b.legs.find(x => x.id === lid); if (!l) return; l.manual = l.manual === r ? null : r; saveBets(); renderBets(); }
/* grade everything we can, and keep each settled leg's result on the leg so it never needs the data again */
function gradeAll(){
  let dirty = false;
  BETS.forEach(b => {
    b.legs.forEach(l => needGrade(l.sport));
    b._g = gradeBet(b);
    b._g.legs.forEach(x => { if (!x.stored && !x.leg.manual && settled(x.r) && (x.leg.res !== x.r || (x.leg.act ?? null) !== (x.actual ?? null))){ x.leg.res = x.r; x.leg.act = x.actual ?? null; dirty = true; } });
  });
  if (dirty) saveBets();
}

/* ---------- My bets ---------- */
function summarizeBets(list){
  const s = {W: 0, L: 0, P: 0, open: 0, units: 0, risk: 0, openRisk: 0};
  list.forEach(b => { const r = b._g.r; if (r){ s[r]++; s.units += betProfit(b, b._g); s.risk += Number(b.stake) || 1; } else { s.open++; s.openRisk += Number(b.stake) || 1; } });
  s.pct = s.W + s.L ? s.W / (s.W + s.L) : null; s.roi = s.risk ? s.units / s.risk : null;
  return s;
}
let PF = Object.assign({status: 'all', type: 'all', sport: 'all'}, LS.get('pf', {}));
const betSports = b => [...new Set(b.legs.map(l => l.sport))];
function renderBets(){
  const v = A.betsEl && $(A.betsEl); if (!v) return;
  gradeAll();
  const s = summarizeBets(BETS);
  if (A.countEl && $(A.countEl)) $(A.countEl).textContent = s.open ? String(s.open) : '';
  const allSports = [...new Set(BETS.flatMap(betSports))].sort((a, b) => Object.keys(SPORTS).indexOf(a) - Object.keys(SPORTS).indexOf(b));
  if (PF.sport !== 'all' && !allSports.includes(PF.sport)) PF.sport = 'all';
  const inSport = b => PF.sport === 'all' || betSports(b).includes(PF.sport);
  const pool = BETS.filter(inSport), ss = summarizeBets(pool);
  const list = pool.filter(b => (PF.status === 'all' || (PF.status === 'open' ? !b._g.r : !!b._g.r)) && (PF.type === 'all' || b.type === PF.type))
    .sort((a, b) => (!!a._g.r - !!b._g.r) || String(b.created).localeCompare(String(a.created)));
  const row = (label, x) => `<tr><td>${label}</td><td class="r num">${x.W}-${x.L}${x.P ? '-' + x.P : ''}</td><td class="r num">${x.pct == null ? '–' : pct(x.pct, 1)}</td>
      <td class="r num" style="color:${x.units > 0 ? 'var(--win)' : x.units < 0 ? 'var(--loss)' : 'inherit'}">${sign(x.units, 2)}u</td><td class="r num">${x.roi == null ? '–' : pct(x.roi, 1)}</td><td class="r num">${x.open || ''}</td></tr>`;
  const sportRows = allSports.length > 1 ? allSports.map(sp => row(sportTag(sp), summarizeBets(BETS.filter(b => betSports(b).length === 1 && b.legs[0].sport === sp))))
    .concat(BETS.some(b => betSports(b).length > 1) ? [row('Mixed-sport parlays', summarizeBets(BETS.filter(b => betSports(b).length > 1)))] : []).join('') : '';
  const typeRows = ['single', 'parlay', 'teaser'].map(k => [k, pool.filter(b => b.type === k)]).filter(x => x[1].length).map(([k, l]) => row(TYPE_LABEL[k] + 's', summarizeBets(l))).join('');
  const legStats = {};
  pool.forEach(b => b._g.legs.forEach(x => { const l = x.leg; if (PF.sport !== 'all' && l.sport !== PF.sport) return; const k = l.sport + ':' + l.market; const o = legStats[k] = legStats[k] || {W: 0, L: 0, P: 0, open: 0, l};
    if (x.r === 'W' || x.r === 'L') o[x.r]++; else if (x.r === 'P' || x.r === 'V') o.P++; else o.open++; }));
  const multiSport = allSports.length > 1 && PF.sport === 'all';
  const legRows = Object.entries(legStats).sort((a, b) => (b[1].W + b[1].L) - (a[1].W + a[1].L)).map(([k, o]) => `<tr><td>${multiSport ? sportTag(o.l.sport) + ' ' : ''}${esc(marketLabel(o.l))}<div class="small">${esc(mkOf(o.l).cat || '')}</div></td><td class="r num">${o.W}-${o.L}${o.P ? '-' + o.P : ''}</td>
      <td class="r num">${o.W + o.L ? pct(o.W / (o.W + o.L), 1) : '–'}</td><td><div class="wbar" title="Break-even at -110 is 52.4%"><span style="width:${o.W + o.L ? (100 * o.W / (o.W + o.L)).toFixed(1) : 0}%"></span><i></i></div></td><td class="r num">${o.open || ''}</td></tr>`).join('');
  const cl = pool.flatMap(b => b.legs.map(clvLeg)).filter(c => c && c.closed && c.unit === 'pts');
  const clvTile = cl.length ? (() => { const beat = cl.filter(c => c.v > 0).length, avg = cl.reduce((a, c) => a + c.v, 0) / cl.length;
    return `<div class="tile"><div class="label">Beat the closing line</div><div class="v num ${avg > 0 ? 'pos' : avg < 0 ? 'neg' : ''}">${beat}/${cl.length}</div><div class="small">Spread and total legs, average ${sign(avg, 1)} pts. The best early sign of a real edge.</div></div>`; })()
    : `<div class="tile"><div class="label">Beat the closing line</div><div class="v num">–</div><div class="small">Shows once your spread or total legs start</div></div>`;
  const sportSeg = allSports.length > 1 ? `<div class="seg" role="group" aria-label="Sport">${['all'].concat(allSports).map(k => `<button type="button" data-pfsport="${k}" aria-pressed="${PF.sport === k}">${k === 'all' ? 'All sports' : SL(k)}</button>`).join('')}</div>` : '';
  const help = A.sport ? `Tap any line on a game card, or <b>+ Slip</b> next to a player prop, high-chance pick or long shot. Build a parlay by adding more legs, from any sport, then place it from the slip.`
    : `Open a sport, tap any line on a game card or <b>+ Slip</b> next to a prop or pick, then place it from the slip.`;
  v.innerHTML = `
    <div class="sec-head"><div><h1 class="h2">My bets</h1><p class="lede">Singles, parlays and teasers from every sport. Each leg grades itself from the final score or box score; a parlay is lost the moment a leg loses and won when every leg is in.</p></div>
      <div class="filters"><button class="btn" data-pkbackup="">Download backup</button><label class="btn" for="pk-restore" style="cursor:pointer">Restore backup</label>
      <input type="file" id="pk-restore" accept="application/json,.json" hidden><button class="btn stripe" data-slipopen="">Bet slip${SLIP.legs.length ? ` (${SLIP.legs.length})` : ''}</button></div></div>
    ${sportSeg}
    <div class="tiles">
      <div class="tile"><div class="label">Record${PF.sport !== 'all' ? ' · ' + SL(PF.sport) : ''}</div><div class="v num">${ss.W}-${ss.L}${ss.P ? '-' + ss.P : ''}</div><div class="small">${ss.pct == null ? 'Settled bets' : pct(ss.pct, 1) + ' of settled bets'}</div></div>
      <div class="tile"><div class="label">Units</div><div class="v num ${ss.units > 0 ? 'pos' : ss.units < 0 ? 'neg' : ''}">${sign(ss.units, 2)}</div><div class="small">ROI ${ss.roi == null ? '–' : pct(ss.roi, 1)} on ${unitsTxt(ss.risk)} risked</div></div>
      <div class="tile"><div class="label">Open</div><div class="v num">${ss.open}</div><div class="small">${ss.open ? unitsTxt(ss.openRisk) + ' at risk' : 'No open bets'}</div></div>
      ${clvTile}
    </div>
    ${BETS.length ? `${sportRows && PF.sport === 'all' ? `<div class="sec-head"><h2 class="h3">By sport</h2></div>
      <div class="tbl-wrap"><table class="grid"><thead><tr><th>Sport</th><th class="r">W-L-P</th><th class="r">Win %</th><th class="r">Units</th><th class="r">ROI</th><th class="r">Open</th></tr></thead><tbody>${sportRows}</tbody></table></div>` : ''}
      ${typeRows ? `<div class="sec-head"><h2 class="h3">By bet type</h2></div>
      <div class="tbl-wrap"><table class="grid"><thead><tr><th>Type</th><th class="r">W-L-P</th><th class="r">Win %</th><th class="r">Units</th><th class="r">ROI</th><th class="r">Open</th></tr></thead><tbody>${typeRows}</tbody></table></div>` : ''}
      ${legRows ? `<div class="sec-head"><h2 class="h3">Legs by market</h2><span class="small">Every leg across your bets</span></div>
      <div class="tbl-wrap"><table class="grid"><thead><tr><th>Market</th><th class="r">W-L-P</th><th class="r">Hit %</th><th>Hit rate vs. break-even</th><th class="r">Open</th></tr></thead><tbody>${legRows}</tbody></table></div>` : ''}
      <div class="sec-head"><h2 class="h3">Tickets</h2><div class="filters">
        <select id="pf-status" aria-label="Status"><option value="all">All</option><option value="open">Open</option><option value="settled">Settled</option></select>
        <select id="pf-type" aria-label="Bet type"><option value="all">All types</option><option value="single">Singles</option><option value="parlay">Parlays</option><option value="teaser">Teasers</option></select></div></div>
      <div class="tickets">${list.map(ticketHtml).join('') || '<div class="empty">No bets match.</div>'}</div>` :
      `<div class="empty"><div class="h3">No bets yet</div><p class="lede" style="margin:0">${help}</p></div>`}
    <div class="note">Your bets are saved in this browser on this device, shared by every sport's page. Use Download backup to keep a copy or move them to another phone or computer.</div>
    ${A.extraBetsHtml ? A.extraBetsHtml() : ''}`;
  const st = $('#pf-status'); if (st){ st.value = PF.status; st.addEventListener('change', e => { PF.status = e.target.value; LS.set('pf', PF); renderBets(); }); }
  const ty = $('#pf-type'); if (ty){ ty.value = PF.type; ty.addEventListener('change', e => { PF.type = e.target.value; LS.set('pf', PF); renderBets(); }); }
  const rs = $('#pk-restore'); if (rs) rs.addEventListener('change', restoreBets);
}
function backupBets(){
  const clean = BETS.map(x => { const c = Object.assign({}, x); delete c._g; delete c._fix; return c; });
  const blob = new Blob([JSON.stringify({app: 'sports-edge', saved: new Date().toISOString(), bets: clean}, null, 1)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'sports-edge-bets-' + new Date().toISOString().slice(0, 10) + '.json';
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
async function restoreBets(e){
  const f = e.target.files && e.target.files[0]; if (!f) return;
  try {
    const j = JSON.parse(await f.text()); let list = Array.isArray(j) ? j : (j.bets || j.picks);
    if (!Array.isArray(list)) throw new Error('format');
    list = list.filter(p => p && p.id).map(p => p.kind === 'bet' && Array.isArray(p.legs) ? normBet(p) : migratePick(p));
    const byId = new Map(BETS.map(p => [p.id, p])); list.forEach(p => byId.set(p.id, p));
    BETS = [...byId.values()]; saveBets(); renderBets(); toast('Restored ' + list.length + ' bets');
  } catch(err){ toast("That file isn't a Sports Edge or NFL Edge backup."); }
}
function actualTxt(l, x){
  if (x.actual == null) return '';
  if (l.market === 'spread' || l.market === 'ml') return x.actual > 0 ? `${l.team} won by ${x.actual}` : x.actual < 0 ? `${l.team} lost by ${Math.abs(x.actual)}` : 'tied';
  return typeof x.actual === 'number' ? 'result: ' + x.actual : String(x.actual);
}
function ticketLegHtml(b, x, multi){
  const l = x.leg, r = x.r;
  const c = clvLeg(l);
  const clv = c ? `<span class="small">${c.closed ? 'closing' : 'line now'} ${c.txt} · <b style="color:${c.v > 0 ? 'var(--win)' : c.v < 0 ? 'var(--loss)' : 'inherit'}">${c.v > 0 ? 'beat it by ' : c.v < 0 ? 'behind by ' : 'same as yours'}${c.v ? Math.abs(c.v).toFixed(1) + (c.unit === 'pts' ? ' pts' : '% win chance') : ''}</b></span>` : '';
  const act = actualTxt(l, x);
  const manual = l.market === 'other' || r === 'C' || l.manual || (b._fix && r) ? `<span class="tk-man">${['W', 'L', 'P'].map(k => `<button class="btn tiny" data-legres="${esc(b.id)}|${esc(l.id)}|${k}" aria-pressed="${l.manual === k}">${k}</button>`).join('')}</span>` : '';
  const fair = l.p != null ? `<span class="small">model ${pct(l.p)}${parseOdds(l.odds) != null && b.type === 'single' ? '' : ' · fair ' + fmtOdds(oddsNum(l.p))}</span>` : '';
  const wait = !r && !G[l.sport] && l.sport !== A.sport ? ' · <span class="small">loading the result…</span>' : '';
  return `<div class="tk-leg"><span class="dot ${r || 'open'}" title="${RWORD[r] || 'Open'}"></span>
    <div style="min-width:0"><div class="tk-ln">${multi ? sportTag(l.sport) + ' ' : ''}${esc(legLabel(l))}${l.tease ? ` <span class="pill ghost">${fmtLine(l.from)} → ${fmtLine(l.line)}</span>` : ''}${b.type !== 'teaser' && l.odds != null && l.odds !== '' ? ` <span class="tk-o num">${fmtOdds(Number(l.odds))}</span>` : ''}</div>
      <div class="tk-ls">${esc(marketLabel(l))} · ${esc(legSub(l))}${act ? ' · ' + esc(act) : ''}${fair ? ' · ' + fair : ''}${clv ? ' · ' + clv : ''}${r === 'V' ? ' · <span class="small">most books void a prop when the player sits</span>' : ''}${r === 'C' ? ' · <span class="small" style="color:var(--warn)">no box-score line found, set it yourself</span>' : ''}${wait}</div></div>
    ${manual}</div>`;
}
function ticketHtml(b){
  const gr = b._g, r = gr.r, n = b.legs.length, sp = betSports(b);
  const head = b.type === 'single' ? marketLabel(b.legs[0]) : b.legacy ? `${TYPE_LABEL[b.type]} · logged as a note` : `${n}-leg ${b.type === 'teaser' ? `${b.pts || 6}-point teaser` : 'parlay'}`;
  const status = r ? (gr.voided ? 'Void' : RWORD[r]) : (gr.check ? 'Check a leg' : 'Open');
  const prof = r ? betProfit(b, gr) : null;
  const money = r ? `<span class="tk-amt ${prof > 0 ? 'pos' : prof < 0 ? 'neg' : ''}">${sign(prof, 2)}u</span>` : `<span class="tk-amt">${unitsTxt(Number(b.stake) || 1)} <span class="small">to win</span> ${unitsTxt(toWin(b))}</span>`;
  const fairTxt = b.fair && b.fair.p != null ? (() => { const ev = evOf(b.fair.p, Number(b.odds)); return `Model ${pct(b.fair.p, b.fair.p < 0.1 ? 1 : 0)} · fair ${fmtOdds(b.fair.odds)} · you got ${fmtOdds(Number(b.odds))} (<span style="color:${ev >= 0.05 ? 'var(--win)' : ev >= 0 ? 'var(--warn)' : 'var(--loss)'}">${ev >= 0 ? '+' : '−'}${Math.abs(Math.round(ev * 100))}¢ per $1</span>)${b.fair.same ? ' · same-game legs' : ''}`; })() : (b.legacy ? 'Logged with the old pick form' : '');
  const fixable = r && !b.manual && !gr.legs.some(x => x.leg.market === 'other');
  const manualBtns = (b.manual || gr.check || gr.legs.some(x => x.leg.market === 'other' && !x.leg.manual) || b._fix) ? ['W', 'L', 'P'].map(k => `<button class="btn tiny" data-betres="${esc(b.id)}|${k}" aria-pressed="${b.manual === k}">${k}</button>`).join('') : '';
  const when = (b.week && sp.length === 1 && sp[0] === 'nfl' ? `Week ${b.week} · ` : '') + `placed ${esc(new Date(b.created).toLocaleDateString([], {month: 'short', day: 'numeric'}))}`;
  return `<article class="tk ${r || 'open'}">
    <div class="tk-h"><div><div class="tk-t">${sp.map(sportTag).join('')}${esc(head)}<span class="tk-st ${r || 'open'}">${status}</span></div>
      <div class="small">${when} · ${fmtOdds(Number(b.odds))}</div></div>${money}</div>
    <div class="tk-legs">${gr.legs.map(x => ticketLegHtml(b, x, sp.length > 1)).join('')}</div>
    <div class="tk-f"><span class="small">${fairTxt}</span><span class="acts">${manualBtns}${fixable ? `<button class="btn tiny" data-betfix="${esc(b.id)}">Fix result</button>` : ''}<button class="btn tiny" data-delbet="${esc(b.id)}" aria-label="Delete bet">Delete</button></span></div>
  </article>`;
}

/* ---------- custom leg form (anything not on a card: team totals, other props, bets the site doesn't list) ---------- */
let draft = null;
const MKS = () => MK[A.sport] || {};
function gamesIn(per){ return (A.customGames ? A.customGames() : []).filter(g => String(g.per) === String(per)).sort((a, b) => String(a.k).localeCompare(String(b.k))); }
function defaultLine(d){
  const S = G[A.sport], g = S && S.games ? S.games[d.game] : null; if (!g) return '';
  if (d.type === 'spread' && g.sp != null) return d.team === g.h ? -g.sp : g.sp;
  if (d.type === 'total' && g.tl != null) return g.tl;
  return '';
}
function openCustom(pre){
  if (!A.sport) return;
  const gs = A.customGames ? A.customGames() : []; if (!gs.length) return toast('No games to pick from right now.');
  const g0 = gs.find(g => !g.final) || gs[0];
  draft = Object.assign({per: g0.per, game: g0.id, type: 'spread', team: g0.a, side: 'O', line: '', odds: -110, player: '', note: ''}, pre || {});
  if (draft.line === '') draft.line = defaultLine(draft);
  renderSheet();
  $('#scrim').hidden = false; $('#sheet').hidden = false;
  setTimeout(() => { const f = $('#pk-type'); if (f) f.focus(); }, 0);
}
function closeCustom(){ const sh = $('#sheet'); if (!sh) return; $('#scrim').hidden = true; sh.hidden = true; draft = null; }
function renderSheet(){
  const d = draft, M_ = MKS(), def = M_[d.type] || {}, gs = A.customGames(), g = gs.find(x => x.id === d.game) || {};
  const pers = []; gs.forEach(x => { if (!pers.some(p => String(p[0]) === String(x.per))) pers.push([x.per, x.perLabel]); });
  const perOpts = pers.map(([k, lb]) => `<option value="${esc(k)}" ${String(k) === String(d.per) ? 'selected' : ''}>${esc(lb)}</option>`).join('');
  const gameOpts = gamesIn(d.per).map(x => `<option value="${esc(x.id)}" ${x.id === d.game ? 'selected' : ''}>${esc(x.a)} @ ${esc(x.h)}${x.final ? ' (final)' : ''}</option>`).join('');
  const typeOpts = ['Game', 'Player', 'Other'].map(c => `<optgroup label="${c}">${Object.keys(M_).filter(k => M_[k].cat === c).map(k => `<option value="${k}" ${k === d.type ? 'selected' : ''}>${M_[k].label}</option>`).join('')}</optgroup>`).join('');
  const tmp = {sport: A.sport, market: d.type};
  const needsTeam = ['spread', 'ml', 'team_total'].includes(d.type);
  const needsSide = isOU(tmp);
  const needsLine = !noLine(tmp);
  const pl = def.cat === 'Player' ? (A.players ? A.players(d.game) : []) : [];
  const perName = (SPORTS[A.sport] || {}).period || 'Week';
  $('#sheet').innerHTML = `
    <div class="sec-head"><h2 class="h3" id="sheet-title">Custom leg</h2><button class="btn tiny" id="pk-close">Close</button></div>
    <form class="form" id="pk-form" novalidate>
      <div class="f"><label for="pk-per">${perName}</label><select id="pk-per">${perOpts}</select></div>
      <div class="f"><label for="pk-game">Game</label><select id="pk-game">${gameOpts}</select></div>
      <div class="f full"><label for="pk-type">Market</label><select id="pk-type">${typeOpts}</select></div>
      ${def.cat === 'Player' ? `<div class="f full"><label for="pk-player">Player</label><select id="pk-player"><option value="">Choose a player</option>${pl.map(p => `<option value="${esc(p.id)}" ${p.id === d.player ? 'selected' : ''}>${esc(p.t)} · ${esc(p.n)}${p.p ? ` (${esc(p.p)})` : ''}</option>`).join('')}</select></div>` : ''}
      ${needsTeam ? `<div class="f"><label for="pk-team">Team</label><select id="pk-team"><option value="${esc(g.a)}" ${d.team === g.a ? 'selected' : ''}>${esc(g.a)}</option><option value="${esc(g.h)}" ${d.team === g.h ? 'selected' : ''}>${esc(g.h)}</option></select></div>` : ''}
      ${needsSide ? `<div class="f"><label for="pk-side">Side</label><select id="pk-side"><option value="O" ${d.side === 'O' ? 'selected' : ''}>Over</option><option value="U" ${d.side === 'U' ? 'selected' : ''}>Under</option></select></div>` : ''}
      ${needsLine ? `<div class="f stpf"><label for="pk-line">${d.type === 'spread' ? `${A.sport === 'nhl' ? 'Puck line' : 'Spread'} (your team)` : 'Line'}</label>${stepWrap(`<input id="pk-line" type="text" inputmode="decimal" autocomplete="off" value="${esc(d.line)}" placeholder="${d.type === 'spread' ? (A.sport === 'nhl' ? '-1.5' : '-2.5') : '0.5'}">`, d.type === 'spread' ? 'spread' : 'line')}</div>` : ''}
      <div class="f stpf"><label for="pk-odds">Odds</label>${stepWrap(`<input id="pk-odds" type="text" inputmode="numeric" autocomplete="off" value="${esc(d.odds === '' || d.odds == null ? '' : fmtOdds(Number(d.odds)).replace('−', '-'))}" placeholder="-110">`, 'odds')}</div>
      ${d.type === 'other' ? `<div class="f full"><label for="pk-note">What is the bet?</label><input id="pk-note" type="text" value="${esc(d.note)}" placeholder="${esc(A.otherHint || 'Describe the bet')}"></div>` : ''}
      <div class="f full"><div class="hint" id="pk-hint">${def.cat === 'Other' ? 'You mark this leg won or lost yourself.' : 'Grades automatically from the final score or box score.'}</div></div>
    </form>
    <div class="sheet-actions"><span class="note" id="pk-err" role="alert"></span><button class="btn primary" id="pk-save">Add to slip</button></div>`;
  const bind = (id, key) => { const el = $('#' + id); if (!el) return; el.addEventListener('change', e => { draft[key] = e.target.value;
    if (key === 'per'){ const gs2 = gamesIn(draft.per); draft.game = gs2.length ? gs2[0].id : ''; }
    if (key === 'per' || key === 'game'){ const gg = A.customGames().find(x => x.id === draft.game); if (gg) draft.team = gg.a; draft.player = ''; }
    if (['per', 'game', 'team', 'type'].includes(key) && (draft.type === 'spread' || draft.type === 'total')) draft.line = defaultLine(draft);
    if (['per', 'game', 'type', 'team'].includes(key)) renderSheet(); }); };
  bind('pk-per', 'per'); bind('pk-game', 'game'); bind('pk-type', 'type'); bind('pk-player', 'player'); bind('pk-team', 'team'); bind('pk-side', 'side');
  ['pk-line', 'pk-odds', 'pk-note'].forEach(id => { const el = $('#' + id); if (el) el.addEventListener('input', e => { const k = id.slice(3); const n = numOf(e.target.value); draft[k] = k === 'note' ? e.target.value : (e.target.value.trim() === '' ? '' : (n == null ? NaN : n)); }); });
  $('#pk-close').addEventListener('click', closeCustom);
  $('#pk-save').addEventListener('click', saveCustomLeg);
  $('#pk-form').addEventListener('submit', e => { e.preventDefault(); saveCustomLeg(); });
}
function saveCustomLeg(){
  const d = draft, def = MKS()[d.type] || {}, err = $('#pk-err'), tmp = {sport: A.sport, market: d.type};
  if (!d.game) return err.textContent = 'Choose a game.';
  if (def.cat === 'Player' && !d.player) return err.textContent = 'Choose a player.';
  if (!noLine(tmp) && (d.line === '' || isNaN(d.line))) return err.textContent = 'Enter the line.';
  if (d.odds === '' || isNaN(d.odds) || (d.odds > -100 && d.odds < 100)) return err.textContent = 'Enter American odds, like -110 or +150.';
  if (d.type === 'other' && !String(d.note || '').trim()) return err.textContent = 'Say what the bet is.';
  const g = A.customGames().find(x => x.id === d.game) || {};
  const pl = def.cat === 'Player' ? ((A.players ? A.players(d.game) : []).find(p => p.id === d.player) || {}) : {};
  const leg = {sport: A.sport, market: d.type, game: d.game, team: ['spread', 'ml', 'team_total'].includes(d.type) ? d.team : (def.cat === 'Player' ? pl.t || null : null),
    side: isOU(tmp) ? d.side : (def.y != null || def.first ? 'Y' : undefined), line: d.line === '' || noLine(tmp) ? null : Number(d.line), odds: Number(d.odds),
    player: def.cat === 'Player' ? d.player : null, player_name: def.cat === 'Player' ? (pl.n || plName({sport: A.sport, player: d.player}) || null) : null,
    label: d.type === 'other' ? d.note.trim() : null, mu: g.a ? g.a + ' @ ' + g.h : ''};
  if (leg.side === undefined) delete leg.side;
  if (d.type === 'other') leg.key = 'other:' + d.game + ':' + uid('x');
  closeCustom(); addLeg(leg, {open: true});
}

/* ---------- events ---------- */
const SLIP_SEL = '[data-ob],[data-slipopen],[data-slipclose],[data-slipclear],[data-slipplace],[data-slipcustom],[data-slmode],[data-slside],[data-sldel],[data-addpick],[data-delbet],[data-betres],[data-legres],[data-betfix],[data-pfsport],[data-pkbackup]';
let wired = false;
function wire(){
  if (wired) return; wired = true;
  document.addEventListener('click', e => {
    const t = e.target.closest(SLIP_SEL); if (!t) return;
    e.stopPropagation();
    const d = t.dataset;
    if (d.ob != null){ const l = LEGREG[d.ob]; if (l) addLeg(l, {toggle: true}); return; }
    if (d.slipopen != null){ openSlip(); return; }
    if (d.slipclose != null){ closeSlip(); return; }
    if (d.slipclear != null){ clearSlip(); return; }
    if (d.slipplace != null){ placeSlip(); return; }
    if (d.slipcustom != null || d.addpick != null){ closeSlip(); openCustom(); return; }
    if (d.slmode){ SLIP.mode = d.slmode; SLIP.modeSet = true; SLIP.book = ''; saveSlip(); refreshSlipUI(); return; }
    if (d.slside){ const l = SLIP.legs.find(x => x.id === d.lid); if (l){ l.side = d.slside; l.p = legP(l); l.desc = legLabel(l); saveSlip(); refreshSlipUI(); } return; }
    if (d.sldel){ removeLeg(d.sldel); return; }
    if (d.pfsport){ PF.sport = d.pfsport; LS.set('pf', PF); renderBets(); return; }
    if (d.pkbackup != null){ backupBets(); return; }
    if (d.delbet){
      if (d.confirm === '1'){ deleteBet(d.delbet); toast('Bet deleted'); }
      else { t.dataset.confirm = '1'; t.textContent = 'Tap again to delete'; setTimeout(() => { if (t.isConnected){ t.dataset.confirm = ''; t.textContent = 'Delete'; } }, 3000); }
      return;
    }
    if (d.betres){ const [id, r] = d.betres.split('|'); setBetResult(id, r); return; }
    if (d.legres){ const [bid, lid, r] = d.legres.split('|'); setLegResult(bid, lid, r); return; }
    if (d.betfix){ const b = BETS.find(x => x.id === d.betfix); if (b){ b._fix = !b._fix; renderBets(); } return; }
  }, true);
  document.addEventListener('input', e => {
    const el = e.target; if (!el.dataset) return;
    const upd = (id, fn) => { const l = SLIP.legs.find(x => x.id === id); if (!l) return; fn(l); l.p = legP(l); l.desc = legLabel(l); saveSlip(); slipLiveUpdate(id); };
    if (el.dataset.slline) upd(el.dataset.slline, l => { const n = numOf(el.value); l.line = el.value.trim() === '' ? '' : (n == null ? l.line : n); });
    else if (el.dataset.slodds) upd(el.dataset.slodds, l => { l.odds = el.value.trim(); delete l.oddsFair; });
    else if (el.dataset.slstake) upd(el.dataset.slstake, l => { const n = numOf(el.value); l.stake = n == null || n <= 0 ? 1 : n; });
    else if (el.id === 'slip-book'){ SLIP.book = el.value.trim(); saveSlip(); slipLiveUpdate(); }
    else if (el.id === 'slip-stake'){ const n = numOf(el.value); SLIP.stake = n == null || n <= 0 ? 1 : n; saveSlip(); slipLiveUpdate(); }
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if ($('#sheet') && !$('#sheet').hidden && draft) closeCustom();
    else if ($('#slipsheet') && !$('#slipsheet').hidden) closeSlip();
  });
  const fab = $('#slip-fab'); if (fab) fab.addEventListener('click', openSlip);
  const ss = $('#slipscrim'); if (ss) ss.addEventListener('click', closeSlip);
  const sc = $('#scrim'); if (sc) sc.addEventListener('click', () => { if (draft) closeCustom(); });
  /* another tab (another sport's page) changed the slip or the bets */
  window.addEventListener('storage', e => {
    if (e.key === 'sportsedge.slip'){ loadSlip(); refreshSlipUI(); }
    else if (e.key === 'sportsedge.bets'){ BETS = loadBets(); renderBets(); }
  });
}
/* refresh the numbers in the open slip without rebuilding the inputs someone is typing in */
function slipLiveUpdate(id){
  const M = slipMath();
  if (id){ const l = SLIP.legs.find(x => x.id === id), box = $(`[data-slfair="${CSS.escape(id)}"]`); if (l && box){ const e_ = effLeg(l), O = parseOdds(l.odds); box.innerHTML = legFairHtml(e_) + (SLIP.mode === 'single' && O != null ? ` · <span class="small">to win <b>${unitsTxt((Number(l.stake ?? SLIP.stake) || 1) * (dec(O) - 1))}</b></span>` : ''); } }
  const sum = $('#slipsheet .slip-sum');
  if (sum){
    if (SLIP.mode === 'single'){ sum.outerHTML = slipSumHtml(M); }
    else {
      const big = $('.ss-row .big', sum); if (big) big.textContent = M.price != null ? fmtOdds(M.price) : '–';
      const note = big && big.closest('.ss-row').nextElementSibling; if (note) note.innerHTML = sumNote(M);
      const win = $('.ss-win b', sum); if (win) win.textContent = M.win != null ? unitsTxt(M.win) : '–';
      const pays = $('.ss-win .small', sum); if (pays) pays.textContent = M.win != null ? `pays ${unitsTxt(M.win + M.stake)}` : '';
      const fair = $('#slip-fair'); if (fair) fair.innerHTML = fairHtml(M.p, M.price, M.same, M.n);
      const bk = $('#slip-book'); if (bk) bk.placeholder = M.computed != null ? fmtOdds(M.computed).replace('−', '-') : '+600';
    }
  }
  const fab = $('#slip-fab'); if (fab && !fab.hidden){ $('#sf-o', fab).textContent = SLIP.mode !== 'single' && M.price != null ? fmtOdds(M.price) : ''; }
}

function init(adapter){
  A = Object.assign({sport: null, root: '', modelP: null}, adapter || {});
  if (A.sport && A.grade) G[A.sport] = A.grade;
  loadSlip(); BETS = loadBets();
  wire();
  SLIP.legs.forEach(l => { if (l.sport === A.sport){ const p = legP(l); if (p != null) l.p = p; decorate(l); } });
  renderBets(); refreshSlipUI();
  const h = location.hash;
  if (h === '#slip') setTimeout(openSlip, 50);
  else if (h === '#custom' && A.sport) setTimeout(() => openCustom(), 50);
}
/* the page's own sport just got fresher scores (live scoreboard): regrade with them */
function setGrade(sport, grade){ G[sport] = grade; regrade(); }

window.SB = {init, addLeg, removeLeg, oddsBtn, openSlip, closeSlip, openCustom, closeCustom, refresh: refreshSlipUI, renderBets, setGrade,
             legLabel, marketLabel, clv: clvLeg, gradeLeg, bets: () => BETS, slip: () => SLIP, slipKey, inSlip, MK, TEASERS,
             summary: () => { gradeAll(); return summarizeBets(BETS); }, needGrade, sportTag};
})();
