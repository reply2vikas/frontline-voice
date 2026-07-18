/* Frontline Voice — view layer.
   No framework and no dependencies: the whole interface is a few hundred lines,
   and a build step would add weight without adding capability. All state lives
   in one object; every render is a pure function of it. */

const ISSUES = [["gate_closed","Gate closed"],["line_static","Line not moving"],
  ["transit_delay","Transport delay"],["lost_fans","People lost"],
  ["fan_distress","Someone in distress"],["heat_distress","Heat distress"],
  ["out_of_scope_request","Asked something I can't do"],["no_information","No information"]];
const MOODS = [["calm","Calm"],["confused","Confused"],["frustrated","Frustrated"],
  ["hostile","Hostile"],["distressed","Distressed"],["exhausted","Exhausted"]];

const OK_STATES = ["OPEN"];
const WARN_STATES = ["CONGESTED","STATIC_QUEUE","SURGE","TRANSIT_DELAY"];

const state = { venue:"MIA", zone:null, issue:"gate_closed", mood:"frustrated", venues:[], vstate:null };

const $ = id => document.getElementById(id);
const esc = s => { const d=document.createElement("div"); d.textContent = s==null?"":String(s); return d.innerHTML; };
const say = msg => { $("srstatus").textContent = msg; };

/* ---------- tabs ---------------------------------------------------------- */
const TABS = ["guide","map","log"];

function selectTab(name, focus=true){
  TABS.forEach(t=>{
    const tab=$("tab-"+t), panel=$("panel-"+t), on = t===name;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    panel.hidden = !on;
  });
  if(focus) $("tab-"+name).focus();
  if(name==="map") loadVenueState();
  if(name==="log") loadLog();
}

function wireTabs(){
  TABS.forEach((t,i)=>{
    const tab=$("tab-"+t);
    tab.onclick = ()=> selectTab(t,false);
    tab.onkeydown = e => {
      const map={ArrowRight:1,ArrowLeft:-1,Home:"first",End:"last"};
      if(!(e.key in map)) return;
      e.preventDefault();
      const v=map[e.key];
      const idx = v==="first"?0 : v==="last"?TABS.length-1 : (i+v+TABS.length)%TABS.length;
      selectTab(TABS[idx]);
    };
  });
}

/* ---------- form ---------------------------------------------------------- */
function taps(el, items, key){
  el.innerHTML="";
  items.forEach(([v,label])=>{
    const b=document.createElement("button");
    b.type="button"; b.className="tap"; b.textContent=label;
    b.setAttribute("aria-pressed", String(state[key]===v));
    b.onclick=()=>{ state[key]=v; taps(el,items,key); };
    el.appendChild(b);
  });
}

function fillZones(){
  const v = state.venues.find(x=>x.id===state.venue);
  const sel=$("zone"); sel.innerHTML="";
  v.zones.filter(z=>z.kind==="gate"||z.kind==="transit").forEach(z=>{
    const o=document.createElement("option"); o.value=z.id; o.textContent=z.name; sel.appendChild(o);
  });
  state.zone = sel.value;
  sel.onchange = e => state.zone = e.target.value;
  $("feedNote").textContent = `Ops feed simulated · heat risk: ${v.heat_risk}`;
}

/* ---------- venue map ----------------------------------------------------- */
function statusColour(s){
  if(OK_STATES.includes(s)) return "var(--ok)";
  if(WARN_STATES.includes(s)) return "var(--warn)";
  return "var(--crit)";
}

