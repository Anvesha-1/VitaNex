try{
const st=document.createElement('style');st.textContent="\n.lx-ctl{display:flex;gap:10px;align-items:center;margin-left:auto;margin-right:14px}\n.lx-src{font-size:12px;font-weight:600;color:var(--mut);background:#f1f5fa;border-radius:99px;padding:6px 12px;white-space:nowrap}\n.lx-ecg{background:#0a1630;border-color:#0a1630;color:#e8eefc;margin-bottom:18px;position:relative;padding:16px 20px}\n.lx-ecg .cap{color:#7d92c4}.lx-ecg canvas{width:100%;height:120px;display:block;margin-top:6px}\n.lx-eh{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}\n.lx-eh b{font-size:20px;font-weight:600}.lx-eh small{display:block;color:#7d92c4;font-size:12px;margin-top:2px}\n.lx-nums{display:flex;gap:26px;text-align:right}.lx-nums div{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;color:#3dffa0;line-height:1}\n.lx-nums div:last-child{color:#6db4ff}.lx-nums span{display:block;font-size:11px;font-weight:600;letter-spacing:.14em;color:#7d92c4;margin-top:4px}\n.lx-vs{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:14px}\n.lx-t{border:1px solid var(--line);border-radius:14px;padding:12px 14px;transition:background .5s,border-color .5s}\n.lx-t.bad{border-color:#f3b4b9;background:#fff5f5}.lx-t svg{height:56px!important;width:100%;display:block}\n.lx-h{display:flex;justify-content:space-between;align-items:baseline;font-size:12.5px;color:var(--mut);font-weight:600}\n.lx-h b{font-size:22px;color:var(--ink);font-variant-numeric:tabular-nums}.lx-h i{font-size:11px;font-style:normal;color:var(--mut);font-weight:500}\n.lx-beds{display:grid;grid-template-columns:repeat(auto-fill,minmax(40px,1fr));gap:7px;margin-top:14px;max-height:250px;overflow:auto;padding:3px}\n.lx-b{border:0;border-radius:9px;aspect-ratio:1;font-size:11px;font-weight:700;background:#e5f7ef;color:#0d6b47;transition:background 1s}\n.lx-b.watch{background:#ffe6d3;color:#9a4210}.lx-b.high{background:var(--red);color:#fff;animation:lxp 1.6s infinite}\n.lx-b.s{outline:2px solid var(--ink);outline-offset:2px}@keyframes lxp{50%{box-shadow:0 0 0 5px rgba(229,48,59,.22)}}\n.lx-leg{display:flex;gap:14px;font-size:12px;color:var(--mut);margin-top:12px}.lx-leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}\n@media(prefers-reduced-motion:reduce){.lx-b.high{animation:none}}@media(max-width:820px){.lx-src{display:none}}\n";document.head.appendChild(st);

(()=>{
const DATA_LABEL="Replaying de-identified patient data · PhysioNet 2019 sepsis format"; /* edit if your source differs */
S.speed=.33; /* one ICU hour every 3 seconds (was every second) */
const COL={HR:"#e5303b",O2Sat:"#0a5fd8",Resp:"#12a26b",MAP:"#8b5cf6"},LB={HR:"Heart rate",O2Sat:"SpO₂",Resp:"Resp. rate",MAP:"MAP"},H={};
let fv={},asked={},lastHr=null,sound=false,lastAct=0,tc="#3dffa0";

/* top bar: data-source badge, speed control, alarm sound */
const ctl=document.createElement("div");ctl.className="lx-ctl";
ctl.innerHTML=`<span class="lx-src">${DATA_LABEL}</span><div class="tabs" id="lx-sp"><button data-s=".17">Slow</button><button data-s=".33" class="on">Normal</button><button data-s=".67">Fast</button></div><button class="btn alt" id="lx-snd" style="padding:6px 12px">Sound off</button>`;
$("#sys").before(ctl);
$("#lx-sp").onclick=e=>{const b=e.target.closest("button");if(!b)return;S.speed=+b.dataset.s;document.querySelectorAll("#lx-sp button").forEach(x=>x.classList.toggle("on",x===b))};
$("#lx-snd").onclick=()=>{sound=!sound;$("#lx-snd").textContent=sound?"Sound on":"Sound off";if(sound)beep()};

/* live ECG card (full width, above the queue) */
const two=document.querySelector("#v-risk .two");
const ec=document.createElement("div");ec.className="card lx-ecg";
ec.innerHTML=`<div class="lx-eh"><div><div class="cap">LIVE RHYTHM</div><b id="lx-who"></b><small>Trace animated from the patient's measured heart rate</small></div><div class="lx-nums"><div id="lx-hr">–<span>HR BPM</span></div><div id="lx-o2">–<span>SPO₂ %</span></div></div></div><canvas id="lx-ecg"></canvas>`;
two.before(ec);

/* vitals stream + bed map */
const row=document.createElement("div");row.className="two";row.style.marginTop="18px";
row.innerHTML=`<div class="card"><div class="cap">LIVE VITALS STREAM</div><h2 id="lx-vh" style="font-size:20px;font-weight:600;margin-top:4px"></h2><div class="lx-vs" id="lx-vs"></div></div><div class="card"><div class="cap">WARD BED MAP</div><h2 style="font-size:20px;font-weight:600;margin-top:4px">Every patient at a glance</h2><div style="color:var(--mut);font-size:12.5px;margin-top:2px">Select a bed to open that patient.</div><div class="lx-beds" id="lx-beds"></div><div class="lx-leg"><span><i style="background:#e5f7ef"></i>Stable</span><span><i style="background:#ffe6d3"></i>Watch</span><span><i style="background:var(--red)"></i>Critical</span></div></div>`;
two.after(row);
$("#lx-beds").onclick=e=>{const b=e.target.closest("[data-p]");if(b){S.sel=b.dataset.p;S.edit=false;renderList();renderSel();extras()}};
$("#list").addEventListener("click",()=>setTimeout(extras,50));

function extras(){
  const v=S.vit||{},hr=+$("#hour").value;let cur=v[S.sel]&&v[S.sel].HR!=null?v[S.sel]:(fv[S.sel]||{});
  if(cur.HR==null){const key=S.sel+"@"+hr;if(!asked[key]){asked[key]=1;fetch("/api/patient/"+encodeURIComponent(S.sel)+"?hour="+hr).then(r=>r.json()).then(j=>{if(j.vitals&&j.vitals.HR!=null){fv[S.sel]=j.vitals;extras()}}).catch(()=>{})}}
  if(hr!==lastHr){ if(hr===1)for(const p in H)delete H[p]; lastHr=hr;
    for(const p in v){const h=H[p]=H[p]||{};for(const k in LB)if(v[p][k]!=null)h[k]=(h[k]||[]).concat(v[p][k]).slice(-40)} }
  $("#lx-who").textContent="Patient "+S.sel;$("#lx-vh").textContent="Patient "+S.sel;
  $("#lx-hr").firstChild.textContent=cur.HR??"–";$("#lx-o2").firstChild.textContent=cur.O2Sat??"–";
  const r=(S.board||[]).find(x=>x.patient===S.sel);tc=r&&cat(r.risk)==="high"?"#ff6b76":"#3dffa0";
  $("#lx-vs").innerHTML=Object.keys(LB).map(k=>{const a=(H[S.sel]||{})[k]||[],[lo,hi]=rng(S.sel,k),bad=isOut(S.sel,k,cur[k]);
    return `<div class="lx-t${bad?" bad":""}"><div class="lx-h"><span>${LB[k]}</span><b>${cur[k]??"–"}<i> ${VL[k][1]}</i></b></div>${a.length>1?line(a,COL[k],Math.min(...a,lo)-2,Math.max(...a,hi)+2,[lo,hi]):'<small style="color:var(--mut)">Collecting readings…</small>'}</div>`}).join("");
  $("#lx-beds").innerHTML=(S.board||[]).slice(0,120).map(r=>{const c=cat(r.risk);return `<button class="lx-b ${c}${r.patient===S.sel?" s":""}" data-p="${esc(r.patient)}" title="Patient ${esc(r.patient)} · ${pct(r.risk)}% ${CL[c][0]}">${esc(r.patient.slice(-2))}</button>`}).join("");
  const act=S.alarms.filter(a=>!a.ack).length;if(act>lastAct&&sound)beep();lastAct=act;
}
const _l=window.load;window.load=async function(...a){const r=await _l.apply(this,a);extras();return r};

function beep(){try{const a=new(window.AudioContext||webkitAudioContext)();[0,.22].forEach(d=>{const o=a.createOscillator(),g=a.createGain(),t=a.currentTime+d;o.frequency.value=880;o.connect(g);g.connect(a.destination);g.gain.setValueAtTime(.12,t);g.gain.exponentialRampToValueAtTime(.001,t+.18);o.start(t);o.stop(t+.2)})}catch(e){}}

/* ECG renderer: time-based sweep, so speed does not depend on the display refresh rate */
const cv=$("#lx-ecg"),cx=cv.getContext("2d"),G=(x,m,s,a)=>a*Math.exp(-((x-m)**2)/(2*s*s)),wv=(t,h)=>{const q=Math.max(.014,.014*h/75),tc=.385+.25*Math.sqrt(h/60);return G(t,.18,.035,.12)+G(t,.36,q*.9,-.12)+G(t,.385,q,1)+G(t,.41,q,-.25)+G(t,tc,.06,h>110?.16:.22)};
let ph=0,acc=0,buf=[],t0=performance.now();
(function frame(now){const dp=devicePixelRatio||1,W=cv.clientWidth,Hh=cv.clientHeight,dt=Math.min(.1,(now-t0)/1e3);t0=now;
  if(W&&cv.width!==Math.round(W*dp)){cv.width=W*dp;cv.height=Hh*dp}
  if(S.live){const vv=(S.vit||{})[S.sel],hr=(vv&&vv.HR!=null?vv.HR:(fv[S.sel]||{}).HR)||0;acc+=dt*60;const n=Math.floor(acc);acc-=n;for(let i=0;i<n;i++){ph=(ph+hr*(1+.02*Math.sin(now/1500))/3600)%1;buf.push(hr?wv(ph,hr)+(Math.random()-.5)*.025:(Math.random()-.5)*.02)}}
  while(buf.length>W)buf.shift();cx.setTransform(dp,0,0,dp,0,0);cx.clearRect(0,0,W,Hh);
  cx.strokeStyle="rgba(125,146,196,.14)";cx.lineWidth=1;for(let x=0;x<W;x+=22){cx.beginPath();cx.moveTo(x,0);cx.lineTo(x,Hh);cx.stroke()}for(let y=0;y<Hh;y+=22){cx.beginPath();cx.moveTo(0,y);cx.lineTo(W,y);cx.stroke()}
  cx.beginPath();buf.forEach((v,i)=>{const y=Hh*.78-v*Hh*.6;i?cx.lineTo(i,y):cx.moveTo(i,y)});cx.strokeStyle=tc;cx.lineWidth=2;cx.shadowColor=tc;cx.shadowBlur=8;cx.stroke();cx.shadowBlur=0;
  if(buf.length){cx.beginPath();cx.arc(buf.length-1,Hh*.78-buf.at(-1)*Hh*.6,4,0,7);cx.fillStyle="#fff";cx.fill()}
  requestAnimationFrame(frame)})(t0);
extras();
})();

}catch(e){console.error('VitaNex live add-on failed:',e)}

