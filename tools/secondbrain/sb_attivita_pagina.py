#!/usr/bin/env python3
"""Writes the SecondBrain tasks page for the phone: one self-contained, read-only HTML file.

Usage:
    .venv/bin/python tools/secondbrain/sb_attivita_pagina.py <output.html>

It is a snapshot of the tasks engine (sb_attivita.py) with a grouped list, a table and a board by status, search,
filters and sorting. To change a task, use SecondBrain on the Mac.
"""





from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sb_attivita as A  # noqa: E402
import sb_telefono as T  # noqa: E402

DESCR_MAX = 6000


def dati() -> dict:
    ""



    f = T.fotografia(DESCR_MAX)
    righe = []
    for t in f["task"]:
        stima = t["stima"]
        righe.append(
            {
                "id": t["id"],
                "t": (t["titolo"] or "").strip(),
                "p": t["priorita"],
                "s": t["stato"],
                "chiusa": t["chiusa"],
                "a": t["area_nome"] or "",
                "d": str(t["scadenza"] or "")[:10] or None,
                "e": stima,
                "es": A.stima_frase(stima) if stima else "",
                "x": t["descrizione"],
                "c": str(t["creata"] or "")[:10],
                "m": str(t["cambiata"] or "")[:16],
                "ch": str(t["chiusa_il"] or "")[:10] or None,
                "u": t["link"],
            }
        )
    return {
        "quando": f["quando"][:16],
        "stati": [{k: s[k] for k in ("id", "nome", "tipo", "colore")} for s in f["stati"]],

        "urgenti": f["urgenti"],
        "task": righe,
    }