function buildMap(vs){
  const W=680, H=420, cx=W/2, cy=H/2;
  const gates = vs.zones.filter(z=>z.kind==="gate");
  const outer = vs.zones.filter(z=>z.kind!=="gate");
  let svg = `<svg class="map" viewBox="0 0 ${W} ${H}" role="img" aria-label="Schematic map of ${esc(vs.venue_name)} showing live zone status">`;
  svg += `<ellipse cx="${cx}" cy="${cy}" rx="118" ry="74" fill="#123021" stroke="var(--line)" stroke-width="2"/>`;
  svg += `<text x="${cx}" y="${cy+4}" text-anchor="middle" fill="var(--dim)">${esc(vs.venue_name)}</text>`;

  gates.forEach((z,i)=>{
    const a = (i/gates.length)*2*Math.PI - Math.PI/2;
    const x = cx + Math.cos(a)*205 - 46, y = cy + Math.sin(a)*140 - 21;
    svg += `<g class="zone" tabindex="0" role="button" data-zone="${esc(z.id)}"
       aria-label="${esc(z.name)}, status ${esc(z.status.toLowerCase().replace(/_/g,' '))}, ${z.load_pct} percent load. Select this gate.">
      <rect x="${x}" y="${y}" width="92" height="42" rx="9" fill="var(--panel2)" stroke="${statusColour(z.status)}" stroke-width="3"/>
      <text x="${x+46}" y="${y+18}" text-anchor="middle" fill="var(--ink)">${esc(z.name.split(" (")[0])}</text>
      <text x="${x+46}" y="${y+33}" text-anchor="middle" fill="${statusColour(z.status)}">${z.load_pct}%</text>
    </g>`;
  });

  outer.forEach((z,i)=>{
    const a = (i/outer.length)*2*Math.PI + Math.PI/4;
    const x = cx + Math.cos(a)*300, y = cy + Math.sin(a)*185;
    svg += `<g role="img" aria-label="${esc(z.name)}">
      <circle cx="${x}" cy="${y}" r="13" fill="var(--panel2)" stroke="var(--accent)" stroke-width="2"/>
      <text x="${x}" y="${y+4}" text-anchor="middle" fill="var(--accent)">${esc(z.kind[0].toUpperCase())}</text>
    </g>`;
  });

  return svg + "</svg>";
}