/* VitaNex visual polish. Colours and effects only: no layout, position, size, animation or script changes. */
try{const st=document.createElement("style");st.textContent=`
body{-webkit-font-smoothing:antialiased}
::selection{background:#cfe0ff}
.card{box-shadow:0 1px 2px rgba(13,31,60,.04),0 10px 28px -16px rgba(13,31,60,.14);transition:box-shadow .25s}
.card:hover{box-shadow:0 1px 2px rgba(13,31,60,.05),0 16px 34px -16px rgba(13,31,60,.2)}
.nav{transition:background .2s,color .2s}.nav.on{box-shadow:inset 3px 0 0 var(--blue)}
.btn{transition:background .2s,color .2s,box-shadow .2s}.btn:hover{box-shadow:0 6px 14px -8px rgba(10,95,216,.55)}
.row{transition:background .2s}.row:hover .av,.row.sel .av{background:#d6e6fd;color:var(--blue)}
.vt div{transition:border-color .25s,background .4s}.vt div:hover{border-color:#b9cdee}
.list,.feed{scrollbar-width:thin;scrollbar-color:#c5d3ea transparent}
.list::-webkit-scrollbar,.feed::-webkit-scrollbar{width:8px}
.list::-webkit-scrollbar-thumb,.feed::-webkit-scrollbar-thumb{background:#c5d3ea;border-radius:9px}`;
document.head.appendChild(st)}catch(e){console.error("VitaNex polish failed:",e)}