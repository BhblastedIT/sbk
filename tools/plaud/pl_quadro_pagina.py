#!/usr/bin/env python3
""







from __future__ import annotations

import html
import json
import os
from pathlib import Path

DATA = Path(os.environ.get("SBK_DATA", Path.home() / ".sbk-data"))
QUADRO = DATA / "plaud" / "quadro"


def compatta(q: dict) -> dict:
    def riga(m: dict) -> dict:
        c = m.get("contesto") or {}
        return {
            "id": m["id"],
            "t": (m.get("titolo") or "")[:90],
            "d": m.get("data"),
            "o": (m.get("inizio") or "")[11:16],
            "dur": round(m.get("durata_min") or 0),
            "sn": m.get("minuti_senza_nome", 0),
            "vs": m.get("voci_senza_nome", 0),
            "v": m.get("voci", 0),
            "kb": m.get("fatti_kb", 0),
            "inv": c.get("invitati", 0),
            "luogo": (c.get("luogo") or [""])[0][:40],
            "call": c.get("call", False),
            "dp": c.get("di_persona", False),
            "g": m.get("gruppo", ""),
            "ev": (c.get("eventi") or [""])[0][:60],
            "ind": (m.get("indizi") or [])[:4],
            "tipo": m.get("tipo"),
            "tr": m.get("trascritta_da"),
            "uno": m.get("una_voce_sola", False),
        }

    _mesi = sorted({m["mese"] for m in q.get("per_mese", []) if m.get("mese")})
    _cut = _mesi[-12] if len(_mesi) > 12 else (_mesi[0] if _mesi else "")

    return {
        "generato": q.get("generato"),
        "obiettivo": q.get("obiettivo"),
        "perche": q.get("perche"),
        "metodo": q.get("metodo"),
        "indizi": [{k: v for k, v in i.items() if k != "casi"} for i in q.get("indizi", [])],
        "fiducia": q.get("fiducia_nomi", {}),
        "lotto": json.loads((QUADRO / "lotto-verifiche.json").read_text())
        if (QUADRO / "lotto-verifiche.json").exists()
        else {},
        "attivita": q.get("attivita"),
        "totali": q.get("totali"),
        "nomi": q.get("nomi"),
        "solidita": q.get("solidita"),
        "veridicita": q.get("veridicita"),
        "piano_nomi": q.get("piano_nomi", []),
        "per_mese": [m for m in q.get("per_mese", []) if m["mese"] >= _cut],
        "per_mese_prima": [m for m in q.get("per_mese", []) if m["mese"] < _cut],
        "kb": {
            **{k: v for k, v in (q.get("kb") or {}).items() if k != "piu_lunghe_fuori"},
            "lunghe": [
                riga({**m, "voci_senza_nome": 0})
                for m in (q.get("kb") or {}).get("piu_lunghe_fuori", [])
            ],
        },
        "contesto": q.get("contesto"),
        "mancano": [riga(m) for m in q.get("mancano", [])],
        "mancano_con_indizi": q.get("mancano_con_indizi"),
        "senza_trascrizione": q.get("senza_trascrizione"),
        "storia": q.get("storia", []),
        "regole": (q.get("regole") or {}).get("regole", []),
        "proposte_giudizio": q.get("proposte_giudizio") or {},
        "regole_in_calcolo": q.get("regole_in_calcolo") or [],
        "misura": _leggi("misura-giudizio.json", _misura_compatta),
        "pesi": _leggi("pesi-regole.json", lambda p: p.get("pesi_leggibili") or {}),
        "sfida": _leggi("sfida.json", lambda x: x),
    }


def _leggi(nome: str, f):
    p = QUADRO / nome
    try:
        return f(json.loads(p.read_text())) if p.exists() else {}
    except (ValueError, KeyError, TypeError):
        return {}


def _misura_compatta(m: dict) -> dict:
    ""
    g = m.get("giro2") or {}
    return {
        "voci": m.get("test_voci"),
        "top1": g.get("top1") or {},
        "fasce": g.get("fasce_tarate_incrociate") or {},
        "auto": g.get("auto_nomi_nuovi_tarata") or {},
    }