function renderTelemetry(vs){
  const s=vs.summary;
  const items=[["Gates open",`${s.gates_open}/${s.gates_total}`],["Impaired",s.gates_impaired],
    ["Peak load",`${s.peak_load_pct}%`],["Heat risk",vs.heat_risk]];
  $("telemetry").innerHTML = items.map(([k,v])=>
    `<div class="metric"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");
}

function renderZoneTable(vs){
  $("zonetable").querySelector("tbody").innerHTML = vs.zones.map(z=>
    `<tr><th scope="row">${esc(z.name)}</th><td>${esc(z.kind)}</td>
     <td style="color:${statusColour(z.status)}">${esc(z.status.replace(/_/g," "))}</td>
     <td>${z.capacity?z.load_pct+"%":"—"}</td></tr>`).join("");
}

async function loadVenueState(){
  try{
    const vs = await (await fetch(`/api/venue-state/${state.venue}`)).json();
    state.vstate = vs;
    $("map").innerHTML = buildMap(vs);
    renderTelemetry(vs); renderZoneTable(vs);
    $("map").querySelectorAll("[data-zone]").forEach(g=>{
      const pick = ()=>{ state.zone=g.dataset.zone; $("zone").value=state.zone;
        say(`${g.dataset.zone} selected. Switching to the volunteer view.`); selectTab("guide"); };
      g.onclick = pick;
      g.onkeydown = e => { if(e.key==="Enter"||e.key===" "){ e.preventDefault(); pick(); } };
    });
  }catch(err){ $("map").innerHTML = `<p class="muted">Could not load venue state: ${esc(err.message)}</p>`; }
}

/* ---------- operations log ------------------------------------------------ */
async function loadLog(){
  try{
    const rows = await (await fetch("/api/audit?limit=25")).json();
    const body = $("logtable").querySelector("tbody");
    body.innerHTML = rows.length ? rows.map(r=>
      `<tr><th scope="row">${esc(new Date(r.ts).toLocaleTimeString())}</th>
       <td>${esc(r.venue_id)}</td><td>${esc(r.zone_id)}</td><td>${esc(r.sop_id)}</td>
       <td>${esc(r.severity)}</td><td>${esc(r.engine)}</td>
       <td>${r.escalated?"Yes":"No"}</td></tr>`).join("")
      : `<tr><td colspan="7" class="muted">No decisions recorded yet.</td></tr>`;
  }catch(err){ say("Could not load the operations log."); }
}

/* ---------- guidance ------------------------------------------------------ */
function feedFor(){
  const m = {gate_closed:{status:"CLOSED",reason:"scanner_failure",hold_time_min:30},
    line_static:{status:"STATIC_QUEUE"}, transit_delay:{status:"TRANSIT_DELAY"},
    heat_distress:{status:"HEAT_WARNING"}};
  return m[state.issue] ? [{zone_id:state.zone, ...m[state.issue]}] : [];
}

async function submit(e){
  e.preventDefault();
  const out=$("out"), go=$("go");
  out.setAttribute("aria-busy","true"); go.disabled=true;
  out.innerHTML='<p class="muted">Resolving…</p>'; say("Working on guidance.");
  const body={report:{venue_id:state.venue, zone_id:state.zone, issue:state.issue,
    crowd_mood:state.mood, phase:"pre_kickoff",
    static_for_min: state.issue==="line_static"?15:0}, feed:feedFor()};
  try{
    const r=await fetch("/api/decide",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    if(!r.ok) throw new Error("Request failed ("+r.status+")");
    const d=await r.json(); render(d);
    say(`Guidance ready. ${d.output.recommendation}`);
  }catch(err){
    out.innerHTML=`<div class="card"><p class="rec">Could not get guidance</p><p class="muted">${esc(err.message)}</p></div>`;
    say("Could not get guidance.");
  }finally{ out.setAttribute("aria-busy","false"); go.disabled=false; }
}

function render(d){
  const sev=d.facts.severity;
  const cls = sev==="critical"?"crit":sev==="elevated"?"elev":"ok";
  let h=`<div class="card">
    <div class="badges">
      <span class="badge ${cls}">${esc(sev)}</span>
      <span class="badge">${esc(d.facts.sop_id)}</span>
      <span class="badge">confidence: ${esc(d.output.confidence)}</span>
      <span class="badge">${d.engine==="genai"?"AI-phrased":"offline template"}</span>
      <span class="badge">${d.latency_ms} ms</span>
      ${d.facts.escalate?'<span class="badge crit">escalate</span>':""}
    </div>
    <p class="rec">${esc(d.output.recommendation)}</p>
    <h2>Why</h2><ul>${d.output.rationale.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>`;
  if(d.output.alternatives.length){
    h+=`<h2>Alternatives</h2><ul>`+d.output.alternatives.map(a=>
      `<li><b>${esc(a.action)}</b><br><span class="muted">${esc(a.tradeoff)}</span></li>`).join("")+`</ul>`;
  }
  if(d.facts.escalate_reasons.length){
    h+=`<h2>Escalation</h2><p class="muted">${d.facts.escalate_reasons.map(esc).join("; ")}</p>`;
  }
  h+=`</div><div class="card"><h2>Say this</h2>`;
  d.output.announcements.forEach(a=>{
    h+=`<div class="ann"><b>${esc(a.lang.toUpperCase())}</b><p lang="${esc(a.lang)}">${esc(a.text)}</p></div>`;
  });
  h+=`</div>`;
  if(d.citations.length){
    h+=`<div class="card"><h2>Grounded in documented incidents</h2>`;
    d.citations.forEach(c=>{
      h+=`<div class="cite"><b>${esc(c.title)}</b><span class="tier">${esc(c.evidence_tier.replace(/_/g," "))}</span>
        <div class="muted">${esc(c.event)} · ${esc(c.venue)} · ${esc(c.date)}</div>
        <a href="${esc(c.sources[0].url)}" target="_blank" rel="noopener noreferrer">${esc(c.sources[0].publisher)}</a></div>`;
    });
    h+=`</div>`;
  }
  $("out").innerHTML=h;
}

/* ---------- init ---------------------------------------------------------- */
async function init(){
  state.venues = await (await fetch("/api/venues")).json();
  const vs=$("venue");
  state.venues.forEach(v=>{
    const o=document.createElement("option"); o.value=v.id; o.textContent=`${v.name} — ${v.city}`; vs.appendChild(o);
  });
  vs.onchange = e => { state.venue=e.target.value; fillZones(); state.vstate=null; };
  fillZones();
  taps($("issue"), ISSUES, "issue");
  taps($("mood"), MOODS, "mood");
  wireTabs();
  $("f").onsubmit = submit;
}
init();
