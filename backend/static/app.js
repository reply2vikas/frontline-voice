const ISSUES = [["gate_closed","Gate closed"],["line_static","Line not moving"],
  ["transit_delay","Transport delay"],["lost_fans","People lost"],
  ["fan_distress","Someone in distress"],["heat_distress","Heat distress"],
  ["out_of_scope_request","Asked something I can't do"],["no_information","No information"]];
const MOODS = [["calm","Calm"],["confused","Confused"],["frustrated","Frustrated"],
  ["hostile","Hostile"],["distressed","Distressed"],["exhausted","Exhausted"]];

const state = {venue:"MIA", zone:null, issue:"gate_closed", mood:"frustrated"};
let VENUES = [];

function taps(el, items, key){
  el.innerHTML = "";
  items.forEach(([v,label])=>{
    const b=document.createElement("button");
    b.type="button"; b.className="tap"; b.textContent=label;
    b.setAttribute("aria-pressed", String(state[key]===v));
    b.onclick=()=>{ state[key]=v; taps(el,items,key); };
    el.appendChild(b);
  });
}

function fillZones(){
  const v = VENUES.find(x=>x.id===state.venue);
  const sel = document.getElementById("zone");
  sel.innerHTML="";
  v.zones.filter(z=>z.kind==="gate"||z.kind==="transit").forEach(z=>{
    const o=document.createElement("option"); o.value=z.id; o.textContent=z.name; sel.appendChild(o);
  });
  state.zone = sel.value;
  sel.onchange = e => state.zone = e.target.value;
  document.getElementById("feedNote").textContent =
    `Ops feed simulated · heat risk: ${v.heat_risk}`;
}

async function init(){
  VENUES = await (await fetch("/api/venues")).json();
  const vs=document.getElementById("venue");
  VENUES.forEach(v=>{const o=document.createElement("option");o.value=v.id;o.textContent=`${v.name} — ${v.city}`;vs.appendChild(o);});
  vs.onchange=e=>{state.venue=e.target.value;fillZones();};
  fillZones();
  taps(document.getElementById("issue"), ISSUES, "issue");
  taps(document.getElementById("mood"), MOODS, "mood");
}

function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}

document.getElementById("f").onsubmit = async (e)=>{
  e.preventDefault();
  const out=document.getElementById("out");
  out.setAttribute("aria-busy","true");
  out.innerHTML='<p class="muted">Resolving…</p>';
  const feed = state.issue==="gate_closed" ? [{zone_id:state.zone,status:"CLOSED",reason:"scanner_failure",hold_time_min:30}]
             : state.issue==="line_static" ? [{zone_id:state.zone,status:"STATIC_QUEUE"}]
             : state.issue==="transit_delay" ? [{zone_id:state.zone,status:"TRANSIT_DELAY"}]
             : state.issue==="heat_distress" ? [{zone_id:state.zone,status:"HEAT_WARNING"}] : [];
  const body={report:{venue_id:state.venue,zone_id:state.zone,issue:state.issue,
    crowd_mood:state.mood,phase:"pre_kickoff",static_for_min:state.issue==="line_static"?15:0}, feed};
  try{
    const r=await fetch("/api/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    if(!r.ok) throw new Error("Request failed ("+r.status+")");
    render(await r.json());
  }catch(err){
    out.innerHTML='<div class="card"><p class="rec">Could not get guidance</p><p class="muted">'+esc(err.message)+'</p></div>';
  }finally{ out.setAttribute("aria-busy","false"); }
};

function render(d){
  const sev=d.facts.severity;
  const sevClass = sev==="critical"?"crit":sev==="elevated"?"elev":"ok";
  let h=`<div class="card">
    <div class="badges">
      <span class="badge ${sevClass}">${esc(sev)}</span>
      <span class="badge">${esc(d.facts.sop_id)}</span>
      <span class="badge">confidence: ${esc(d.output.confidence)}</span>
      <span class="badge">${d.engine==="genai"?"AI-phrased":"offline template"}</span>
      ${d.facts.escalate?'<span class="badge crit">escalate</span>':''}
    </div>
    <p class="rec">${esc(d.output.recommendation)}</p>
    <h2 style="font-size:.9rem;color:var(--dim);margin:.8rem 0 .2rem">Why</h2>
    <ul>${d.output.rationale.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>`;

  if(d.output.alternatives.length){
    h+=`<h2 style="font-size:.9rem;color:var(--dim);margin:.9rem 0 .2rem">Alternatives</h2><ul>`+
      d.output.alternatives.map(a=>`<li><b>${esc(a.action)}</b><br><span class="muted">${esc(a.tradeoff)}</span></li>`).join("")+`</ul>`;
  }
  if(d.facts.escalate_reasons.length){
    h+=`<p class="muted" style="margin-top:.8rem">Escalation: ${d.facts.escalate_reasons.map(esc).join("; ")}</p>`;
  }
  h+=`</div><div class="card"><h2 style="font-size:.9rem;color:var(--dim);margin:0 0 .3rem">Say this</h2>`;
  d.output.announcements.forEach(a=>{
    h+=`<div class="ann"><b>${a.lang.toUpperCase()}</b><p>${esc(a.text)}</p></div>`;
  });
  h+=`</div>`;
  if(d.citations.length){
    h+=`<div class="card"><h2 style="font-size:.9rem;color:var(--dim);margin:0 0 .4rem">Grounded in documented incidents</h2>`;
    d.citations.forEach(c=>{
      h+=`<div class="cite"><b>${esc(c.title)}</b><span class="tier">${esc(c.evidence_tier.replace("_"," "))}</span>
        <div class="muted">${esc(c.event)} · ${esc(c.venue)} · ${esc(c.date)}</div>
        <a href="${esc(c.sources[0].url)}" target="_blank" rel="noopener noreferrer">${esc(c.sources[0].publisher)}</a></div>`;
    });
    h+=`</div>`;
  }
  document.getElementById("out").innerHTML=h;
}
init();