PAGINA = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>Tasks · SBK</title>
<style>
:root{--fondo:#F6F5F2;--carta:#FFFFFF;--riga:#E7E5E0;--testo:#1D1C1A;--piano:#6B6A66;--tenue:#9A9893;--accento:#1F4E99;
--p0f:#FDE0DC;--p0t:#A8231B;--p1f:#FCE5D2;--p1t:#94450C;--p2f:#FAEFC9;--p2t:#735400;--p3f:#ECECEA;--p3t:#5C5B57}
*{box-sizing:border-box}
html,body{margin:0;background:var(--fondo);color:var(--testo);font:15px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;-webkit-text-size-adjust:100%}
button,select,input{font:inherit;color:inherit}
/* the compact header for the phone: only the title row and the search stay pinned at the top. Views, priorities and menu live
   in the commands, which go away when you scroll down and come back when you scroll up, like the Safari bar */
.testa{position:-webkit-sticky;position:sticky;top:0;z-index:6;background:var(--fondo);border-bottom:1px solid transparent;padding:14px 16px 8px;transition:border-color .2s}
.testa.sola{border-bottom-color:var(--riga)}
.comandi{position:-webkit-sticky;position:sticky;top:var(--alto,100px);z-index:5;background:var(--fondo);border-bottom:1px solid var(--riga);padding:0 16px 10px;transition:transform .22s ease,opacity .22s ease}
.comandi.via{transform:translateY(-100%);opacity:0;pointer-events:none}
.titolo{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
h1{font-size:24px;line-height:1.15;margin:0;letter-spacing:-.01em}
.quando{color:var(--tenue);font-size:12px;white-space:nowrap}
.conto{font-size:12px;color:var(--piano)}
.cerca{display:flex;gap:8px;margin-top:10px}
.cerca input{flex:1;min-width:0;border:1px solid var(--riga);background:var(--carta);border-radius:10px;padding:9px 12px;font-size:16px;outline:none}
.cerca input:focus{border-color:#B9C8E4;box-shadow:0 0 0 3px rgba(31,78,153,.12)}
.viste{display:flex;background:#ECEAE5;border-radius:10px;padding:2px;margin-top:2px}
.viste button{flex:1;border:0;background:transparent;padding:7px 4px;border-radius:8px;font-size:14px;color:var(--piano);cursor:pointer}
.viste button.su{background:var(--carta);color:var(--testo);box-shadow:0 1px 2px rgba(0,0,0,.08);font-weight:600}
/* only the four priorities with their counts are shown, the rest in More filters */
.filtri{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-top:10px}
.prio{flex:none;height:30px;padding:0 8px;border-radius:7px;font-size:12.5px;font-weight:700;border:1.5px solid transparent;white-space:nowrap;cursor:pointer;-webkit-appearance:none;appearance:none}
.prio span{font-weight:600}
.prio.su{border-color:currentColor}
.prio.spenta{opacity:.45}
.filtri .conto{margin-left:auto;white-space:nowrap}
.scelte{display:flex;gap:8px;margin-top:8px}
.scelte select,.scelte .altri{flex:1;min-width:0;height:34px;border:1px solid var(--riga);background:var(--carta);border-radius:10px;padding:0 10px;font-size:14px;-webkit-appearance:none;appearance:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:left;cursor:pointer}
.scelte .altri.su{border-color:var(--testo);font-weight:600}
main{padding:12px 16px 40px;max-width:1100px;margin:0 auto}
.gruppo{margin:6px 0 18px}
.gruppo h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--piano);margin:0 0 8px;display:flex;gap:8px;align-items:center}
.gruppo h2 .n{color:var(--tenue);font-weight:500}
.carta{background:var(--carta);border:1px solid var(--riga);border-radius:12px;padding:11px 12px;margin-bottom:8px;cursor:pointer;display:flex;gap:10px;align-items:flex-start}
.carta:active{background:#FBFAF8}
.pill{flex:none;font-size:11px;font-weight:700;line-height:16px;height:18px;padding:1px 6px;border-radius:4px;letter-spacing:.02em}
.p0{background:var(--p0f);color:var(--p0t)}.p1{background:var(--p1f);color:var(--p1t)}.p2{background:var(--p2f);color:var(--p2t)}.p3{background:var(--p3f);color:var(--p3t)}
.corpo{min-width:0;flex:1}
.nome{font-weight:600;font-size:15px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.chiusa .nome{color:var(--tenue);text-decoration:line-through}
.meta{display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:4px;font-size:12.5px;color:var(--piano)}
.punto{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:1px}
/* due dates like in the Mac app: no red or orange */
.sc{white-space:nowrap}
.sc.scaduta{color:var(--testo);font-weight:500}
.sc.scaduta::before{content:"!";display:inline-block;width:12px;height:12px;line-height:11px;margin-right:4px;border:1.2px solid var(--tenue);border-radius:50%;font-size:9px;font-weight:700;text-align:center;color:var(--piano);vertical-align:1px}
.sc.passata{color:var(--tenue)}
.sc.passata::before{content:"◷";margin-right:3px;font-size:11px}
.sc.oggi{color:var(--testo);font-weight:600}
.sc.vicina{color:var(--testo)}
.sc.lontana{color:var(--piano)}
.vuoto{color:var(--tenue);text-align:center;padding:40px 10px}
.tab{width:100%;border-collapse:separate;border-spacing:0;background:var(--carta);border:1px solid var(--riga);border-radius:12px;overflow:hidden;font-size:13.5px}
.tabbox{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:12px}
.tab th{position:sticky;top:0;background:#F1EFEB;text-align:left;font-weight:600;font-size:12px;color:var(--piano);padding:8px 10px;border-bottom:1px solid var(--riga);white-space:nowrap;cursor:pointer;user-select:none}
.tab td{padding:8px 10px;border-bottom:1px solid #F0EEEA;vertical-align:top}
.tab td:not(.tit){white-space:nowrap}
.tab tr:last-child td{border-bottom:0}
.tab td.tit{min-width:220px;max-width:420px;font-weight:500}
.tab td.tit .tl{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
@media(max-width:520px){.tab{font-size:13px}.tab td{padding:7px 8px}.tab td.tit{min-width:170px}}
.tab tr{cursor:pointer}
.tab .fr{color:var(--tenue);font-weight:400;margin-left:3px}
.bacheca{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch}
.colonna{flex:none;width:min(82vw,300px);scroll-snap-align:start;background:#EFEDE8;border-radius:12px;padding:10px 8px}
.colonna h2{font-size:13px;margin:2px 4px 10px;color:var(--piano);display:flex;justify-content:space-between}
.colonna .carta{margin-bottom:6px;padding:9px 10px}
.velo{position:fixed;inset:0;background:rgba(20,19,18,.32);z-index:20;display:none;align-items:flex-end;justify-content:center}
.velo.su{display:flex}
.scheda{background:var(--carta);width:100%;max-width:640px;max-height:88vh;overflow-y:auto;border-radius:16px 16px 0 0;padding:16px 18px 28px;box-shadow:0 -8px 30px rgba(0,0,0,.15)}
@media(min-width:700px){.velo{align-items:center}.scheda{border-radius:16px}}
.scheda .chiudi{float:right;border:0;background:#EFEDE8;border-radius:999px;width:30px;height:30px;font-size:18px;line-height:30px;cursor:pointer;color:var(--piano)}
.scheda h3{font-size:19px;line-height:1.3;margin:2px 40px 10px 0}
.campi{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;font-size:14px;margin:10px 0 14px}
.campi dt{color:var(--tenue)}.campi dd{margin:0}
.descr{white-space:pre-wrap;word-wrap:break-word;font-size:14.5px;line-height:1.5;border-top:1px solid var(--riga);padding-top:12px}
.piede{color:var(--tenue);font-size:12px;text-align:center;margin-top:18px}
/* the More filters sheet */
.modifica{display:flex;flex-direction:column;gap:14px;margin:12px 0 6px}
.mc .ml{display:block;font-size:13px;color:var(--tenue);margin-bottom:7px}
.scegli{display:flex;flex-wrap:wrap;gap:6px}
.scegli button{border:1px solid var(--riga);background:var(--carta);border-radius:999px;padding:6px 11px;font-size:14px;color:var(--piano);white-space:nowrap;cursor:pointer;-webkit-appearance:none;appearance:none}
.scegli button.su{border-color:var(--testo);color:var(--testo);font-weight:600}
.azioni{display:flex;gap:8px;margin-top:16px}
.azioni button{flex:1;height:42px;border-radius:10px;border:1px solid var(--riga);background:var(--carta);font-weight:600;text-align:center;cursor:pointer;-webkit-appearance:none;appearance:none}
.azioni .primario{background:var(--testo);color:#fff;border-color:var(--testo)}
.azioni button[disabled]{opacity:.4;cursor:default}
a{color:var(--accento)}
</style>
</head>
<body>
<header class="testa" id="testa">
  <div class="titolo"><h1>Tasks</h1><span class="quando" id="quando"></span></div>
  <div class="cerca"><input id="q" type="search" placeholder="Search title, description, area" autocomplete="off"></div>
</header>
<div class="comandi" id="comandi">
  <div class="viste" id="viste">
    <button data-v="elenco" class="su">List</button><button data-v="tabella">Table</button><button data-v="bacheca">Board</button>
  </div>
  <div class="filtri" id="filtri"></div>
  <div class="scelte">
    <select id="gruppo" aria-label="Group">
      <option value="p">By priority</option><option value="a">By area</option><option value="s">By status</option><option value="d">By due date</option><option value="n">No group</option>
    </select>
    <select id="ordine" aria-label="Sort">
      <option value="p">↕ Priority</option><option value="d">↕ Due date</option><option value="m">↕ Last change</option><option value="a">↕ Area</option><option value="t">↕ Title</option>
    </select>
    <button class="altri" id="altri" type="button">More filters</button>
  </div>
</div>
<main id="vista"></main>
<div class="velo" id="velo"><div class="scheda" id="scheda"></div></div>
<script id="dati" type="application/json">__DATI__</script>
<script>
const D = JSON.parse(document.getElementById('dati').textContent);
const STATI = {}; D.stati.forEach((s, i) => STATI[s.id] = {...s, i});
const COLORI = {verde:'#2E8B4E', blu:'#2F6BC8', arancio:'#D07A1E', rosso:'#C8372D', giallo:'#C9A227', viola:'#7B4FB8', grigio:'#9A9893'};
const oggi = new Date(); oggi.setHours(0,0,0,0);
// --- dates: start (the tests run with node, tests/test_secondbrain_attivita_pagina.py)
const giorni = d => d ? Math.round((new Date(d + 'T00:00:00') - oggi) / 86400000) : null;
const NOMI_M = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const NOMI_G = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const U = D.urgenti || {p1:true, prima:6, dopo:7};
function dataCorta(d){ const x = new Date(d.slice(0,10) + 'T00:00:00'); return x.getDate() + ' ' + NOMI_M[x.getMonth()] + (x.getFullYear() !== oggi.getFullYear() ? ' ' + x.getFullYear() : ''); }
// «up front» like the engine's `_urgente`: P0, P1, and the due date from `dopo` days ago to `prima` days from now
function davanti(t){ if(t.chiusa) return false; if(t.p === 0 || (U.p1 && t.p === 1)) return true;
  const g = t.d ? giorni(t.d) : null; return g !== null && g >= -U.dopo && g <= U.prima; }
// the short due date and its tone, with the words and thresholds of the engine's `_breve` (no red: the tone is a cue)
function breve(d, dav){ if(!d) return ['', 'vuota']; const g = giorni(d); const x = new Date(d + 'T00:00:00');
  if(g === 0) return ['today', 'oggi']; if(g === 1) return ['tomorrow', 'vicina'];
  if(g >= 2 && g <= 6) return [NOMI_G[x.getDay()] + ' ' + x.getDate(), 'vicina']; if(g > 6) return [dataCorta(d), 'lontana'];
  const tono = dav ? 'scaduta' : 'passata'; if(g === -1) return ['yesterday', tono]; if(g >= -6) return [(-g) + ' days ago', tono];
  return [dataCorta(d), tono]; }
const scadenza = t => { if(!t.d) return ''; const [testo, tono] = breve(t.d, davanti(t)); return `<span class="sc ${tono}">${testo}</span>`; };
// when it changed, a past date: never the due-date words
function quando(d){ if(!d) return ''; const g = giorni(d.slice(0,10)); if(g === 0) return 'today'; if(g === -1) return 'yesterday';
  if(g < 0 && g >= -6) return (-g) + ' days ago'; return dataCorta(d); }
// --- dates: end
function dataLunga(d){ if(!d) return ''; const x = new Date(d.slice(0,10) + 'T00:00:00'); return x.getDate() + ' ' + NOMI_M[x.getMonth()] + ' ' + x.getFullYear() + (d.length > 10 ? ' at ' + d.slice(11,16) : ''); }
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const piega = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
D.task.forEach(t => t._q = piega(t.t + ' ' + t.x + ' ' + t.a));

const st = {vista:'elenco', q:'', pr:new Set(), stati:new Set(), area:'', gruppo:'p', ordine:'p', fatte:false, scadute:false};
const aree = [...new Set(D.task.map(t => t.a).filter(Boolean))].sort((a,b) => a.localeCompare(b, 'it'));

document.getElementById('quando').textContent = 'updated on ' + dataLunga(D.quando);
// the four priorities shown with the counts of open tasks (they used to be on a separate row), and next to them open and overdue
function filtriChip(){ const aperte = D.task.filter(t => !t.chiusa), n = p => aperte.filter(t => t.p === p).length;
  const scad = aperte.filter(t => t.d && giorni(t.d) < 0).length, qualcuna = st.pr.size > 0;
  document.getElementById('filtri').innerHTML = [0,1,2,3].map(p => `<button class="prio p${p}${st.pr.has(p) ? ' su' : qualcuna ? ' spenta' : ''}" type="button" data-p="${p}" aria-pressed="${st.pr.has(p)}">P${p} <span>${n(p)}</span></button>`).join('') +
    `<span class="conto"><b>${aperte.length}</b> open${scad ? ` · ${scad} overdue` : ''}</span>`; }
document.getElementById('filtri').addEventListener('click', e => { const b = e.target.closest('button[data-p]'); if(!b) return;
  const p = +b.dataset.p; st.pr.has(p) ? st.pr.delete(p) : st.pr.add(p); filtriChip(); disegna(); });
// «More filters»: the statuses, only overdue, also closed and the area, in a bottom sheet; the button shows how many are on
const quantiFiltri = () => st.stati.size + (st.scadute ? 1 : 0) + (st.fatte ? 1 : 0) + (st.area ? 1 : 0);
function altriFiltri(){ const n = quantiFiltri(), b = document.getElementById('altri');
  b.textContent = n ? `More filters · ${n}` : 'More filters'; b.classList.toggle('su', n > 0); }
let filtriAperti = false;
function disegnaFiltri(){ const sc = document.getElementById('scheda'), tenuto = sc.scrollTop;
  const scad = D.task.filter(t => !t.chiusa && t.d && giorni(t.d) < 0).length;
  const stati = D.stati.filter(s => s.tipo !== 'fatta' && s.tipo !== 'non_serve').map(s => `<button type="button" class="${st.stati.has(s.id) ? 'su' : ''}" data-fs="${esc(s.id)}"><span class="punto" style="background:${COLORI[s.colore]||COLORI.grigio}"></span>${esc(s.nome)}</button>`).join('');
  const area = [['', 'All areas'], ...aree.map(a => [a, a])].map(([v, n]) => `<button type="button" class="${st.area === v ? 'su' : ''}" data-fa="${esc(v)}">${esc(n)}</button>`).join('');
  const n = visibili().length;
  sc.innerHTML = `<button class="chiudi" type="button" aria-label="Close">×</button><h3>More filters</h3>` +
    `<div class="modifica"><div class="mc"><span class="ml">Status</span><div class="scegli">${stati}</div></div>` +
    `<div class="mc"><span class="ml">Show</span><div class="scegli"><button type="button" class="${st.scadute ? 'su' : ''}" data-fx="scadute">Only overdue · ${scad}</button><button type="button" class="${st.fatte ? 'su' : ''}" data-fx="fatte">Also closed</button></div></div>` +
    `<div class="mc"><span class="ml">Area</span><div class="scegli">${area}</div></div></div>` +
    `<div class="azioni"><button type="button" data-fx="togli"${quantiFiltri() ? '' : ' disabled'}>Clear these filters</button><button type="button" class="primario" data-fx="chiudi">${n === 0 ? 'No task' : n === 1 ? 'Show 1 task' : `Show ${n} tasks`}</button></div>`;
  sc.scrollTop = tenuto; }
function apriFiltri(){ filtriAperti = true; document.getElementById('scheda').scrollTop = 0; disegnaFiltri(); document.getElementById('velo').classList.add('su'); }
function chiudiVelo(){ document.getElementById('velo').classList.remove('su'); filtriAperti = false; }
function cambiaFiltro(b){ const d = b.dataset;
  if(d.fs !== undefined) st.stati.has(d.fs) ? st.stati.delete(d.fs) : st.stati.add(d.fs);
  else if(d.fa !== undefined) st.area = d.fa;
  else if(d.fx === 'scadute') st.scadute = !st.scadute;
  else if(d.fx === 'fatte') st.fatte = !st.fatte;
  else if(d.fx === 'togli'){ st.stati.clear(); st.area = ''; st.scadute = false; st.fatte = false; }
  else if(d.fx === 'chiudi') return chiudiVelo();
  else return;
  altriFiltri(); disegna(); disegnaFiltri(); }
document.getElementById('altri').addEventListener('click', apriFiltri);
document.getElementById('viste').addEventListener('click', e => { const b = e.target.closest('button'); if(!b) return; st.vista = b.dataset.v;
  document.querySelectorAll('#viste button').forEach(x => x.classList.toggle('su', x === b)); disegna(); });
document.getElementById('q').addEventListener('input', e => { st.q = piega(e.target.value.trim()); disegna(); });
document.getElementById('gruppo').addEventListener('change', e => { st.gruppo = e.target.value; disegna(); });
document.getElementById('ordine').addEventListener('change', e => { st.ordine = e.target.value; disegna(); });

function visibili(){ const parole = st.q ? st.q.split(/\s+/) : [];
  return D.task.filter(t => (st.fatte || !t.chiusa) && (!st.pr.size || st.pr.has(t.p)) && (!st.stati.size || st.stati.has(t.s)) &&
    (!st.area || t.a === st.area) && (!st.scadute || (t.d && giorni(t.d) < 0 && !t.chiusa)) && parole.every(w => t._q.includes(w))); }
function confronta(a, b){ const per = {
    p: () => a.p - b.p || (a.d || '9999').localeCompare(b.d || '9999') || a.t.localeCompare(b.t, 'it'),
    d: () => (a.d || '9999').localeCompare(b.d || '9999') || a.p - b.p,
    m: () => (b.m || '').localeCompare(a.m || ''),
    a: () => (a.a || '~').localeCompare(b.a || '~', 'it') || a.p - b.p,
    t: () => a.t.localeCompare(b.t, 'it') };
  return (a.chiusa - b.chiusa) || per[st.ordine](); }
function chiaveGruppo(t){ switch(st.gruppo){
  case 'p': return ['P' + t.p, t.p];
  case 'a': return [t.a || 'No area', t.a ? 0 : 1];
  case 's': { const s = STATI[t.s] || {nome:t.s, i:99}; return [s.nome, s.i]; }
  case 'd': { if(!t.d) return ['No due date', 9]; const g = giorni(t.d); return g < 0 ? ['Overdue', 0] : g === 0 ? ['Today', 1] : g <= 7 ? ['Next 7 days', 2] : g <= 31 ? ['Within a month', 3] : ['Later', 4]; }
  default: return ['', 0]; } }
function meta(t){ const s = STATI[t.s] || {nome:t.s, colore:'grigio'};
  return `<div class="meta"><span><span class="punto" style="background:${COLORI[s.colore]||COLORI.grigio}"></span>${esc(s.nome)}</span>${t.a ? `<span>${esc(t.a)}</span>` : ''}${scadenza(t)}${t.es ? `<span>${esc(t.es)}</span>` : ''}</div>`; }
const carta = t => `<div class="carta ${t.chiusa?'chiusa':''}" data-id="${t.id}"><span class="pill p${t.p}">P${t.p}</span><div class="corpo"><div class="nome">${esc(t.t)}</div>${meta(t)}</div></div>`;

function disegna(){ const v = document.getElementById('vista'); const lista = visibili().sort(confronta);
  if(!lista.length){ v.innerHTML = '<div class="vuoto">No task with these filters.</div>'; return; }
  if(st.vista === 'tabella'){ v.innerHTML = tabella(lista); return; }
  if(st.vista === 'bacheca'){ v.innerHTML = bacheca(lista); return; }
  const gruppi = new Map(); lista.forEach(t => { const [k, o] = chiaveGruppo(t); if(!gruppi.has(k)) gruppi.set(k, {o, r:[]}); gruppi.get(k).r.push(t); });
  v.innerHTML = [...gruppi.entries()].sort((a,b) => a[1].o - b[1].o || a[0].localeCompare(b[0], 'it')).map(([k, g]) =>
    `<section class="gruppo">${k ? `<h2>${st.gruppo === 'p' ? `<span class="pill p${k.slice(1)}">${k}</span>` : esc(k)}<span class="n">${g.r.length}</span></h2>` : ''}${g.r.map(carta).join('')}</section>`).join(''); }
function tabella(lista){ const s = id => (STATI[id] || {nome:id}).nome;
  const th = (k, n) => `<th data-o="${k}">${n}${st.ordine === k ? ' ↓' : ''}</th>`;
  return `<div class="tabbox"><table class="tab"><thead><tr>${th('p','P')}${th('t','Title')}<th>Status</th>${th('a','Area')}${th('d','Due date')}<th>Estimate</th>${th('m','Changed')}</tr></thead><tbody>` +
    lista.map(t => `<tr data-id="${t.id}" class="${t.chiusa?'chiusa':''}"><td><span class="pill p${t.p}">P${t.p}</span></td><td class="tit"><div class="tl">${esc(t.t)}</div></td><td>${esc(s(t.s))}</td><td>${esc(t.a)}</td><td>${scadenza(t)}</td><td>${esc(t.es)}</td><td>${quando(t.m)}</td></tr>`).join('') + '</tbody></table></div>'; }
function bacheca(lista){
  // the columns follow the chosen grouping (priority by default: almost all tasks are «To do», and a column
  // per status would hold almost all of them); «No group» lays them out by status
  if(st.gruppo === 'n' || st.gruppo === 's'){ const cols = D.stati.filter(s => st.fatte || (s.tipo !== 'fatta' && s.tipo !== 'non_serve'));
    return `<div class="bacheca">` + cols.map(s => { const r = lista.filter(t => t.s === s.id);
      return `<div class="colonna"><h2><span><span class="punto" style="background:${COLORI[s.colore]||COLORI.grigio}"></span>${esc(s.nome)}</span><span>${r.length}</span></h2>${r.map(carta).join('')}</div>`; }).join('') + `</div>`; }
  const gruppi = new Map(); lista.forEach(t => { const [k, o] = chiaveGruppo(t); if(!gruppi.has(k)) gruppi.set(k, {o, r:[]}); gruppi.get(k).r.push(t); });
  return `<div class="bacheca">` + [...gruppi.entries()].sort((a,b) => a[1].o - b[1].o || a[0].localeCompare(b[0], 'it')).map(([k, g]) =>
    `<div class="colonna"><h2><span>${st.gruppo === 'p' ? `<span class="pill p${k.slice(1)}">${k}</span>` : esc(k)}</span><span>${g.r.length}</span></h2>${g.r.map(carta).join('')}</div>`).join('') + `</div>`; }
document.getElementById('vista').addEventListener('click', e => { const th = e.target.closest('th[data-o]');
  if(th){ st.ordine = th.dataset.o; document.getElementById('ordine').value = st.ordine; disegna(); return; }
  const r = e.target.closest('[data-id]'); if(r) apri(r.dataset.id); });
function apri(id){ const t = D.task.find(x => x.id === id); if(!t) return; const s = STATI[t.s] || {nome:t.s, colore:'grigio'}; filtriAperti = false;
  const righe = [['Priority', `<span class="pill p${t.p}">P${t.p}</span>`], ['Status', `<span class="punto" style="background:${COLORI[s.colore]||COLORI.grigio}"></span>${esc(s.nome)}`],
    ['Area', esc(t.a || 'No area')], ['Due date', t.d ? `${dataLunga(t.d)} <span class="fr">(${breve(t.d, davanti(t))[0]})</span>` : '—'], ['Estimate', esc(t.es || '—')],
    ['Created', dataLunga(t.c)], ['Changed', t.m ? dataLunga(t.m.replace('T',' ')) : '—']];
  if(t.ch) righe.push(['Closed', dataLunga(t.ch)]);
  if(t.u) righe.push(['Source', `<a href="${esc(t.u)}" target="_blank" rel="noopener">open</a>`]);
  document.getElementById('scheda').innerHTML = `<button class="chiudi" aria-label="Close">×</button><h3>${esc(t.t)}</h3><dl class="campi">${righe.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>` +
    (t.x ? `<div class="descr">${esc(t.x)}</div>` : '') + `<div class="piede">To change it, use SBK on the Mac.</div>`;
  document.getElementById('velo').classList.add('su'); }
document.getElementById('velo').addEventListener('click', e => { if(e.target.id === 'velo' || e.target.closest('.chiudi')) return chiudiVelo();
  const b = e.target.closest('button'); if(b && filtriAperti) cambiaFiltro(b); });
document.addEventListener('keydown', e => { if(e.key === 'Escape') chiudiVelo(); });
// the compact header: the title row and the search stay pinned at the top; views, priorities and menu go away when you scroll
// down and come back when you scroll up, like the Safari bar; at the very top they are always there
const testaEl = document.getElementById('testa'), comandi = document.getElementById('comandi');
function altezzaTesta(){ document.documentElement.style.setProperty('--alto', testaEl.offsetHeight + 'px'); }
if(window.ResizeObserver) new ResizeObserver(altezzaTesta).observe(testaEl);
window.addEventListener('resize', altezzaTesta);
let yPrima = 0, spinta = 0, aspetta = false;
function comandiVia(via){ comandi.classList.toggle('via', via); testaEl.classList.toggle('sola', via); }
function dopoScroll(){ aspetta = false; const y = Math.max(0, window.scrollY), dy = y - yPrima; yPrima = y;
  if(y <= 4){ spinta = 0; return comandiVia(false); }
  if(!dy) return;
  // a small nudge is not enough; they go away only once their place at the top has already scrolled past, so no gap is left
  spinta = Math.sign(dy) === Math.sign(spinta) ? spinta + dy : dy;
  if(spinta > 12 && y > comandi.offsetHeight) comandiVia(true);
  else if(spinta < -12) comandiVia(false); }
window.addEventListener('scroll', () => { if(!aspetta){ aspetta = true; requestAnimationFrame(dopoScroll); } }, {passive: true});
altezzaTesta(); filtriChip(); altriFiltri(); disegna();
</script>
</body>
</html>
"""


def pagina(d: dict) -> str:

    corpo = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    return PAGINA.replace("__DATI__", corpo)


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) < 2 or argv[1].startswith("-"):
        print(__doc__)
        return 2
    d = dati()
    Path(argv[1]).write_text(pagina(d), encoding="utf-8")
    aperte = sum(1 for t in d["task"] if not t["chiusa"])
    print(
        f"wrote {argv[1]}: {len(d['task'])} tasks, {aperte} open, snapshot from {d['quando']}"
    )
    return 0


if __name__ == "__main__":
    _ = html
    sys.exit(main(sys.argv))