PAGINA = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Plaud, who's speaking</title>
<style>
:root{--bg:#f7f6f2;--card:#fff;--ink:#1d1d1b;--soft:#6b6a65;--line:#e6e3dc;--acc:#2f6f62;--acc-soft:#e3efeb;
--warn:#b7791f;--warn-soft:#fbf1dc;--bad:#a64b3c;--bad-soft:#f6e3df;--ok-soft:#e3efeb}
*{box-sizing:border-box}html{color-scheme:light}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 80px}
h1{font-size:28px;line-height:1.15;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:0 0 8px}
.sub{color:var(--soft);margin:0 0 18px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin:16px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:#fff}
.kpi b{display:block;font-size:26px;letter-spacing:-.02em}.kpi span{color:var(--soft);font-size:13px}
.kpi.acc{background:var(--acc-soft);border-color:#cfe2dc}.kpi.warn{background:var(--warn-soft);border-color:#f1dfb8}
.fatti li{margin:6px 0}.fatti small{color:var(--soft);display:block}
.barra{display:flex;height:22px;border-radius:7px;overflow:hidden;border:1px solid var(--line)}
.barra div{height:100%}.leg{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;font-size:13px;color:var(--soft)}
.leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--soft);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right;white-space:nowrap}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;background:#efede7;color:#55534d;white-space:nowrap}
.pill.fatto{background:var(--ok-soft);color:#24594e}.pill.corso{background:#e6edf7;color:#2c4f7c}.pill.te{background:var(--warn-soft);color:#7a5414}
.mesi{display:grid;grid-template-columns:64px 1fr 48px;gap:4px 10px;align-items:center;font-size:13px}
.mb{height:14px;border-radius:4px;background:#efede7;position:relative;overflow:hidden}.mb span{position:absolute;left:0;top:0;bottom:0}
.ctl{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 10px}.ctl input{flex:1;min-width:180px;padding:8px 10px;border:1px solid var(--line);border-radius:9px;font:inherit}
.ctl label{display:flex;flex:none;align-items:center;gap:6px;color:var(--soft);font-size:14px;white-space:nowrap}.ctl label input{margin:0}
details summary{cursor:pointer;color:var(--acc);margin:6px 0}
.muted{color:var(--soft)}.small{font-size:13px}
.ind{color:var(--soft);font-size:12px}
td,li,p{overflow-wrap:break-word}th{white-space:nowrap}td:first-child{white-space:nowrap}
.fig{margin:22px 0 8px}h4{font-size:13px;margin:0 0 6px;color:var(--soft);font-weight:600}
.schema{display:grid;grid-template-columns:1fr 28px 1.1fr 28px 1fr;gap:8px;align-items:center}
.schema .col{display:flex;flex-direction:column;gap:8px}
.box{border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:#fbfaf7}.box b{display:block;font-size:14px}.box span{display:block;font-size:13px}.box small{display:block;color:var(--soft);font-size:12px;margin-top:2px}
.box.centro{background:var(--acc-soft);border-color:#cfe2dc}.box.centro b{font-size:16px}.box.centro ul{margin:6px 0 0;padding-left:18px;font-size:13px}
.box.esito b{font-size:24px;letter-spacing:-.02em}.box.e1{border-left:5px solid #17604f}.box.e2{border-left:5px solid #3f9a80}.box.e3{border-left:5px solid #a9d3c5}
.freccia{height:2px;background:#cfcabd;position:relative}.freccia:after{content:"";position:absolute;right:-1px;top:-5px;border:6px solid transparent;border-left:8px solid #cfcabd;border-right:0}
.barra.seg{gap:2px;background:#fff;height:26px}.barra.seg div{border-radius:4px}
.hbs{display:flex;flex-direction:column;gap:10px}.hbr{display:grid;grid-template-columns:180px 1fr;gap:10px;align-items:center}.hbt{font-size:13px}
.hb{position:relative;height:22px;display:flex;align-items:center;gap:8px;margin:3px 0}.hb span{display:block;height:12px;border-radius:0 4px 4px 0;min-width:2px;flex:none}.hb em{font-style:normal;font-weight:600;font-size:13px}.hb small{color:var(--soft);font-size:12px}
.cals{display:grid;grid-template-columns:1fr 1fr;gap:18px}.cal{display:grid;grid-template-columns:86px 1fr 92px;gap:8px;align-items:center;font-size:13px;margin:5px 0}
.trk{position:relative;height:16px;background:linear-gradient(90deg,#efede7 0 100%) center/100% 2px no-repeat}.trk span{position:absolute;top:50%;transform:translate(-50%,-50%);border-radius:50%}
.trk .ln{height:3px;border-radius:2px;background:#cfcabd;transform:translateY(-50%)}.trk .dice{width:12px;height:12px;border:2px solid #6b6a65;background:#fff}.trk .fa{width:10px;height:10px;box-shadow:0 0 0 2px #fff}
.pesi{display:flex;flex-direction:column;gap:3px}.pr{display:grid;grid-template-columns:minmax(150px,280px) 1fr;gap:10px;align-items:center;font-size:13px}.pn small{color:var(--soft);margin-left:6px;font-size:11px}
.pb{position:relative;height:16px}.pb .z{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#cfcabd}.pb .b{position:absolute;top:3px;height:10px;border-radius:4px}
.sblocchi{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.sb{border:1px dashed #d8d2c4;border-radius:12px;padding:10px 12px}.sb b{display:block;font-size:14px}.sb span{display:block;font-size:13px}.sb small{display:block;color:var(--soft);font-size:12px;margin-top:4px}
details.tutte{margin-top:22px;border-top:1px solid var(--line);padding-top:8px}
.sfida .carte{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}
.carta{border:1px solid var(--line);border-left-width:5px;border-radius:12px;padding:10px 12px;background:#fff}.carta b{display:block;font-size:14px;margin:2px 0 4px}.carta p{margin:0;font-size:13px;color:#3d3c38}
.carta .liv{display:inline-flex;align-items:center;gap:5px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--soft)}.carta .liv i{font-style:normal;display:inline-grid;place-items:center;width:16px;height:16px;border-radius:50%;color:#fff;font-size:11px;font-weight:700}
.sf-g{border-left-color:#b4553f}.sf-g .liv i{background:#b4553f}.sf-a{border-left-color:#c07a1e}.sf-a .liv i{background:#c07a1e}.sf-n{border-left-color:#1f8a70;background:#f3faf7}.sf-n .liv i{background:#1f8a70}.sf-m{border-left-color:#a9d3c5}
ol.passi{counter-reset:p;list-style:none;padding:0;margin:0;display:grid;gap:8px}ol.passi li{counter-increment:p;display:grid;grid-template-columns:30px 1fr;gap:2px 10px;font-size:14px}ol.passi li:before{content:counter(p);grid-row:span 2;width:26px;height:26px;border-radius:50%;background:var(--acc-soft);color:#24594e;display:grid;place-items:center;font-weight:700;font-size:13px}ol.passi li span{color:var(--soft);font-size:13px}
.hb .base{position:absolute;top:2px;bottom:2px;width:2px;background:#1d1d1b}
@media (max-width:760px){.schema{grid-template-columns:1fr}.freccia{height:18px;width:2px;margin:0 auto}.freccia:after{right:-5px;top:auto;bottom:-2px;border:6px solid transparent;border-top:8px solid #cfcabd;border-bottom:0}.cals{grid-template-columns:1fr}.hbr{grid-template-columns:1fr}.pr{grid-template-columns:1fr;gap:0}}
@media (max-width:640px){h1{font-size:23px}section{padding:14px}.ctl label{white-space:normal}.ctl input{min-width:0;width:100%}.kpis{grid-template-columns:1fr 1fr}.mesi{grid-template-columns:44px 1fr 38px}table.resp thead{display:none}table.resp tr{display:block;border-bottom:1px solid var(--line);padding:6px 0}
table.resp td{display:block;border:0;padding:2px 0;overflow-wrap:anywhere}table.resp td:first-child{white-space:normal}table.resp td.n{text-align:left}}
</style></head><body><main id="app"></main>
<script id="dati" type="application/json">__DATI__</script>
<script>
const D=JSON.parse(document.getElementById('dati').textContent);
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const n=x=>(x??0).toLocaleString('en-US');
const ore=m=>m>=60?`${Math.floor(m/60)} h ${String(Math.round(m%60)).padStart(2,'0')}`:`${Math.round(m)} min`;
const data=s=>s?s.slice(8,10)+'/'+s.slice(5,7)+'/'+s.slice(2,4):'';
const link=id=>`https://web.plaud.ai/file/${id}`;
const COL={"confermato":"#2f6f62","solido":"#5c9b8b","una prova":"#a9cfc4","solo nome":"#ddd8cc","sospetto":"#e2b65c","smentito":"#c47a6c","senza nome":"#f0ede6"};
const st=D.storia||[];const s0=st[0]||{};const sN=st[st.length-1]||{};
function kpi(v,t,c=''){return `<div class="kpi ${c}"><b>${v}</b><span>${t}</span></div>`}
function stato(s){const c=s==='fatto'?'fatto':s==='in corso'?'corso':s==='aspetta te'?'te':'';return `<span class="pill ${c}">${e(s)}</span>`}
let h='';
h+=`<h1>Plaud, who's speaking</h1><p class="sub">${e(D.obiettivo?.frase)}<br><span class="small">Updated on ${e((D.generato||'').slice(0,16).replace('T',' at '))} · ${n(D.totali.registrazioni)} recordings, ${n(D.totali.ore)} hours</span></p>`;
// where we are
h+=`<section><h2>Where we are</h2><div class="kpis">`+
 kpi(D.nomi.pct_minuti_senza_nome+'%','of the spoken minutes without a name','warn')+
 kpi(n(D.nomi.voci_senza_nome),'unnamed speakers, in '+n(D.mancano.length)+' recordings')+
 kpi(D.solidita.pct_solidi_sui_nominati+'%','of the names are solid (confirmed or two proofs)','acc')+
 kpi(D.solidita.pct_sospetti_sui_nominati+'%','of the names have a signal against them')+
 kpi(D.veridicita.giuste+' of '+D.veridicita.voci_verificate_da_owner,'correct names among the speakers you verified yourself')+
 kpi(n(D.kb.registrazioni_fuori),'recordings with no facts in the knowledge base ('+n(D.kb.ore_fuori)+' hours)')+
 `</div><p class="small muted" style="margin-top:12px">Starting point: the first measure of ${data((s0.quando||'').slice(0,10))}. `+
 (st.length>1?`Since then: minutes without a name ${s0.pct_minuti_senza_nome}% → ${sN.pct_minuti_senza_nome}%, solid names ${s0.pct_solidi_sui_nominati}% → ${sN.pct_solidi_sui_nominati}%, your verifications ${s0.verificate_da_owner} → ${sN.verificate_da_owner}.`:'This is the first measure: from the next run you will see here how much we improve.')+`</p></section>`;
// la sfida
const SF=D.sfida||{};
if(SF.gruppi){const N=SF.numeri||{};const LIV={grave:['serious','!','sf-g'],alto:['important','i','sf-a']};
 h+=`<section class="sfida"><h2>The challenge to the judgment, ${e(SF.quando)}</h2><p>${e(SF.intro)}</p><div class="kpis">`+kpi(n(N.agenti),'review agents')+kpi(n(N.rilievi),'things found, '+n(N.misurati)+' with a measure')+kpi(n(N.gravi),'serious, can write a wrong name','warn')+kpi(n(N.regole_nuove),'new rules and ideas proposed','acc')+`</div>`+
 SF.gruppi.map(g=>{const [lab,ic,cl]=LIV[g.livello]||LIV.alto;return `<h3 class="fig">${e(g.titolo)}</h3><div class="carte">`+g.voci.map(v=>`<div class="carta ${cl}"><span class="liv"><i>${ic}</i>${lab}</span><b>${e(v.t)}</b><p>${e(v.d)}</p></div>`).join('')+`</div>`}).join('')+
 `<h3 class="fig">New rules found</h3><p class="small muted" style="margin:0 0 8px">The first three are the strongest among those measured. None is in the calculation yet.</p><div class="carte">`+(SF.regole_nuove||[]).map(r=>`<div class="carta ${r.forte?'sf-n':'sf-m'}">${r.forte?'<span class="liv"><i>+</i>the strongest</span>':''}<b>${e(r.t)}</b><p>${e(r.d)}</p></div>`).join('')+`</div>`+
 `<h3 class="fig">Where the teams disagree</h3><ul class="fatti">`+(SF.disaccordi||[]).map(x=>`<li><b>${e(x.t)}</b><small>${e(x.d)}</small></li>`).join('')+`</ul>`+
 `<h3 class="fig">The order of the work, before the final optimization</h3><ol class="passi">`+(SF.ordine||[]).map(x=>`<li><b>${e(x.t)}</b><span>${e(x.d)}</span></li>`).join('')+`</ol>`+
 `<h3 class="fig">What is needed from you</h3><div class="sblocchi">`+(SF.da_te||[]).map(x=>`<div class="sb"><b>${e(x.t)}</b><small>${e(x.d)}</small></div>`).join('')+`</div></section>`;}
// why
const P=D.perche||{};
h+=`<section><h2>Why Plaud no longer gives the names</h2><p><b>${e(P.in_breve)}</b></p><ul class="fatti">`+
 (P.fatti||[]).map(f=>`<li>${e(f.cosa)}<small>${e(f.prova)}</small></li>`).join('')+`</ul>`+
 (P.cosa_resta_aperto?.length?`<h3>What stays open</h3><ul class="fatti">${P.cosa_resta_aperto.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:'')+
 `<p>${e(P.conseguenza)}</p></section>`;
// the method
const M=D.metodo||{};
if(M.passi){h+=`<section><h2>The method, in your words</h2><p><b>${e(M.in_breve)}</b></p><table class="resp"><tbody>`+
 M.passi.map(p=>`<tr><td class="n" style="color:var(--soft)">${p.n}</td><td><b>${e(p.passo)}</b><div class="small muted">${e(p.parole)} · ${e(p.quando)}</div></td></tr>`).join('')+`</tbody></table>`+
 (M.scoperte?.length?`<h3 style="margin-top:14px">What came out of searching the past</h3><ul class="fatti">${M.scoperte.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:'')+`</section>`;}
// indizi e verifiche
const RG=D.regole||[];
if(RG.length||(D.indizi||[]).length){
 const conta=st=>RG.filter(r=>r.stato===st).length;
 const EFF={'a favore':'brings a name','contro':'removes a name','esclude':'excludes'};
 const DOVE={'voce':'on the speaker','voce per voce':'on the speaker','roster':'on who was there','roster (chi c\'era)':'on who was there','attributo':'on the speaker'};
 const STATO={'attiva':'useful','spenta':'off','misura':'for measuring','da sbloccare':'to unlock'};
 const FR=[['R1','Sources at the time of the recording','Calendar, call transcripts, WhatsApp calls and messages, email, Slack, Plaud\'s data. Here the chance baseline is the same rule with the time shifted by a few days, and «never» means that this way it never fires.'],['R2','Inside the recording','The text and how they speak, that is names called out, introductions, masculine or feminine, formal or informal address, questions, your phrases. Here the chance baseline is guessing at random among the speakers of the recording.'],['R3','Between recordings and people','What is discussed, who you saw in the days before, same day, who appears with whom, where you were. For these the chance baseline is always the same, the person who appears most often, a weak baseline.']];
 const PG=D.proposte_giudizio||{};
 const RC=D.regole_in_calcolo||[];
 const MZ=D.misura||{};const PW=D.pesi||{};
 const pct=(a,b)=>b?Math.round(100*a/b):0;
 h+=`<section><h2>The judgment rules</h2><p class="sub" style="margin-bottom:14px">Many small rules, each looks at one thing only. The judgment puts them together and says who speaks and how sure it is.</p>`;
 // figure 1, the scheme
 const cntF=f=>RC.filter(r=>r.fronte===f).length, segF=f=>RC.filter(r=>r.fronte===f).reduce((a,r)=>a+(r.segnali||0),0);
 const SNC=PG.senza_nome_per_corsia||{};const nessuna=(PG.senza_nome||0)-(PG.senza_nome_con_proposta||0);
 const ESEMPI={R1:'who was invited, the call also recorded by Tactiq or Attio, the WhatsApp call',R2:'who is called by name, feminine phrasing such as «sono stata», who uses the formal address',R3:'who you see often, what is discussed, who appears with whom'};
 h+=`<div class="schema"><div class="col">`+FR.map(([f,tit])=>`<div class="box"><b>${e(tit)}</b><span>${n(cntF(f))} rules · ${n(segF(f))} signals</span><small>${e(ESEMPI[f])}</small></div>`).join('')+`</div>`+
  `<div class="freccia" aria-hidden="true"></div><div class="col"><div class="box centro"><b>The judgment</b><ul><li>gives each rule the weight it has learned</li><li>gives each name to a single speaker</li><li>says how sure it is, and the confidence is measured</li></ul></div></div><div class="freccia" aria-hidden="true"></div><div class="col">`+
  `<div class="box esito e1"><b>${n(SNC.AUTO)}</b><span>I could write them myself</span><small>above 95% with two different rule types. The challenge says it is not enough, for now they become questions</small></div>`+
  `<div class="box esito e2"><b>${n(SNC.CONFERMA)}</b><span>I ask you about them</span><small>the judgment is more than half sure</small></div>`+
  `<div class="box esito e3"><b>${n(SNC.CONTESTO)}</b><span>they stay a clue</span><small>too uncertain, waiting for more proof</small></div></div></div>`+
  `<p class="small muted" style="margin:8px 0 0">Numbers on the unnamed speakers, ${n(PG.senza_nome)} in all. For ${n(nessuna)} no rule finds a name.</p>`;
 // figura 2, gli speaker senza nome
 const SEG=[['I could write them myself',SNC.AUTO||0,'#17604f'],['I ask you about them',SNC.CONFERMA||0,'#3f9a80'],['they stay a clue',SNC.CONTESTO||0,'#a9d3c5'],['no name found',Math.max(nessuna,0),'#e6e3dc']];const totS=SEG.reduce((a,x)=>a+x[1],0)||1;
 h+=`<h3 class="fig">The unnamed speakers, where they end up</h3><div class="barra seg">`+SEG.map(([t,v,c])=>`<div title="${e(t)}, ${n(v)}" style="flex:${Math.max(v/totS,0.004)};background:${c}"></div>`).join('')+`</div><div class="leg">`+SEG.map(([t,v,c])=>`<span><i style="background:${c}"></i>${e(t)} <b>${n(v)}</b></span>`).join('')+`</div>`;
 // figura 3, quanto indovina
 const T=MZ.top1||{};
 if(T.freddo&&T.caldo){const RIGHE=[['Recordings never named',T.freddo],['With some name already in',T.caldo]];
  const BASE=MZ.banale||{};const barra=(v,c,chi,bs)=>{const p=pct(v[0],v[1]);return `<div class="hb" title="${chi}, ${p}%, ${n(v[0])} of ${n(v[1])}${bs?', baseline rule '+bs+'%':''}"><span style="width:${p}%;background:${c}"></span><em>${p}%</em><small>${n(v[0])} of ${n(v[1])}${bs?' · baseline '+bs+'%':''}</small></div>`};
  h+=`<h3 class="fig">How often it guesses</h3><p class="small muted" style="margin:0 0 8px">Test done on the names Plaud had already set, hidden from the judgment, ${n(MZ.voci)} speakers. The first proposal is shown.</p><div class="leg" style="margin:0 0 8px"><span><i style="background:#2a78d6"></i>when the voice is yours</span><span><i style="background:#9a4fb0"></i>when it is another person</span></div><div class="hbs">`+
  RIGHE.map(([t,x],i)=>`<div class="hbr"><div class="hbt">${e(t)}</div><div>${barra(x.owner,'#2a78d6','You',i===0?BASE.owner:0)}${barra(x.altri,'#9a4fb0','Other people',i===0?BASE.altri:0)}</div></div>`).join('')+`</div>`+
  `<p class="small muted" style="margin:6px 0 0">Your voices are almost half of those tested, ${n(T.freddo.owner[1])} of ${n(MZ.voci)}, and with you it is easier. The hard part is the other people in the recordings that were never named. «Baseline» is what a rule with no calculation would do, the voice that talks the most for you and the most frequent person for the others. Where the recent recordings no longer have Plaud's names, without those on the other people the precision drops.</p>`;}
 // figura 4, quando dice X ci prende
 const FA=MZ.fasce||{};
 if(FA.altri){const ORD=['sotto 0,50','0,50-0,70','0,70-0,90','0,90-0,95','0,95-1'];const NOMEF={'sotto 0,50':'below 50%','0,50-0,70':'50-70%','0,70-0,90':'70-90%','0,90-0,95':'90-95%','0,95-1':'above 95%'};
  const pannello=(chi,c,F)=>`<div><h4>${chi}</h4>`+ORD.map(k=>{const x=F[k]||{};if(!x.proposte)return `<div class="cal"><span class="ft">${NOMEF[k]}</span><span class="muted small">no case</span></div>`;const poco=x.proposte<10;
   return `<div class="cal" title="says ${x.fiducia_media}%, correct ${x.pct}%, ${n(x.giuste)} of ${n(x.proposte)}"><span class="ft">${NOMEF[k]}</span><div class="trk"><span class="ln" style="left:${Math.min(x.fiducia_media,x.pct)}%;width:${Math.abs(x.fiducia_media-x.pct)}%"></span><span class="dice" style="left:${x.fiducia_media}%"></span><span class="fa" style="left:${x.pct}%;background:${c}${poco?';opacity:.45':''}"></span></div><span class="small">${x.pct}%<small class="muted"> of ${n(x.proposte)}${poco?', few':''}</small></span></div>`}).join('')+`</div>`;
  h+=`<h3 class="fig">When it says it is sure, is it right?</h3><p class="small muted" style="margin:0 0 8px">The empty circle is how sure it says it is, the full dot is how often it was really right. If they match, the confidence is honest. Note, the challenge found that this test is done on the same months the judgment learns from, so it is more optimistic than the truth. It must be redone on months never seen.</p><div class="cals">`+pannello('The voice is yours','#2a78d6',FA.owner||{})+pannello('Another person','#9a4fb0',FA.altri)+`</div>`;}
 // figura 5, i pesi imparati
 const NG={'R1:calendario-titolo':'name in the event title','R1:calendario':'invited to the event','R1:email-invito':'email invite at that time','R1:email-rifiuto':'declined by email','R1:gemello':'the call also recorded by Tactiq, Attio or Meet','R1:slack':'Slack messages shortly before','R1:titolo':'name in the recording title','R1:wa-chiamata':'WhatsApp call at that time','R1:wa-durante':'was texting you on WhatsApp while you recorded','R1:wa-messaggi':'WhatsApp messages before and after','R2:chi_dice_il_nome':'whoever says a name is not that person','R2:file_spezzati':'same conversation in two files','R2:genere':'masculine or feminine does not match','R2:presentazione':'introduces themselves, «I am…»','R2:registro':'whoever uses the formal address is not you','R2:ruolo_owner':'asks more questions, talks more','R2:owner_testo':'your phrases, they call you by name','R2:terza_persona_assente':'spoken of in the third person','R2:vocativo':'called by name','R3:copresenza':'appears with the same people','R3:finestra':'outside the period when they appear','R3:luogo':'same city, if it is rare','R3:quota':'how much they usually talk','R3:rete':'heard in the 14 days before','R3:stesso-giorno':'named the same day','R3:tema':'their topics are discussed','R3:titolo':'title almost the same as another','e_owner':'signals that the voice is yours'};
 const PR=Object.entries(PW).map(([k,v])=>{const [f,g,d]=k.split(':');const nm=NG[g?f+':'+g:k]||k;return {k,nm:(d==='contro'&&g==='gemello')?'the call transcript contradicts it':nm,f,w:v.presenza,nv:v.voci_di_addestramento}}).filter(x=>typeof x.w==='number').sort((a,b)=>b.w-a.w);
 if(PR.length){const mx=Math.max(...PR.map(x=>Math.abs(x.w)))||1;const FN={R1:'sources',R2:'text',R3:'cross-checks'};
  h+=`<h3 class="fig">How much each rule group weighs</h3><p class="small muted" style="margin:0 0 8px">Weights learned by the judgment on its own. To the right it pushes toward a name, to the left it pushes away. Light means learned on fewer than 30 cases, so still uncertain.</p><div class="leg" style="margin:0 0 6px"><span><i style="background:#1f8a70"></i>pushes toward the name</span><span><i style="background:#c46a1c"></i>pushes away from the name</span></div><div class="pesi">`+
  PR.map(x=>{const w=Math.abs(x.w)/mx*50;const poco=x.nv!=null&&x.nv<30;return `<div class="pr" title="${e(x.nm)}, weight ${String(x.w.toFixed(2))}, ${x.nv!=null?'learned on '+n(x.nv)+' cases':'learned on all voices'}"><span class="pn">${e(x.nm)}<small>${FN[x.f]||''}</small></span><div class="pb"><span class="z"></span><span class="b" style="${x.w>=0?`left:50%`:`left:${50-w}%`};width:${w}%;background:${x.w>=0?'#1f8a70':'#c46a1c'}${poco?';opacity:.4':''}"></span></div></div>`}).join('')+`</div>`;}
 h+=`<details class="tutte"><summary>All the rules one by one, with the measures</summary><p class="small muted">To measure a rule, the names Plaud had already set are hidden and we look at how often the rule is right, that is it finds the name if it brings a name, and it removes whoever really was not there if it excludes. Next to it is how much would be guessed by chance. Plaud's names are only partly correct, so it is a check and not a proof. The real proof is your confirmations.</p><div class="kpis"><div class="kpi acc"><b>${n(RG.length)}</b><span>rules and subtypes found</span></div><div class="kpi"><b>${n(RC.length)}</b><span>run in the calculation</span></div><div class="kpi"><b>${n(conta('spenta'))}</b><span>off, measured and worthless</span></div><div class="kpi warn"><b>${n(conta('da sbloccare'))}</b><span>waiting for a datum or a choice from you</span></div></div>`;

 const forza=r=>{if(r.filtro)return 'always excludes';const p=r.peso;if(p==null)return 'does not weigh yet';const a=Math.abs(p);const l=a>=1.5?'strong':a>=0.7?'medium':a>=0.2?'weak':'almost nothing';return (p<0&&a>=0.2?'against, ':'')+l};
 if(RC.length){h+=`<h3 style="margin-top:18px">The ${RC.length} rules running now</h3><p class="small muted" style="margin:0 0 6px">These are the ones that passed the measure and that the calculation actually uses. The weight was learned by the calculation on its own, from the names already set, and it changes with each confirmation of yours. Rules similar to each other count only once.</p>`;
  for(const [f,tit] of FR){const rr=RC.filter(r=>r.fronte===f);if(!rr.length)continue;
   h+=`<details${f==='R1'?' open':''}><summary>${e(tit)} · ${rr.length} rules</summary><table class="resp"><thead><tr><th>Rule</th><th>What it does</th><th class="n">Recordings</th><th>Learned weight</th></tr></thead><tbody>`+
   rr.map(r=>`<tr><td><b>${e(r.nome)}</b><div class="ind">${e(r.famiglia)}${r.sottotipo&&r.sottotipo!==r.nome?' · '+e(r.sottotipo):''}</div></td><td class="small">${e(EFF[r.direzione==='a_favore'?'a favore':r.direzione]||r.direzione)} ${e(DOVE[r.tipo]||'')}</td><td class="n">${n(r.registrazioni)}</td><td class="small">${e(forza(r))}</td></tr>`).join('')+`</tbody></table></details>`;}
  h+=`<h3 style="margin-top:18px">All the measured rules, including the ones that are off</h3><p class="small muted" style="margin:0 0 6px">Here the estimate column says how much each rule was worth measured on its own, before the calculation learned. The learned weight is the one in the table above, where similar rules count only once.</p>`;}
 for(const [f,tit,desc] of FR){const rr=RG.filter(r=>r.fronte===f);if(!rr.length)continue;
  const fam={};rr.forEach(r=>{(fam[r.famiglia]=fam[r.famiglia]||[]).push(r)});
  h+=`<h3 style="margin-top:18px">${e(tit)} <span class="muted small">· ${rr.length} rules</span></h3><p class="small muted" style="margin:0 0 6px">${e(desc)}</p>`;
  for(const [k,lista] of Object.entries(fam)){const att=lista.filter(r=>r.stato==='attiva').length;const best=Math.max(...lista.filter(r=>r.stato==='attiva').map(r=>(r.argento||{}).pct||0),0);
   h+=`<details><summary>${e(k)} · ${lista.length} ${lista.length>1?'rules':'rule'}, ${att} useful${best?`, the best is right ${best}% of the time`:''}</summary><table class="resp"><thead><tr><th>Rule</th><th>What it does</th><th class="n">Recordings</th><th class="n">Correct</th><th class="n">By chance</th><th class="n">Starting estimate</th><th>Status</th></tr></thead><tbody>`+
   lista.map(r=>{const a=r.argento||{};const pw=r.forza;return `<tr${r.stato==='spenta'?' style="color:var(--soft)"':''}><td><b>${e(r.regola)}</b><div class="ind">${e(r.sottotipo)}</div></td><td class="small">${e(EFF[r.direzione]||r.direzione)} ${e(DOVE[r.tipo]||'')}</td><td class="n">${r.registrazioni!=null?n(r.registrazioni):''}</td><td class="n">${a.su?`${a.pct}%<div class="ind">${n(a.giusti)} of ${n(a.su)}</div>`:''}</td><td class="n">${r.caso_pct==null?'':r.caso_pct===0?'never':String(r.caso_pct)+'%'}</td><td class="n">${pw!=null?Math.round(pw*100)+'%':''}</td><td class="small">${e(STATO[r.stato]||r.stato)}${r.stato_perche?`<div class="ind">${e(r.stato_perche)}</div>`:''}</td></tr>`}).join('')+`</tbody></table></details>`;}}
 h+=`</details>`;
 const SB=RG.filter(r=>r.stato==='da sbloccare'&&r.fronte==='-');
 if(SB.length)h+=`<h3 class="fig">Ready rules waiting for a datum</h3><div class="sblocchi">${SB.map(r=>`<div class="sb"><b>${e(r.regola)}</b><span>${e(r.sottotipo)}</span><small>${e(r.stato_perche)}</small></div>`).join('')}</div>`;
 if((D.indizi||[]).length)h+=`<details><summary>How much your answers weigh, the earlier calculation</summary><p class="small muted">Every time you tell me «it's him» or «it's not him», the rules that pointed to that name gain or lose weight. Today it rests on few verifications, so it is a signal. It becomes a measure with the batch below, chosen at random.</p><table class="resp"><thead><tr><th>Clue</th><th class="n">Weight</th><th class="n">Correct</th><th class="n">Wrong</th><th>Starting point</th></tr></thead><tbody>`+
 D.indizi.map(i=>`<tr><td><b>${e(i.indizio)}</b></td><td class="n">${Math.round(i.punteggio*100)}%</td><td class="n">${i.giusti}</td><td class="n">${i.sbagliati}</td><td class="small muted">${Math.round(i.partenza*100)}%, ${e(i.perche_partenza)}</td></tr>`).join('')+`</tbody></table>`+
 `<p class="small muted" style="margin-top:10px">With these weights, of the names present: ${Object.entries(D.fiducia||{}).map(([k,v])=>`${n(v)} with confidence ${k}`).join(', ')}.</p></details>`;
 h+=`</section>`;}
const LV=(D.lotto||{}).voci||[];
if(LV.length){const BL=[['tua voce','Is this your voice?','Answer yes or no.'],['seconda voce','Is this your voice too?','You are already on another voice from the same recording. Yes or no.'],['altre persone','Who is speaking?','Choose 1, 2 or 3, or write the right name.'],['etichetta Plaud','Plaud set this name. Is it right?','It tells us how often Plaud is wrong. Yes or no.']];
 const fatte=LV.filter(v=>v.risposta).length;
 h+=`<section id="lotto"><h2>The ${LV.length} verifications</h2><p>Chosen from the judgment's proposals, by confidence band. Each answer teaches the judgment the true names and says from which threshold it will be able to write on its own. The recordings that are too long are left out; they must first be cut and reprocessed.</p>`+
 `<div class="kpis">${kpi(fatte+' of '+LV.length,'answers given',fatte?'acc':'')}${BL.map(([b,t])=>kpi(LV.filter(v=>v.blocco===b).length,t)).join('')}</div>`+
 `<p class="small muted" style="margin-top:10px">Open the link, go to the minute, listen. Reply to me in chat with the number and the answer, many at once too. For example «3 yes», «7 no, it's Marco Rossi», «28 2», «12 wasn't there», «15 mixed voice», «20 don't know».</p>`;
 for(const [b,t,come] of BL){const vv=LV.filter(v=>v.blocco===b);if(!vv.length)continue;
  h+=`<h3 class="fig">${e(t)} <span class="muted small">· ${vv.length}</span></h3><p class="small muted" style="margin:0 0 6px">${e(come)}</p><table class="resp"><thead><tr><th class="n">N</th><th>Recording</th><th>${b==='altre persone'?'Choices':'Name'}</th><th>Phrase</th></tr></thead><tbody>`+
  vv.map(v=>`<tr${v.risposta?' style="background:#f3faf7"':''}><td class="n">${v.n}</td><td><a href="${v.link}" target="_blank">${e((v.titolo||'').slice(0,70))}</a><div class="ind">${data((v.inizio||'').slice(0,10))} · minute ${e(v.minuto||'0:00')} · speaks ${v.minuti_voce>=1?Math.round(v.minuti_voce)+' min':'less than a minute'} · sure at ${Math.round((v.fiducia||0)*100)}%</div></td><td>${b==='altre persone'&&(v.scelte||[]).length?v.scelte.map((x,i)=>`<div><b>${i+1}</b> ${e(x)}</div>`).join(''):`<b>${e(v.nome_proposto)}</b>`}${(v.prove||[]).length?`<div class="ind">${e(v.prove[0])}</div>`:''}${v.risposta?`<div class="ind"><b>answer</b> ${e(v.risposta)}</div>`:''}</td><td class="small">«${e(v.frase)}»</td></tr>`).join('')+`</tbody></table>`;}
 h+=`</section>`;}
// solidità
const L=D.solidita.livelli;const totMin=Object.values(L).reduce((a,b)=>a+b.minuti,0)||1;
const SPIEGA={"confermato":"you said it yourself","solido":"two independent proofs (calendar, text, agents with a quote, voice)","una prova":"a single proof","solo nome":"the name is there, no proof","sospetto":"a signal against, for example the same name on several speakers","smentito":"you said it's not him","senza nome":"Speaker 1, 2, 3"};
h+=`<section><h2>How solid the names are</h2><div class="barra">`+Object.entries(L).map(([k,v])=>`<div title="${k}: ${n(v.minuti)} min" style="width:${100*v.minuti/totMin}%;background:${COL[k]}"></div>`).join('')+`</div>`+
 `<div class="leg">`+Object.entries(L).map(([k,v])=>`<span><i style="background:${COL[k]};border:1px solid #d8d4ca"></i>${k}: ${n(v.voci)} speaker, ${ore(v.minuti)}</span>`).join('')+`</div>`+
 `<table style="margin-top:14px"><tbody>`+Object.keys(L).map(k=>`<tr><td><span class="pill" style="background:${COL[k]};color:${['confermato','smentito'].includes(k)?'#fff':'#333'}">${k}</span></td><td class="muted small">${SPIEGA[k]}</td></tr>`).join('')+`</tbody></table>`+
 `<p class="small muted">The truthfulness is not a measure today: you verified ${D.veridicita.voci_verificate_da_owner} speakers, ${D.veridicita.giuste} correct and ${D.veridicita.sbagliate} wrong, and they were cases noticed because something did not add up. It becomes a measure with at least 50 verifications chosen at random.</p></section>`;
// per mese
const mesi=D.per_mese;
h+=`<section><h2>Month by month</h2><p class="small muted">Grey bar: minutes without a name. Green bar: minutes with a solid name. Any recent drop may be due to a change of transcription service.</p><div class="mesi">`+
 mesi.map(m=>`<span>${m.mese.slice(5)}/${m.mese.slice(2,4)}</span><div class="mb"><span style="width:${m.pct_senza_nome}%;background:#c9c4b8"></span></div><span class="small">${m.pct_senza_nome}%</span>`+
 `<span></span><div class="mb" style="height:8px"><span style="width:${m.pct_solidi}%;background:var(--acc)"></span></div><span class="small muted">${m.pct_solidi}%</span>`).join('')+`</div>`+
 `<details><summary>The month table</summary><table class="resp"><thead><tr><th>Month</th><th class="n">Recordings</th><th class="n">Hours</th><th class="n">With no name at all</th><th class="n">Minutes without a name</th><th class="n">In the knowledge base</th></tr></thead><tbody>`+
 [...(D.per_mese_prima||[]),...mesi].map(m=>`<tr><td>${m.mese}</td><td class="n">${n(m.registrazioni)}</td><td class="n">${m.ore}</td><td class="n">${n(m.senza_nessun_nome)}</td><td class="n">${n(m.minuti_senza_nome)} (${m.pct_senza_nome}%)</td><td class="n">${n(m.nel_kb)}</td></tr>`).join('')+`</tbody></table></details></section>`;
// da dove si parte
h+=`<section><h2>Where we start with the names</h2><p class="small muted">The unnamed speakers split by the proofs we already have. We begin at the top: where the proofs are good the name becomes solid, the rest improves one step at a time.</p><table class="resp"><thead><tr><th>Group</th><th>What we have</th><th class="n">Speaker</th><th class="n">Hours</th></tr></thead><tbody>`+
 (D.piano_nomi||[]).map(g=>`<tr><td><b>${e(g.gruppo)}</b></td><td class="small muted">${e(g.come)}</td><td class="n">${n(g.voci)}</td><td class="n">${n(g.ore)}</td></tr>`).join('')+`</tbody></table></section>`;
// the longest without names
h+=`<section><h2>The longest conversations without names</h2><p class="small muted">${n(D.mancano.length)} recordings have at least one unnamed speaker. In ${n(D.mancano_con_indizi)} we already have a clue: calendar invitees or a name said in the text. We start from there. In ${n(D.nomi.registrazioni_una_voce_sola)} (${n(D.nomi.ore_una_voce_sola)} hours) Plaud put everything on a single speaker. There the voices must first be separated, then named.</p>`+
 `<div class="ctl"><input id="q" placeholder="Search title, event, name…"><label><input type="checkbox" id="ci"> only with clues</label><label><input type="checkbox" id="fk"> only outside the knowledge base</label></div>`+
 `<table class="resp" id="tm"><thead><tr><th>When</th><th>Recording</th><th class="n">Without a name</th><th>Context</th></tr></thead><tbody></tbody></table><p id="piu" class="small"></p></section>`;
// outside KB
h+=`<section><h2>Where the facts are missing</h2><p>The knowledge base has the facts of ${n(D.kb.registrazioni_con_fatti)} recordings, the last one from ${data(D.kb.ultima_registrazione_nel_kb)}. ${n(D.kb.registrazioni_fuori)} are missing, ${n(D.kb.ore_fuori)} hours. The longest:</p>`+
 `<table class="resp"><thead><tr><th>When</th><th>Recording</th><th class="n">Duration</th><th class="n">Without a name</th><th>Context</th></tr></thead><tbody>`+
 D.kb.lunghe.slice(0,25).map(m=>`<tr><td>${data(m.d)}</td><td><a href="${link(m.id)}" target="_blank">${e(m.t)}</a></td><td class="n">${ore(m.dur)}</td><td class="n">${ore(m.sn)}</td><td class="small">${ctx(m)}</td></tr>`).join('')+`</tbody></table></section>`;
// contesto
const C=D.contesto;
h+=`<section><h2>The context we have</h2><div class="kpis">`+kpi(n(C.con_evento),'recordings with a calendar event at that time')+kpi(n(C.con_invitati),'with invitees we know')+kpi(n(C.in_call),'in a call (link in the event)')+kpi(n(C.di_persona||0),'in person (physical place, no call)')+kpi(n(C.con_luogo),'with a place in the event')+`</div>`+
 `<p class="small muted" style="margin-top:10px">Recorded with: `+Object.entries(C.per_tipo||{}).filter(([k])=>!/^\d+$/.test(k)).map(([k,v])=>`${k} ${n(v)}`).join(' · ')+`. Plaud does not give the place: we reconstruct it from calendar, time zone, text and locations.</p></section>`;
// activities
h+=`<section><h2>What we are doing</h2><table class="resp"><tbody>`+(D.attivita||[]).map(a=>`<tr><td>${stato(a.stato)}</td><td>${e(a.cosa)}${a.esito?`<div class="small muted">${e(a.esito)}</div>`:''}</td></tr>`).join('')+`</tbody></table></section>`;
h+=`<section><h2>How it is measured</h2><details><summary>The rules of the measures</summary><ul class="small">
<li>A speaker is a «Speaker N» of a recording. Its name is the label that weighs the most in minutes.</li>
<li>Independent proofs: an invitee to the calendar event at that time with that name; the text that calls that speaker by name or where they introduce themselves; the name written by our agents with a quote; Plaud's owner voice for you.</li>
<li>Signals against: the same name on several speakers of the same recording, the text that calls the speaker by another name.</li>
<li>Your truths (correct, it's not him) are kept in a separate ledger and win over everything.</li>
<li>The facts in the knowledge base are matched to the recording even when the file changed name.</li></ul></details></section>`;
document.getElementById('app').innerHTML=h;
function ctx(m){const p=[];if(m.ev)p.push(e(m.ev));if(m.inv)p.push(m.inv+' invitees');if(m.call)p.push('call');if(m.dp)p.push('in person');if(m.luogo)p.push(e(m.luogo));if(m.ind&&m.ind.length)p.push('in the text: '+m.ind.map(e).join(', '));return p.join(' · ')||'<span class="muted">no clue</span>'}
const tb=document.querySelector('#tm tbody');let lim=40;
function disegna(){const q=document.getElementById('q').value.toLowerCase(),ci=document.getElementById('ci').checked,fk=document.getElementById('fk').checked;
 const r=D.mancano.filter(m=>(!ci||m.inv||(m.ind&&m.ind.length))&&(!fk||!m.kb)&&(!q||(m.t+' '+m.ev+' '+(m.ind||[]).join(' ')).toLowerCase().includes(q)));
 tb.innerHTML=r.slice(0,lim).map(m=>`<tr><td>${data(m.d)} ${m.o}</td><td><a href="${link(m.id)}" target="_blank">${e(m.t)}</a><div class="ind">${m.uno?'<b>a single speaker</b>, Plaud did not separate the speakers':`${m.vs} unnamed speakers of ${m.v}`} · ${ore(m.dur)}${m.kb?'':' · outside the knowledge base'}</div></td><td class="n">${ore(m.sn)}</td><td class="small">${ctx(m)}</td></tr>`).join('');
 document.getElementById('piu').innerHTML=r.length>lim?`<a href="#" id="altre">Show ${Math.min(80,r.length-lim)} more (of ${n(r.length)})</a>`:`${n(r.length)} recordings`;
 const a=document.getElementById('altre');if(a)a.onclick=ev=>{ev.preventDefault();lim+=80;disegna()}}
['q','ci','fk'].forEach(i=>document.getElementById(i).addEventListener('input',()=>{lim=40;disegna()}));disegna();
</script></body></html>"""


def main() -> int:
    q = json.loads((QUADRO / "quadro.json").read_text())
    dati = json.dumps(compatta(q), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out = QUADRO / "pagina"
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(PAGINA.replace("__DATI__", dati))
    print(out / "index.html", round((out / "index.html").stat().st_size / 1024), "KB")
    return 0


if __name__ == "__main__":
    _ = html
    raise SystemExit(main())
