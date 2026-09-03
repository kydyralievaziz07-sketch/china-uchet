"use strict";
/* Китай · учёт — логика интерфейса, v2 (этапы 1–2) */

/* ═══════════════════ утилиты ═══════════════════ */
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const CUR={USD:"$",CNY:"¥",KGS:"с"};
const ST_RU={new:"Не отправлен",shipping:"В пути",arrived:"Прибыл",cancelled:"Отменён"};
const KIND_RU={prepay:"Аванс",final:"Доплата",refund:"Возврат"};
const KINDS=["prepay","final","refund"];
const METHODS=["Наличные","Перевод на карту","WeChat","Alipay","Через посредника","Другое"];
const MON=["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
const MONTH=["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const reduced=()=>matchMedia("(prefers-reduced-motion: reduce)").matches;
const isMobile=()=>matchMedia("(max-width: 820px)").matches;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let UID=0;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function fmtN(v){return (Math.round((+v||0)*100)/100).toLocaleString("ru-RU",{maximumFractionDigits:2}).replace(/,/g,".").replace(/ /g," ")}
function money(v,cur){cur=cur||"USD";const n=+v||0;const s=fmtN(Math.abs(n));const b=cur==="KGS"?s+" с":(CUR[cur]||"")+s;return (n<-0.004?"−":"")+b}
function dRu(d){if(!d)return"";const[y,m,dd]=d.split("-");return dd+"."+m+"."+y}
function dShort(d){if(!d)return"";const[y,m,dd]=d.split("-");return +dd+" "+MON[+m-1]}
function ymRu(ym){const[y,m]=ym.split("-");return MONTH[+m-1]+" "+y}
function todayISO(){const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")}
function plural(n,a,b,c){n=Math.abs(n)%100;const n1=n%10;if(n>10&&n<20)return c;if(n1>1&&n1<5)return b;if(n1===1)return a;return c}
async function api(path,opts={}){
  const r=await fetch(path,{headers:{"Content-Type":"application/json"},...opts,body:opts.body?JSON.stringify(opts.body):undefined});
  if(r.status===401){showLogin();throw new Error("Нужен вход")}
  const j=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(j.error||"Ошибка "+r.status);
  return j;
}
/* иконки */
const I={
  edit:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>',
  copy:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>',
  pay:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="2.5"/><circle cx="12" cy="12" r="2.6"/><path d="M6 12h.01M18 12h.01"/></svg>',
  chev:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  down:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 21h16"/></svg>',
};
const ILL='<svg class="ill" viewBox="0 0 96 96" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 62c14-22 30-22 44-10s22 8 24-6" stroke-dasharray="4 5" opacity=".45"/><path d="M30 44l18-8 18 8-18 8z" stroke="#6C8CFF"/><path d="M30 44v14l18 8 18-8V44" stroke="#6C8CFF"/><path d="M48 52v14" stroke="#6C8CFF"/><circle cx="14" cy="62" r="3" fill="#FFB65C" stroke="none"/><circle cx="82" cy="46" r="3" fill="#57E39B" stroke="none"/></svg>';

/* ═══════════════════ тосты, окна ═══════════════════ */
function toast(msg,cls="info"){
  const t=document.createElement("div");t.className="toast "+cls;
  const life=cls==="err"?4200:2600;t.style.setProperty("--life",life+"ms");
  t.innerHTML=`<span class="ic">${cls==="ok"?"✓":cls==="err"?"!":"i"}</span><span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(()=>{t.classList.add("out");t.addEventListener("animationend",()=>t.remove(),{once:true});setTimeout(()=>t.remove(),500)},life);
}
function openModal(html,cls){
  const m=$("#modal");m.className="modal "+(cls||"");m.innerHTML=html;
  $("#modal-ov").classList.add("show");
  $$("#modal [data-x]").forEach(b=>b.onclick=closeModal);
  setTimeout(()=>{if(!isMobile())m.querySelector("[autofocus]")?.focus()},120);
}
function closeModal(){$("#modal-ov").classList.remove("show")}
$("#modal-ov").addEventListener("mousedown",e=>{if(e.target.id==="modal-ov")closeModal()});
function confirmBox(title,text,danger){
  return new Promise(res=>{
    openModal(`<div class="mh"><h2>${esc(title)}</h2><button class="x" data-x>×</button></div>
      <div class="mb" style="color:var(--muted);font-size:14px;line-height:1.5">${esc(text)}</div>
      <div class="mf"><button class="ghost" data-x>Отмена</button>
      <button class="pill ${danger?"danger":""}" id="cf-ok" autofocus>${danger?"Удалить":"Да"}</button></div>`,"small");
    $("#cf-ok").onclick=()=>{closeModal();res(true)};
    $$("#modal [data-x]").forEach(b=>b.onclick=()=>{closeModal();res(false)});
  });
}
async function withBusy(btn,fn){
  if(!btn||btn.disabled)return false;
  btn.disabled=true;btn.classList.add("busy");
  try{await fn();btn.classList.remove("busy");btn.classList.add("done");await sleep(reduced()?0:300);return true}
  catch(e){toast(e.message,"err");return false}
  finally{btn.disabled=false;btn.classList.remove("busy","done")}
}

/* ═══════════════════ анимации и графика ═══════════════════ */
function kick(root){ /* запускает переходы ширин/высот/дуг после отрисовки */
  root=root||document;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    root.querySelectorAll("[data-w]").forEach(el=>el.style.setProperty("--w",el.dataset.w+"%"));
    root.querySelectorAll("[data-h]").forEach(el=>el.style.setProperty("--h",el.dataset.h+"%"));
    root.querySelectorAll(".dn[data-len]").forEach(el=>el.style.strokeDasharray=el.dataset.len+" 100");
    root.querySelectorAll(".fgc[data-v]").forEach(el=>el.style.strokeDashoffset=String(100-(+el.dataset.v)));
  }));
}
function counter(el,to,cur,from){
  from=from||0;
  if(reduced()){el.textContent=money(to,cur);return}
  const t0=performance.now(),dur=from?750:1150;
  function step(t){const p=Math.min((t-t0)/dur,1),e=1-Math.pow(1-p,3);
    el.textContent=money(from+(to-from)*e,cur);
    if(p<1)requestAnimationFrame(step);else{el.classList.add("bump");setTimeout(()=>el.classList.remove("bump"),600)}}
  requestAnimationFrame(step);
}
function sparkSvg(ser,color,w,h){
  w=w||78;h=h||30;
  if(!ser||ser.length<2)return"";
  const mx=Math.max(...ser),mn=Math.min(...ser),rng=(mx-mn)||1;
  const pts=ser.map((v,i)=>[+(2+i/(ser.length-1)*(w-4)).toFixed(1),+(h-4-(v-mn)/rng*(h-9)).toFixed(1)]);
  let d="M"+pts[0].join(" ");
  for(let i=1;i<pts.length;i++){const a=pts[i-1],b=pts[i];const cx=((a[0]+b[0])/2).toFixed(1);d+=` C${cx} ${a[1]} ${cx} ${b[1]} ${b[0]} ${b[1]}`}
  const last=pts[pts.length-1],id="sg"+(++UID);
  const area=d+` L${last[0]} ${h} L${pts[0][0]} ${h} Z`;
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="none" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".38"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path class="sp-a" d="${area}" fill="url(#${id})"/>
    <path class="sp-l" d="${d}" stroke="${color}" stroke-width="2" stroke-linecap="round" pathLength="100"/>
    <circle class="sp-e" cx="${last[0]}" cy="${last[1]}" r="2.8" fill="${color}"/></svg>`;
}
function deltaHtml(ser){
  if(!ser||ser.length<2)return"";
  const a=ser[ser.length-2]||0,b=ser[ser.length-1]||0;
  if(!b)return""; // текущий месяц ещё пустой — сравнивать не с чем
  if(!a)return`<span class="delta up" title="В прошлом месяце было пусто">новое</span>`;
  const p=Math.round((b-a)/a*100);
  if(!p)return`<span class="delta" title="Как в прошлом месяце">= прошлый</span>`;
  return`<span class="delta ${p>0?"up":"down"}" title="К прошлому месяцу">${p>0?"▲":"▼"} ${Math.abs(p)}%</span>`;
}
function ringSvg(pct,color,size,sw){
  size=size||64;sw=sw||6;const r=(size-sw)/2,c=size/2;
  return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle class="bgc" cx="${c}" cy="${c}" r="${r}" stroke-width="${sw}"/>
    <circle class="fgc" cx="${c}" cy="${c}" r="${r}" stroke="${color}" stroke-width="${sw}" pathLength="100" data-v="${Math.round(Math.min(100,Math.max(0,pct)))}"/></svg>`;
}
function donutSvg(parts,size,sw){
  size=size||120;sw=sw||12;const r=(size-sw)/2,c=size/2;const tot=parts.reduce((a,p)=>a+p.v,0)||1;let off=0;
  return `<svg class="donut" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle class="bgc" cx="${c}" cy="${c}" r="${r}" stroke-width="${sw}"/>
    ${parts.map(p=>{const len=p.v/tot*100,gap=parts.length>1?1.5:0;
      const s=`<circle class="dn" cx="${c}" cy="${c}" r="${r}" stroke="${p.color}" stroke-width="${sw}" pathLength="100" data-len="${Math.max(0,len-gap).toFixed(2)}" style="stroke-dashoffset:${(-off).toFixed(2)}"><title>${esc(p.l)}: ${money(p.v)}</title></circle>`;
      off+=len;return s}).join("")}</svg>`;
}
/* прожектор под курсором, параллакс ауры, рябь на кнопках */
let auraTick=false;
document.addEventListener("pointermove",e=>{
  const el=e.target.closest?.(".spot");
  if(el){const r=el.getBoundingClientRect();el.style.setProperty("--mx",(e.clientX-r.left)+"px");el.style.setProperty("--my",(e.clientY-r.top)+"px")}
  if(!auraTick&&!reduced()&&!isMobile()){auraTick=true;requestAnimationFrame(()=>{auraTick=false;const a=$("#aura");if(!a)return;
    a.style.setProperty("--px",((e.clientX/innerWidth)-.5)*-24+"px");a.style.setProperty("--py",((e.clientY/innerHeight)-.5)*-18+"px")})}
},{passive:true});
document.addEventListener("pointerdown",e=>{
  const b=e.target.closest(".pill,.ghost,.tab");if(!b||reduced())return;
  const r=b.getBoundingClientRect(),d=Math.max(r.width,r.height)*1.7;
  const s=document.createElement("i");s.className="rip";
  s.style.cssText=`width:${d}px;height:${d}px;left:${e.clientX-r.left-d/2}px;top:${e.clientY-r.top-d/2}px`;
  b.appendChild(s);setTimeout(()=>s.remove(),700);
});
document.addEventListener("click",e=>{const g=e.target.closest("[data-go]");if(g){e.preventDefault();go(g.dataset.go)}});

/* скелеты */
const skKpis=()=>[0,1,2,3].map(i=>`<div class="glass kpi" style="--i:${i}"><span class="sk" style="width:90px;height:10px"></span><span class="sk" style="width:130px;height:26px;margin:12px 0 8px"></span><span class="sk" style="width:150px;height:10px"></span></div>`).join("");
const skRows=n=>Array.from({length:n},()=>`<div class="ship sk-row"><span class="sk" style="width:38%;height:15px"></span><span class="sk" style="width:24%;height:11px;margin-top:8px"></span><span class="sk" style="width:100%;height:3px;margin-top:20px"></span></div>`).join("");
const skAside=()=>[0,1,2].map(()=>`<div class="glass card"><span class="sk" style="width:120px;height:10px;margin-bottom:14px"></span><span class="sk" style="width:100%;height:12px;margin-bottom:10px"></span><span class="sk" style="width:80%;height:12px"></span></div>`).join("");

/* ═══════════════════ состояние ═══════════════════ */
const S={user:null,section:"ships",tab:"",q:"",stores:[],partners:[],ships:null,sum:null,pays:null,
  pay:{kind:"",supplier:"",from:"",to:"",q:""},kpiPrev:{}};

/* ═══════════════════ вход ═══════════════════ */
function showLogin(){$("#login-ov").classList.add("show");$("#app").classList.add("off")}
$("#login-form").onsubmit=async e=>{
  e.preventDefault();$("#l-err").textContent="";const btn=$("#l-btn");btn.classList.add("busy");
  try{
    const r=await api("/api/login",{method:"POST",body:{login:$("#l-login").value,password:$("#l-pass").value}});
    S.user=r.user;$("#login-ov").classList.remove("show");$("#app").classList.remove("off");go(S.section);
  }catch(err){
    $("#l-err").textContent=err.message;
    const c=$(".login-card");c.classList.remove("shake");void c.offsetWidth;c.classList.add("shake");
  }finally{btn.classList.remove("busy")}
};

/* ═══════════════════ навигация ═══════════════════ */
const RENDER={ships:renderShips,payments:renderPayments,partners:renderPartners,investors:renderInvestors,
  stores:renderStores,summary:renderSummary,settings:renderSettings};
let navSeq=0;
async function go(sec){
  if(!RENDER[sec])sec="ships";
  const seq=++navSeq;S.section=sec;history.replaceState(null,"","#"+sec);setRail(sec);hidePop();
  const m=$("#main");
  if(m.innerHTML&&!reduced()){m.classList.add("leave");await sleep(160);if(seq!==navSeq)return;m.classList.remove("leave")}
  window.scrollTo({top:0});
  try{await RENDER[sec]()}catch(e){if(e.message!=="Нужен вход")toast(e.message,"err")}
}
function setRail(sec){$$("#rail a").forEach(a=>a.classList.toggle("on",a.dataset.sec===sec));moveInd()}
function moveInd(){
  const a=$("#rail a.on"),ind=$("#rail-ind");if(!a||!ind)return;
  ind.style.transform=isMobile()?`translate(${a.offsetLeft+(a.offsetWidth-20)/2}px,0)`:`translate(0,${a.offsetTop+(a.offsetHeight-22)/2}px)`;
  requestAnimationFrame(()=>ind.classList.add("ready"));
}
addEventListener("resize",moveInd);
addEventListener("hashchange",()=>{const h=location.hash.replace("#","");if(RENDER[h]&&h!==S.section&&S.user)go(h)});
document.addEventListener("keydown",e=>{
  const typing=/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable;
  const modalOpen=$("#modal-ov").classList.contains("show");
  if(e.key==="Escape"){if(modalOpen)closeModal();hidePop();return}
  if((e.metaKey||e.ctrlKey)&&(e.key==="s"||e.key==="ы")){if(modalOpen){e.preventDefault();$("#modal [data-save]")?.click()}return}
  if(typing||modalOpen||e.metaKey||e.ctrlKey||e.altKey)return;
  if(e.key==="/"){e.preventDefault();($("#q")||$("#pq"))?.focus();return}
  if(/^[nт]$/i.test(e.key)){e.preventDefault();
    if(S.section==="payments")payModal();else if(S.section==="partners")partnerModal();else if(S.section==="stores")storeModal();else shipModal();return}
  if(/^[1-6]$/.test(e.key))go(["ships","payments","partners","investors","stores","summary"][+e.key-1]);
});
function headHtml(title,sub,right){
  return `<header class="top"><div><h1>${title}</h1><div class="sub" id="hd-sub">${sub||""}</div></div><div class="hd-r">${right||""}</div></header>`;
}
function avatarHtml(){return `<div class="glass avatar" title="${esc(S.user?.name||"")}" data-go="settings">${esc((S.user?.name||"А")[0])}</div>`}

/* ═══════════════════ справочные данные ═══════════════════ */
async function loadRefs(){[S.stores,S.partners]=await Promise.all([api("/api/stores"),api("/api/partners")])}
const activeStores=()=>S.stores.filter(s=>s.active);
const activeSuppliers=()=>S.partners.filter(p=>p.active&&p.is_supplier);

/* ═══════════════════ ПАРТИИ ═══════════════════ */
async function renderShips(){
  $("#main").innerHTML=`<div class="view">${headHtml("Партии <span>из Китая</span>",`<span class="sk" style="width:240px;height:12px;margin-top:6px"></span>`,`
    <div class="srch-w"><span class="srch-ic">${I.search}</span><input class="srch" id="q" placeholder="Поиск: товар, трек, поставщик" value="${esc(S.q)}"><kbd>/</kbd></div>
    <button class="pill" id="add-ship">${I.plus}<span>Новая партия</span></button>${avatarHtml()}`)}
    <div class="kpis" id="kpis">${skKpis()}</div>
    <div class="grid"><div class="glass panel" style="--i:1">
      <div class="ph"><h2>Партии в работе</h2>
        <div class="tabs" id="tabs">${[["","Все"],["shipping","В пути"],["new","Не отправлены"],["arrived","Прибыли"],["cancelled","Отменены"]]
          .map(([v,l])=>`<div class="tab${S.tab===v?" on":""}" data-v="${v}">${l}</div>`).join("")}</div></div>
      <div id="ship-list">${skRows(3)}</div>
    </div><aside id="aside" style="--i:2">${skAside()}</aside></div></div>`;
  $("#add-ship").onclick=()=>shipModal();
  let qt;$("#q").oninput=e=>{clearTimeout(qt);qt=setTimeout(()=>{S.q=e.target.value;loadShips()},300)};
  $$("#tabs .tab").forEach(t=>t.onclick=()=>{S.tab=t.dataset.v;$$("#tabs .tab").forEach(x=>x.classList.toggle("on",x===t));loadShips()});
  await loadRefs();
  await Promise.all([loadShips(),loadSummaryUI()]);
}
async function loadShips(opts){
  opts=opts||{};
  const p=new URLSearchParams();if(S.tab)p.set("status",S.tab);if(S.q)p.set("q",S.q);
  const d=await api("/api/shipments?"+p);S.ships=d;
  const el=$("#ship-list");if(!el)return;
  const openIds=new Set($$("#ship-list .ship.open").map(x=>+x.dataset.id));
  if(!d.rows.length){
    el.innerHTML=`<div class="empty">${ILL}<b>${S.tab||S.q?"Ничего не найдено":"Партий пока нет"}</b>
      ${S.tab||S.q?"Попробуйте другой фильтр или запрос":"Создайте первую партию — это займёт минуту"}
      ${!S.tab&&!S.q?`<br><button class="pill" onclick="shipModal()">${I.plus}<span>Новая партия</span></button>`:""}</div>`;
  }else{
    el.innerHTML=d.rows.map((s,i)=>shipHtml(s,Math.min(i,10),openIds.has(s.id))).join("")+
     `<div class="ship" style="background:rgba(255,255,255,.03);--i:11"><div class="ship-top" style="cursor:default">
        <div class="who" style="font-size:13.5px;color:var(--muted)">Итого по фильтру: ${d.totals.count} парт. · ${d.totals.items} поз.</div>
        <div class="money"><b>${money(d.totals.amount)}</b><div class="m2">оплачено ${money(d.totals.paid)} · остаток ${money(d.totals.balance)}</div></div></div></div>`;
    bindShipActions();kick(el);
    if(opts.pop){const t=el.querySelector(`.ship[data-id="${opts.pop}"] .tag`);if(t)t.classList.add("pop")}
  }
  const sub=$("#hd-sub");
  if(sub){const live=d.rows.filter(s=>s.status==="shipping").length,n=new Date();
    sub.innerHTML=`${MONTH[n.getMonth()]} ${n.getFullYear()} · ${d.totals.count} ${plural(d.totals.count,"партия","партии","партий")}`+
      (live?` · <span class="live-dot"></span>${live} ${live===1?"едет":"едут"} прямо сейчас`:"")}
}
function routeHtml(s){
  if(s.status==="cancelled")return"";
  const origin=s.supplier_city||s.supplier_name.split("—")[0].trim();
  let p1=0,p2=0,n1="",n2="",n3="",f1=false,f2=false;
  if(s.status==="new"){n1="act"}
  else if(s.status==="arrived"){p1=100;p2=100;n1="done";n2="done";n3="fin"}
  else{ // в пути: прогресс по датам отправки и ожидания
    let pr=.35;
    if(s.sent_date&&s.eta_date){const a=new Date(s.sent_date),b=new Date(s.eta_date),t=new Date();pr=Math.min(.95,Math.max(.05,(t-a)/((b-a)||1)))}
    else if(s.sent_date){pr=Math.min(.9,.08+(s.days_transit||0)/22)}
    if(pr<.5){p1=pr*200;n1="done";n2="act";f1=true}
    else{p1=100;p2=(pr-.5)*200;n1="done";n2="done";n3="act";f2=true}
  }
  const dot=c=>({done:"done",act:"live",fin:"fin"})[c]||"";
  const seg=(w,flow)=>`<div class="seg${flow?" flow":""}"><i data-w="${w.toFixed(1)}"></i>${flow?`<span class="head" data-w="${w.toFixed(1)}"></span>`:""}</div>`;
  const node=(c,label)=>`<div class="node ${c==="act"?"act":c==="fin"?"fin":""}"><span class="dot ${dot(c)}"></span><span>${esc(label)}</span></div>`;
  return `<div class="route">${node(n1,origin)}${seg(p1,f1)}${node(n2,"Урумчи")}${seg(p2,f2)}${node(n3,"Бишкек")}</div>`;
}
function shipHtml(s,i,open){
  const chips=[];
  if(s.status==="shipping"&&s.days_transit!=null)chips.push(["в пути "+s.days_transit+" дн."]);
  if(s.status==="shipping"&&s.eta_date){const late=s.eta_date<todayISO();
    chips.push([late?"задержка — ждали "+dRu(s.eta_date):"ожидается "+dRu(s.eta_date),late?"warn":""])}
  if(s.status==="new")chips.push(["заказана "+dRu(s.date)]);
  if(s.status==="arrived"&&s.arrived_date)chips.push(["прибыла "+dRu(s.arrived_date),"ok"]);
  if(s.stores.length)chips.push(["магазин"+(s.stores.length>1?"ы":"")+" №"+s.stores.join(" · №")]);
  if(s.pay_mode==="auto")chips.push([s.payments.length+" "+plural(s.payments.length,"платёж","платежа","платежей"),"info"]);
  const pay=s.amount?Math.min(100,Math.max(0,s.paid/s.amount*100)):0,over=s.balance<-0.004;
  const m2=s.status==="cancelled"?"не считается":over?`переплата <span class="v-rose">${money(-s.balance,s.currency)}</span>`
    :s.balance<=0.004?`<span class="v-green">оплачено полностью</span>`
    :`оплачено ${money(s.paid,s.currency)} · остаток <span class="v-amber">${money(s.balance,s.currency)}</span>`;
  return `<div class="ship spot${open?" open":""}" data-id="${s.id}" style="--i:${i}">
    <div class="ship-top" data-open>
      <div><div class="who">${esc(s.supplier_name)} <span class="chev">${I.chev}</span></div>
        <div class="meta">${dRu(s.date)} · ${s.items.length} поз.${s.track?" · трек "+esc(s.track):""}</div></div>
      <button class="tag t-${s.status}" data-st title="Сменить статус">${ST_RU[s.status]}</button>
      <div class="money"><b>${money(s.amount,s.currency)}</b><div class="m2">${m2}</div></div>
      <div class="acts">
        <button class="mini-btn" data-pay title="Записать платёж">${I.pay}</button>
        <button class="mini-btn" data-edit title="Редактировать">${I.edit}</button>
        <button class="mini-btn" data-copy title="Дублировать">${I.copy}</button>
        <button class="mini-btn del" data-del title="Удалить">${I.trash}</button></div>
    </div>
    ${routeHtml(s)}
    ${chips.length?`<div class="chips">${chips.map(([t,c])=>`<span class="chip ${c||""}">${esc(t)}</span>`).join("")}</div>`:""}
    ${s.status!=="cancelled"&&s.amount?`<div class="paybar${over?" over":""}" title="Оплачено ${Math.round(pay)}%"><i data-w="${pay.toFixed(1)}"></i></div>`:""}
    <div class="ship-x"><div>
      <div class="items-tbl"><table>
        <tr><th>Магазин</th><th>Товар</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th></tr>
        ${s.items.map(it=>`<tr><td><span class="badge">№${esc(it.store_number)}</span></td><td>${esc(it.product)}</td>
          <td class="num">${it.qty?fmtN(it.qty)+" "+esc(it.unit||""):"—"}</td>
          <td class="num">${it.unit_price?money(it.unit_price,s.currency):"—"}</td>
          <td class="num"><b>${money(it.amount,s.currency)}</b></td></tr>`).join("")}
      </table></div>
      <div class="pays"><div class="pays-h"><span>Платежи по партии</span><button class="lnk" data-pay>+ Платёж</button></div>
        ${s.payments.length?s.payments.map(p=>`<div class="pay-line"><span class="d">${dRu(p.date)}</span>
            <span class="tag k-${p.kind}" style="cursor:default">${KIND_RU[p.kind]}</span>
            <span class="n">${esc([p.method,p.note].filter(Boolean).join(" · "))}</span>
            <b class="${p.kind==="refund"?"v-rose":""}">${p.kind==="refund"?"−":""}${money(p.amount,p.currency)}</b></div>`).join("")
          :`<div class="pay-line"><span class="empty-l">${s.paid?"Аванс "+money(s.paid,s.currency)+" введён вручную в карточке партии. Запишите первый платёж — дальше всё посчитается само.":"Платежей пока нет"}</span></div>`}
      </div>
    </div></div></div>`;
}
function bindShipActions(){
  $$("#ship-list .ship[data-id]").forEach(el=>{
    const id=+el.dataset.id,s=S.ships.rows.find(x=>x.id===id);if(!s)return;
    el.querySelector("[data-open]").onclick=e=>{if(e.target.closest("button"))return;el.classList.toggle("open")};
    el.querySelector("[data-edit]").onclick=()=>shipModal(s);
    el.querySelector("[data-copy]").onclick=()=>shipModal({...s,id:null,date:todayISO(),status:"new",sent_date:null,arrived_date:null,
      eta_date:null,track:"",prepaid:0,payments:[],pay_mode:"manual",paid:0});
    el.querySelectorAll("[data-pay]").forEach(b=>b.onclick=()=>payModal({supplier_id:s.supplier_id,shipment_id:s.id}));
    el.querySelector("[data-del]").onclick=async()=>{
      if(await confirmBox("Удалить партию?",`${s.supplier_name}, ${dRu(s.date)}, ${s.items.length} поз. на ${money(s.amount,s.currency)}. Партия будет скрыта из списков.`,true)){
        await api("/api/shipments/"+id,{method:"DELETE"});toast("Партия удалена","ok");loadShips();loadSummaryUI();loadRefs()}};
    el.querySelector("[data-st]").onclick=e=>{e.stopPropagation();statusPop(e.currentTarget,s)};
  });
}
function statusPop(btn,s){
  const pop=$("#st-pop");
  pop.innerHTML=Object.entries(ST_RU).map(([v,l])=>`<button class="tag t-${v}${v===s.status?" cur":""}" data-v="${v}">${l}</button>`).join("");
  const r=btn.getBoundingClientRect();
  pop.style.left=Math.min(r.left,innerWidth-190)+"px";pop.style.top=(r.bottom+scrollY+6)+"px";
  pop.classList.add("show");
  pop.querySelectorAll("[data-v]").forEach(b=>b.onclick=async()=>{
    hidePop();if(b.dataset.v===s.status)return;
    try{await api("/api/shipments/"+s.id,{method:"PATCH",body:{status:b.dataset.v}});
      toast("Статус: "+ST_RU[b.dataset.v],"ok");loadShips({pop:s.id});loadSummaryUI()}catch(e){toast(e.message,"err")}});
  setTimeout(()=>document.addEventListener("click",function h(e){if(!pop.contains(e.target)){hidePop();document.removeEventListener("click",h)}}),0);
}
function hidePop(){$("#st-pop").classList.remove("show")}

/* ═══════════════════ плитки и правая колонка ═══════════════════ */
function kpiHtml(list){
  return list.map(([l,v,c,dt,ser,col],i)=>`<div class="glass kpi spot" style="--i:${i}"><div class="lab">${l}</div>
    <div class="val ${c||""}" data-v="${v}" data-k="${esc(l)}">${money(0)}</div><div class="dt">${dt}</div>
    ${ser?`<div class="kpi-r">${sparkSvg(ser,col)}${deltaHtml(ser)}</div>`:""}</div>`).join("");
}
function runCounters(root){
  root.querySelectorAll(".val[data-v]").forEach(el=>{const k=el.dataset.k,to=+el.dataset.v;counter(el,to,undefined,S.kpiPrev[k]);S.kpiPrev[k]=to});
}
async function loadSummaryUI(){
  const d=await api("/api/summary");S.sum=d;const t=d.tiles,sr=d.series;
  const k=$("#kpis");if(!k)return;
  k.innerHTML=kpiHtml([
    ["Заказано",t.ordered,"",`${t.ordered_items} ${plural(t.ordered_items,"позиция","позиции","позиций")} · ${t.ordered_count} ${plural(t.ordered_count,"партия","партии","партий")}`,sr.ordered,"#6C8CFF"],
    ["Отдано поставщикам",t.paid,"v-cyan",t.ordered?Math.round(t.paid/t.ordered*100)+"% от суммы закупок":"—",sr.paid,"#3ED8D0"],
    ["Остаток к оплате",t.debt_total,"v-amber",t.debt_suppliers?`${t.debt_suppliers} ${plural(t.debt_suppliers,"поставщик ждёт","поставщика ждут","поставщиков ждут")} доплату`:"долгов нет",sr.balance,"#FFB65C"],
    ["Сейчас в пути",t.transit,"v-green",t.transit_count?`${t.transit_count} парт. · дольше всех ${t.transit_max_days} дн.`:"ничего не едет",sr.sent,"#57E39B"],
  ]);
  runCounters(k);
  const a=$("#aside");if(!a)return;
  a.innerHTML=asideHtml(d);kick(a);
}
function asideHtml(d){
  const t=d.tiles,mx=Math.max(...d.months.map(m=>m.total),1);
  return `
   <div class="glass card spot"><h3>Закупки по месяцам</h3>
     <div class="bars">${d.months.map((m,i)=>`<i ${i===6?'class="cur"':""} data-h="${Math.round(m.total/mx*100)}" title="${ymRu(m.ym)}: заказано ${money(m.total)}, оплачено ${money(m.paid)}"><b data-h="${m.total?Math.min(100,Math.round(m.paid/m.total*100)):0}"></b></i>`).join("")}</div>
     <div class="bl">${d.months.map(m=>`<span>${MON[+m.ym.slice(5)-1]}</span>`).join("")}</div>
     <div class="legend"><span><i style="background:#6C8CFF"></i>заказано</span><span><i style="background:rgba(87,227,155,.75)"></i>из них оплачено</span></div></div>
   <div class="glass card spot"><h3>Долги поставщикам</h3>
     ${d.debts.length?d.debts.map(([n,v])=>`<div class="stat"><span class="l">${esc(n)}</span><span class="v">${money(v)}</span></div>`).join("")
       +`<div class="stat tot"><span class="l">Итого</span><span class="v v-amber">${money(t.debt_total)}</span></div>`
       :'<div class="stat"><span class="l">Долгов нет 🎉</span></div>'}
     ${d.overpaid.map(([n,v])=>`<div class="stat"><span class="l">${esc(n)} — переплата</span><span class="v v-green">${money(v)}</span></div>`).join("")}</div>
   <div class="glass card spot"><h3>Ожидается прибытие</h3>
     ${d.arriving.length?d.arriving.map(x=>`<div class="stat"><span class="l">${esc(x.supplier)}</span>
        <span class="v ${x.eta&&x.eta<todayISO()?"v-amber":"v-green"}">${x.eta?dRu(x.eta):(x.days!=null?x.days+" дн. в пути":"—")}</span></div>`).join("")
       :'<div class="stat"><span class="l">Ничего не едет</span></div>'}</div>
   <div class="glass card spot"><h3>Последние платежи <button class="lnk" data-go="payments">все →</button></h3>
     ${d.recent_payments.length?d.recent_payments.slice(0,4).map(p=>`<div class="stat"><span class="l">${dShort(p.date)} · ${esc(p.supplier_name)}</span>
        <span class="v ${p.kind==="refund"?"v-rose":""}">${p.kind==="refund"?"−":""}${money(p.amount,p.currency)}</span></div>`).join("")
       :'<div class="stat"><span class="l">Платежей пока нет</span></div>'}</div>`;
}

/* ═══════════════════ окно партии ═══════════════════ */
let ITEMS=[];
function shipModal(s){
  const isNew=!s||!s.id;
  const sup=activeSuppliers();
  if(!sup.length&&isNew){toast("Сначала добавьте поставщика (раздел «Поставщики»)","err");return}
  if(!activeStores().length&&isNew){toast("Сначала добавьте магазин (раздел «Магазины»)","err");return}
  ITEMS=(s?.items||[{}]).map(i=>({...i}));if(!ITEMS.length)ITEMS=[{}];
  const auto=s?.pay_mode==="auto";
  openModal(`<div class="mh"><h2>${isNew?"Новая партия":"Партия — "+esc(s.supplier_name)}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c3"><label>Дата заказа</label><input type="date" id="f-date" value="${s?.date||todayISO()}"></div>
    <div class="fg c6"><label>Поставщик</label><select id="f-sup">
      ${sup.map(p=>`<option value="${p.id}" ${s?.supplier_id===p.id?"selected":""}>${esc(p.name)}</option>`).join("")}</select></div>
    <div class="fg c3"><label>Валюта</label><select id="f-cur">
      ${["USD","CNY","KGS"].map(c=>`<option ${((s?.currency)||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
    <div class="fg c3"><label>Статус</label><select id="f-st">
      ${Object.entries(ST_RU).map(([v,l])=>`<option value="${v}" ${((s?.status)||"new")===v?"selected":""}>${l}</option>`).join("")}</select></div>
    <div class="fg c3"><label>Отправлена</label><input type="date" id="f-sent" value="${s?.sent_date||""}"></div>
    <div class="fg c3"><label>Ожидается</label><input type="date" id="f-eta" value="${s?.eta_date||""}"></div>
    <div class="fg c3"><label>Прибыла</label><input type="date" id="f-arr" value="${s?.arrived_date||""}"></div>
    <div class="fg c6"><label>Трек / накладная</label><input id="f-track" value="${esc(s?.track||"")}" placeholder="SF7742019"></div>
    <div class="fg c3"><label>${auto?"Оплачено (по платежам)":"Аванс"}</label><input type="number" step="0.01" id="f-pre" value="${auto?s.paid:(s?.prepaid||"")}" placeholder="0" ${auto?"disabled":""}>
      ${auto?`<div class="hint">считается по ${s.payments.length} ${plural(s.payments.length,"платежу","платежам","платежам")} — менять в разделе «Платежи»</div>`:`<div class="hint">или запишите платёж — тогда считается само</div>`}</div>
    <div class="fg c3"><label>Курс к сому</label><input type="number" step="0.01" id="f-rate" value="${s?.rate||""}" placeholder="—"></div>
    <div class="fg c12"><label>Комментарий</label><input id="f-note" value="${esc(s?.note||"")}"></div>
   </div>
   <div class="itm-head"><h4>Товары в партии</h4><button class="ghost sm" style="margin-left:auto" id="f-add-itm">${I.plus}<span>Товар</span></button></div>
   <div class="itm-cols"><span>Магазин</span><span>Наименование</span><span class="itm-qty">Кол-во</span><span class="itm-unitcol">Ед.</span><span class="itm-qty">Цена</span><span>Сумма</span><span></span></div>
   <div id="f-items"></div>
   <div class="msum"><span>Позиций: <b id="m-cnt">0</b></span><span>Сумма: <b id="m-sum">0</b></span><span>Остаток: <b id="m-bal">0</b></span></div>
   </div>
   <div class="mf"><span class="hint">⌘S — сохранить</span><button class="ghost" data-x>Отмена</button>
     ${isNew?'<button class="ghost" id="f-save-more">Сохранить и ещё одну</button>':""}
     <button class="pill" id="f-save" data-save>Сохранить</button></div>`);
  renderItems();
  $("#f-add-itm").onclick=()=>{ITEMS.push({});renderItems();const last=$("#f-items .itm-row:last-of-type");last?.querySelector(".i-prod")?.focus()};
  $("#f-pre").oninput=recalc;$("#f-cur").onchange=recalc;
  $("#f-st").onchange=()=>{const v=$("#f-st").value;
    if(v==="shipping"&&!$("#f-sent").value)$("#f-sent").value=todayISO();
    if(v==="arrived"&&!$("#f-arr").value)$("#f-arr").value=todayISO()};
  const save=async()=>{
    const body={date:$("#f-date").value,supplier_id:+$("#f-sup").value,currency:$("#f-cur").value,
      status:$("#f-st").value,sent_date:$("#f-sent").value||null,eta_date:$("#f-eta").value||null,
      arrived_date:$("#f-arr").value||null,track:$("#f-track").value,prepaid:+($("#f-pre").value||0),
      rate:+($("#f-rate").value||0)||null,note:$("#f-note").value,
      items:ITEMS.filter(i=>i.product||i.amount).map(i=>({store_id:+i.store_id||null,product:(i.product||"").trim(),
        qty:+i.qty||null,unit:i.unit||"шт",unit_price:+i.unit_price||null,amount:+i.amount||0,note:i.note||""}))};
    if(auto)delete body.prepaid;
    await api(isNew?"/api/shipments":"/api/shipments/"+s.id,{method:isNew?"POST":"PATCH",body});
    toast(isNew?"Партия создана":"Сохранено","ok");
    refreshAfterPay();
  };
  $("#f-save").onclick=async()=>{if(await withBusy($("#f-save"),save))closeModal()};
  if(isNew)$("#f-save-more").onclick=async()=>{if(await withBusy($("#f-save-more"),save))shipModal()};
}
function renderItems(){
  const stores=activeStores();
  const defStore=ITEMS.find(i=>i.store_id)?.store_id||stores[0]?.id;
  $("#f-items").innerHTML=ITEMS.map((i,n)=>`<div class="itm-row" data-n="${n}">
    <select class="i-store">${stores.map(st=>`<option value="${st.id}" ${(+i.store_id||defStore)===st.id?"selected":""}>№${esc(st.number)}</option>`).join("")}</select>
    <input class="i-prod" value="${esc(i.product||"")}" placeholder="Наименование товара" list="prod-hints">
    <input class="i-qty itm-qty" type="number" step="0.01" value="${i.qty||""}" placeholder="0">
    <select class="i-unit itm-unitcol">${["шт","кор","кг","м","компл"].map(u=>`<option ${(i.unit||"шт")===u?"selected":""}>${u}</option>`).join("")}</select>
    <input class="i-price itm-qty" type="number" step="0.01" value="${i.unit_price||""}" placeholder="0">
    <input class="i-amount" type="number" step="0.01" value="${i.amount||""}" placeholder="0">
    <button class="itm-del" title="Убрать" type="button">×</button></div>`).join("")+
    `<datalist id="prod-hints">${[...new Set((S.ships?.rows||[]).flatMap(s=>s.items.map(i=>i.product)))].slice(0,80).map(p=>`<option value="${esc(p)}">`).join("")}</datalist>`;
  $$("#f-items .itm-row").forEach(row=>{
    const n=+row.dataset.n,i=ITEMS[n];
    const sync=()=>{i.store_id=row.querySelector(".i-store").value;i.product=row.querySelector(".i-prod").value;
      i.qty=row.querySelector(".i-qty").value;i.unit=row.querySelector(".i-unit").value;
      i.unit_price=row.querySelector(".i-price").value;i.amount=row.querySelector(".i-amount").value;recalc()};
    row.querySelectorAll("input,select").forEach(el=>el.addEventListener("input",()=>{
      if(el.classList.contains("i-qty")||el.classList.contains("i-price")){
        const q=+row.querySelector(".i-qty").value,p=+row.querySelector(".i-price").value;
        if(q&&p)row.querySelector(".i-amount").value=Math.round(q*p*100)/100;}
      sync()}));
    row.querySelector(".itm-del").onclick=()=>{ITEMS.splice(n,1);if(!ITEMS.length)ITEMS.push({});renderItems()};
  });
  recalc();
}
function recalc(){
  const cur=$("#f-cur")?.value||"USD";
  const sum=ITEMS.reduce((a,i)=>a+(+i.amount||0),0);
  const cnt=ITEMS.filter(i=>i.product||+i.amount).length;
  if($("#m-cnt")){$("#m-cnt").textContent=cnt;$("#m-sum").textContent=money(sum,cur);
    $("#m-bal").textContent=money(sum-(+$("#f-pre")?.value||0),cur)}
}

/* ═══════════════════ ПЛАТЕЖИ ═══════════════════ */
function refreshAfterPay(){
  if(S.section==="ships"){loadShips();loadSummaryUI();loadRefs()}
  else if(S.section==="payments"){loadPayments();loadPayKpis()}
  else if(S.section==="partners")loadPartners();
  else if(S.section==="stores")loadStores();
  else if(S.section==="summary")renderSummary();
}
async function renderPayments(){
  await loadRefs();
  const sup=S.partners.filter(p=>p.is_supplier||p.shipments||p.payments);
  $("#main").innerHTML=`<div class="view">${headHtml("Платежи <span>поставщикам</span>",`<span class="sk" style="width:200px;height:12px;margin-top:6px"></span>`,`
     <a class="ghost" href="/api/payments.csv" download title="Скачать таблицу платежей">${I.down}<span>Excel</span></a>
     <button class="pill" id="add-pay">${I.plus}<span>Платёж</span></button>${avatarHtml()}`)}
    <div class="kpis" id="pkpis">${skKpis()}</div>
    <div class="glass panel" style="--i:1">
      <div class="ph"><h2>Все платежи <span class="cnt" id="pay-cnt"></span></h2>
        <div class="tabs" id="ptabs">${[["","Все"],["prepay","Авансы"],["final","Доплаты"],["refund","Возвраты"]]
          .map(([v,l])=>`<div class="tab${S.pay.kind===v?" on":""}" data-v="${v}">${l}</div>`).join("")}</div></div>
      <div class="fbar">
        <select id="pf-sup"><option value="">Все поставщики</option>${sup.map(p=>`<option value="${p.id}" ${String(S.pay.supplier)===String(p.id)?"selected":""}>${esc(p.name)}</option>`).join("")}</select>
        <input type="date" id="pf-from" value="${S.pay.from||""}" title="С даты"><input type="date" id="pf-to" value="${S.pay.to||""}" title="По дату">
        <span class="sep"></span>
        <div class="srch-w"><span class="srch-ic">${I.search}</span><input class="srch" id="pq" placeholder="Комментарий, способ, поставщик" value="${esc(S.pay.q||"")}" style="min-width:230px"></div>
      </div>
      <div id="pay-list">${skRows(3)}</div>
    </div></div>`;
  $("#add-pay").onclick=()=>payModal();
  $$("#ptabs .tab").forEach(t=>t.onclick=()=>{S.pay.kind=t.dataset.v;$$("#ptabs .tab").forEach(x=>x.classList.toggle("on",x===t));loadPayments()});
  $("#pf-sup").onchange=e=>{S.pay.supplier=e.target.value;loadPayments()};
  $("#pf-from").onchange=e=>{S.pay.from=e.target.value;loadPayments()};
  $("#pf-to").onchange=e=>{S.pay.to=e.target.value;loadPayments()};
  let qt;$("#pq").oninput=e=>{clearTimeout(qt);qt=setTimeout(()=>{S.pay.q=e.target.value;loadPayments()},300)};
  await Promise.all([loadPayments(),loadPayKpis()]);
}
async function loadPayKpis(){
  const d=await api("/api/summary");S.sum=d;const k=$("#pkpis");if(!k)return;const t=d.tiles,n=new Date();
  k.innerHTML=kpiHtml([
    ["Отдано в этом месяце",d.month_paid,"v-cyan",`${MONTH[n.getMonth()]} · всего ${d.payments_count} ${plural(d.payments_count,"платёж","платежа","платежей")}`,d.series.paid,"#3ED8D0"],
    ["Отдано за всё время",t.paid,"",t.ordered?Math.round(t.paid/t.ordered*100)+"% закупок оплачено":"—",null],
    ["Остаток к оплате",t.debt_total,"v-amber",t.debt_suppliers?`${t.debt_suppliers} ${plural(t.debt_suppliers,"поставщик ждёт","поставщика ждут","поставщиков ждут")} доплату`:"долгов нет",d.series.balance,"#FFB65C"],
    ["Заказано всего",t.ordered,"v-indigo",`${t.ordered_count} ${plural(t.ordered_count,"партия","партии","партий")} без отменённых`,d.series.ordered,"#6C8CFF"],
  ]);
  runCounters(k);
}
async function loadPayments(){
  const f=S.pay,p=new URLSearchParams();
  if(f.kind)p.set("kind",f.kind);if(f.supplier)p.set("supplier",f.supplier);if(f.from)p.set("from",f.from);if(f.to)p.set("to",f.to);if(f.q)p.set("q",f.q);
  const has=!!(f.kind||f.supplier||f.from||f.to||f.q);
  const d=await api("/api/payments?"+p);S.pays=d;const el=$("#pay-list");if(!el)return;
  const cnt=$("#pay-cnt");if(cnt)cnt.textContent=d.totals.count?"· "+d.totals.count:"";
  if(!d.rows.length){
    el.innerHTML=`<div class="empty">${ILL}<b>${has?"Ничего не найдено":"Платежей пока нет"}</b>${has?"Попробуйте снять фильтры":"Запишите первый платёж поставщику — аванс или доплату"}
      ${!has?`<br><button class="pill" onclick="payModal()">${I.plus}<span>Платёж</span></button>`:""}</div>`;
  }else{
    let html="",cur="",i=0;
    for(const r of d.rows){const ym=r.date.slice(0,7);
      if(ym!==cur){cur=ym;const g=d.rows.filter(x=>x.date.slice(0,7)===ym);const net=g.reduce((a,x)=>a+(x.kind==="refund"?-x.amount:x.amount),0);
        html+=`<div class="pay-month">${ymRu(ym)}<b>${g.length} ${plural(g.length,"платёж","платежа","платежей")} · ${money(net)}</b></div>`}
      html+=payRowHtml(r,Math.min(i++,12));}
    html+=`<div class="pay-row" style="background:rgba(255,255,255,.03);--i:13"><div></div>
      <div class="pw"><div class="who" style="font-size:13.5px;color:var(--muted)">Итого по фильтру</div><div class="meta">отдано ${money(d.totals.given)} · возвраты ${money(d.totals.refund)}</div></div>
      <div></div><div class="money"><b>${money(d.totals.net)}</b></div><div></div></div>`;
    el.innerHTML=html;bindPayActions(el,d.rows);
  }
  const sub=$("#hd-sub");if(sub)sub.textContent=`${d.totals.count} ${plural(d.totals.count,"платёж","платежа","платежей")} · чистыми отдано ${money(d.totals.net)}`;
}
function payRowHtml(r,i){
  const[y,m,dd]=r.date.split("-");
  const ship=r.ship_date?`партия от ${dRu(r.ship_date)} · ${money(r.ship_amount)}${r.ship_deleted?" (удалена)":""}`:"без привязки к партии";
  return `<div class="pay-row spot" data-id="${r.id}" style="--i:${i}">
    <div class="pd"><b>${+dd}</b><span>${MON[+m-1]}</span></div>
    <div class="pw"><div class="who">${esc(r.supplier_name)}</div><div class="meta">${esc(ship)}${r.method?" · "+esc(r.method):""}${r.note?" · "+esc(r.note):""}</div></div>
    <span class="tag k-${r.kind}" style="cursor:default">${KIND_RU[r.kind]}</span>
    <div class="money"><b class="${r.kind==="refund"?"v-rose":""}">${r.kind==="refund"?"−":""}${money(r.amount,r.currency)}</b></div>
    <div class="acts"><button class="mini-btn" data-edit title="Изменить">${I.edit}</button><button class="mini-btn del" data-del title="Удалить">${I.trash}</button></div></div>`;
}
function bindPayActions(root,rows,after){
  root.querySelectorAll(".pay-row[data-id]").forEach(el=>{
    const r=rows.find(x=>x.id===+el.dataset.id);if(!r)return;
    el.querySelector("[data-edit]").onclick=()=>payModal({},r,after);
    el.querySelector("[data-del]").onclick=async()=>{
      if(await confirmBox("Удалить платёж?",`${dRu(r.date)}, ${r.supplier_name}, ${money(r.amount,r.currency)}. Долг поставщика пересчитается.`,true)){
        try{await api("/api/payments/"+r.id,{method:"DELETE"});toast("Платёж удалён","ok");(after||refreshAfterPay)()}catch(e){toast(e.message,"err")}}};
  });
}
async function payModal(pre,p,after){
  pre=pre||{};
  await loadRefs();
  const sup=S.partners.filter(x=>x.active&&(x.is_supplier||x.shipments))
    .concat(S.partners.filter(x=>!x.active&&(x.id===p?.supplier_id||x.id===pre.supplier_id)));
  if(!sup.length){toast("Сначала добавьте поставщика (раздел «Поставщики»)","err");return}
  const supId=p?.supplier_id||pre.supplier_id||sup[0].id;
  let kind=p?.kind||pre.kind||"prepay";
  openModal(`<div class="mh"><h2>${p?"Платёж — "+esc(p.supplier_name||""):"Новый платёж"}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c4"><label>Дата</label><input type="date" id="y-date" value="${p?.date||todayISO()}"></div>
    <div class="fg c8"><label>Поставщик</label><select id="y-sup">${sup.map(x=>`<option value="${x.id}" ${x.id===supId?"selected":""}>${esc(x.name)}${x.debt>0.004?" — долг "+money(x.debt):""}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Партия</label><select id="y-ship"><option value="">Загрузка…</option></select><div class="hint" id="y-hint"></div></div>
    <div class="fg c12"><label>Тип платежа</label><div class="seg-ctl" id="y-kind"><i class="thumb"></i>
      ${KINDS.map(k=>`<button type="button" data-k="${k}">${KIND_RU[k]}</button>`).join("")}</div></div>
    <div class="fg c5"><label>Сумма</label><div class="amt-w"><input type="number" step="0.01" min="0" id="y-amt" value="${p?.amount||pre.amount||""}" placeholder="0" autofocus>
      <button type="button" class="lnk" id="y-rest" hidden>весь остаток</button></div></div>
    <div class="fg c3"><label>Валюта</label><select id="y-cur">${["USD","CNY","KGS"].map(c=>`<option ${((p?.currency)||pre.currency||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
    <div class="fg c4"><label>Способ</label><select id="y-meth"><option value="">—</option>${METHODS.map(m=>`<option ${(p?.method||"")===m?"selected":""}>${m}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Комментарий</label><input id="y-note" value="${esc(p?.note||"")}" placeholder="за что, кому передали"></div>
   </div></div>
   <div class="mf"><span class="hint">⌘S — сохранить</span><button class="ghost" data-x>Отмена</button><button class="pill" id="y-save" data-save>${p?"Сохранить":"Записать платёж"}</button></div>`,"mid");
  const setKind=k=>{kind=k;$$("#y-kind button").forEach(b=>b.classList.toggle("on",b.dataset.k===k));
    $("#y-kind .thumb").style.transform=`translateX(${KINDS.indexOf(k)*100}%)`};
  setKind(kind);$$("#y-kind button").forEach(b=>b.onclick=()=>setKind(b.dataset.k));
  let ships=[];
  const hint=()=>{const s=ships.find(x=>x.id===+$("#y-ship").value),h=$("#y-hint"),r=$("#y-rest");
    if(!s){h.textContent="Платёж пойдёт в общий счёт поставщика — на долг влияет так же";r.hidden=true;return}
    h.innerHTML=`Партия на <b>${money(s.amount,s.currency)}</b>, оплачено <b>${money(s.paid,s.currency)}</b>`+
      (s.balance>0.004?`, остаток <b>${money(s.balance,s.currency)}</b>`:"")+
      (s.pay_mode==="manual"&&s.paid>0&&!p?`. Ручной аванс ${money(s.paid,s.currency)} будет перенесён в список платежей автоматически`:"");
    r.hidden=!(s.balance>0.004);r.dataset.v=s.balance};
  const loadShipOpts=async()=>{
    const sid=+$("#y-sup").value,sel=$("#y-ship");
    const d=await api("/api/shipments?supplier="+sid);
    const want=p?.shipment_id||pre.shipment_id||"";
    ships=d.rows.filter(s=>s.status!=="cancelled"||s.id===want);
    sel.innerHTML=`<option value="">— без привязки к партии (общий долг)</option>`+ships.map(s=>`<option value="${s.id}" ${s.id===want?"selected":""}>${dRu(s.date)} · ${money(s.amount,s.currency)} · ${s.balance>0.004?"остаток "+money(s.balance,s.currency):s.balance<-0.004?"переплата":"оплачена"} · ${ST_RU[s.status]}</option>`).join("");
    hint()};
  $("#y-sup").onchange=loadShipOpts;$("#y-ship").onchange=hint;
  $("#y-rest").onclick=()=>{$("#y-amt").value=$("#y-rest").dataset.v;$("#y-amt").focus()};
  await loadShipOpts();
  $("#y-save").onclick=async()=>{
    const ok=await withBusy($("#y-save"),async()=>{
      const body={date:$("#y-date").value,supplier_id:+$("#y-sup").value,shipment_id:+$("#y-ship").value||null,
        amount:+$("#y-amt").value,currency:$("#y-cur").value,kind,method:$("#y-meth").value,note:$("#y-note").value};
      const r=await api(p?"/api/payments/"+p.id:"/api/payments",{method:p?"PATCH":"POST",body});
      toast(p?"Платёж изменён":(r.converted?`Платёж записан, ручной аванс ${money(r.converted)} перенесён в платежи`:"Платёж записан"),"ok");
    });
    if(ok){closeModal();(after||refreshAfterPay)()}
  };
}

/* ═══════════════════ ПОСТАВЩИКИ ═══════════════════ */
async function renderPartners(){
  $("#main").innerHTML=`<div class="view">${headHtml("Поставщики <span>и партнёры</span>",`<span class="sk" style="width:200px;height:12px;margin-top:6px"></span>`,
    `<button class="pill" id="add-p">${I.plus}<span>Контрагент</span></button>${avatarHtml()}`)}
    <div class="glass panel" style="--i:1"><div class="list-wrap" id="p-list">${skRows(3)}</div></div></div>`;
  $("#add-p").onclick=()=>partnerModal();
  await loadPartners();
}
async function loadPartners(){
  await loadRefs();const rows=S.partners,el=$("#p-list");if(!el)return;
  const sub=$("#hd-sub");if(sub)sub.textContent=`${rows.length} ${plural(rows.length,"контрагент","контрагента","контрагентов")} · долг всем ${money(rows.reduce((a,p)=>a+Math.max(0,p.debt||0),0))}`;
  el.innerHTML=rows.length?`<table class="list-tbl"><thead><tr><th>Название</th><th>Тип</th><th>Город · контакт</th><th class="num">Партий</th>
      <th class="num">Оборот</th><th>Отдано</th><th class="num">Долг</th><th class="num">В пути</th><th></th></tr></thead><tbody>
    ${rows.map((p,i)=>`<tr class="clk ${p.active?"":"inactive"}" data-id="${p.id}" style="--i:${Math.min(i,12)}">
      <td><b>${esc(p.name)}</b>${p.active?"":" <span class='chip'>скрыт</span>"}</td>
      <td style="color:var(--muted)">${[p.is_supplier?"поставщик":"",p.is_investor?"инвестор":""].filter(Boolean).join(" + ")||"—"}</td>
      <td style="color:var(--muted)">${esc([p.city,p.contact].filter(Boolean).join(" · "))||"—"}</td>
      <td class="num">${p.shipments}</td><td class="num">${money(p.total)}</td>
      <td><span>${money(p.paid)}</span><div class="pb"><i data-w="${p.total?Math.min(100,Math.max(0,p.paid/p.total*100)).toFixed(0):0}"></i></div></td>
      <td class="num" style="color:${p.debt>0.004?"var(--amber)":p.debt<-0.004?"var(--green)":"var(--dim)"}">${p.debt<-0.004?"+":""}${money(Math.abs(p.debt))}</td>
      <td class="num" style="color:${p.transit?"var(--green)":"var(--dim)"}">${money(p.transit)}</td>
      <td><div class="acts"><button class="mini-btn" data-pay title="Записать платёж">${I.pay}</button><button class="mini-btn" data-edit title="Изменить">${I.edit}</button><button class="mini-btn del" data-del title="Удалить">${I.trash}</button></div></td>
    </tr>`).join("")}</tbody></table>`
    :`<div class="empty">${ILL}<b>Контрагентов пока нет</b>Добавьте первого поставщика<br><button class="pill" onclick="partnerModal()">${I.plus}<span>Контрагент</span></button></div>`;
  kick(el);
  el.querySelectorAll("tr[data-id]").forEach(tr=>{
    const p=rows.find(x=>x.id===+tr.dataset.id);
    tr.onclick=e=>{if(e.target.closest("button"))return;partnerCard(p.id)};
    tr.querySelector("[data-pay]").onclick=()=>payModal({supplier_id:p.id});
    tr.querySelector("[data-edit]").onclick=()=>partnerModal(p);
    tr.querySelector("[data-del]").onclick=async()=>{
      if(await confirmBox("Удалить контрагента?",p.name+(p.shipments||p.payments?" — у него есть партии или платежи, он будет скрыт с сохранением истории":""),true)){
        const r=await api("/api/partners/"+p.id,{method:"DELETE"});toast(r.msg||"Удалено","ok");loadPartners()}};
  });
}
async function partnerCard(pid,tab){
  tab=tab||"ships";
  let p;try{p=await api("/api/partners/"+pid)}catch(e){toast(e.message,"err");return}
  const pct=p.total?Math.min(100,Math.max(0,p.paid/p.total*100)):0;
  const types=[p.is_supplier?"поставщик":"",p.is_investor?"инвестор":""].filter(Boolean).join(" + ");
  openModal(`<div class="mh"><div><h2>${esc(p.name)}</h2><div class="meta">${esc([types,p.city,p.contact].filter(Boolean).join(" · "))}</div></div>
     <div class="mh-acts"><button class="ghost sm" id="pc-pay">${I.pay}<span>Платёж</span></button><button class="ghost sm" id="pc-edit" title="Изменить">${I.edit}</button><button class="x" data-x>×</button></div></div>
   <div class="mb">
     <div class="pc-stats"><div class="pc-ring">${ringSvg(pct,pct>=99.5?"#57E39B":"#3ED8D0",78,7)}<div class="pc-ring-l"><b>${Math.round(pct)}%</b><span>оплачено</span></div></div>
       <div class="pc-grid">
         <div class="pc-st"><span>Оборот</span><b>${money(p.total)}</b></div>
         <div class="pc-st"><span>Отдано</span><b class="v-cyan">${money(p.paid)}</b></div>
         <div class="pc-st"><span>${p.debt<-0.004?"Переплата":"Долг"}</span><b class="${p.debt>0.004?"v-amber":"v-green"}">${money(Math.abs(p.debt))}</b></div>
         <div class="pc-st"><span>В пути</span><b class="v-green">${money(p.transit)}</b></div></div></div>
     <div class="tabs" id="pc-tabs" style="margin-left:0;display:inline-flex"><div class="tab${tab==="ships"?" on":""}" data-t="ships">Партии · ${p.shipments.length}</div><div class="tab${tab==="pays"?" on":""}" data-t="pays">Платежи · ${p.payments_list.length}</div></div>
     <div class="pc-list" id="pc-body"></div></div>`,"wide");
  kick($("#modal"));
  const again=()=>{partnerCard(pid,tab);refreshAfterPay()};
  const body=()=>{const b=$("#pc-body");
    if(tab==="ships"){
      b.innerHTML=p.shipments.length?p.shipments.map((s,i)=>`<div class="ship" style="--i:${i}"><div class="ship-top" style="cursor:default">
        <div><div class="who">${dRu(s.date)}</div><div class="meta">${s.items.length} поз. · ${s.items.slice(0,3).map(x=>esc(x.product)).join(", ")}${s.items.length>3?" …":""}${s.track?" · "+esc(s.track):""}</div></div>
        <span class="tag t-${s.status}" style="cursor:default">${ST_RU[s.status]}</span>
        <div class="money"><b>${money(s.amount,s.currency)}</b><div class="m2">${s.status==="cancelled"?"не считается":s.balance<=0.004?"оплачено полностью":"оплачено "+money(s.paid,s.currency)+" · остаток "+money(s.balance,s.currency)}</div></div>
        <div class="acts"><button class="mini-btn" data-pay="${s.id}" title="Платёж по партии">${I.pay}</button></div></div>
        ${s.status!=="cancelled"&&s.amount?`<div class="paybar"><i data-w="${Math.min(100,Math.max(0,s.paid/s.amount*100)).toFixed(1)}"></i></div>`:""}</div>`).join("")
        :`<div class="empty"><b>Партий нет</b></div>`;
      b.querySelectorAll("[data-pay]").forEach(x=>x.onclick=()=>payModal({supplier_id:pid,shipment_id:+x.dataset.pay},null,again));kick(b);
    }else{
      const rows=p.payments_list.map(r=>({...r,supplier_name:p.name}));
      b.innerHTML=rows.length?rows.map((r,i)=>payRowHtml(r,i)).join(""):`<div class="empty"><b>Платежей нет</b>Запишите первый — долг посчитается сам</div>`;
      bindPayActions(b,rows,again);
    }};
  body();
  $$("#pc-tabs .tab").forEach(t=>t.onclick=()=>{tab=t.dataset.t;$$("#pc-tabs .tab").forEach(x=>x.classList.toggle("on",x===t));body()});
  $("#pc-pay").onclick=()=>payModal({supplier_id:pid},null,again);
  $("#pc-edit").onclick=()=>partnerModal(p,again);
}
function partnerModal(p,after){
  openModal(`<div class="mh"><h2>${p?"Контрагент":"Новый контрагент"}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c12"><label>Название</label><input id="p-name" value="${esc(p?.name||"")}" placeholder="Гуанчжоу — Чен" autofocus></div>
    <div class="fg c6"><label>Тип</label><div style="display:flex;gap:16px;padding:9px 2px">
      <label class="chk"><input type="checkbox" id="p-sup" ${(p?p.is_supplier:1)?"checked":""}> поставщик</label>
      <label class="chk"><input type="checkbox" id="p-inv" ${p?.is_investor?"checked":""}> инвестор</label></div></div>
    <div class="fg c6"><label>Город (начало маршрута)</label><input id="p-city" value="${esc(p?.city||"")}" placeholder="Гуанчжоу"></div>
    <div class="fg c6"><label>Контакт (WeChat / WhatsApp)</label><input id="p-contact" value="${esc(p?.contact||"")}"></div>
    <div class="fg c6"><label>Валюта по умолчанию</label><select id="p-cur">${["USD","CNY","KGS"].map(c=>`<option ${((p?.currency)||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Комментарий</label><input id="p-note" value="${esc(p?.note||"")}"></div>
    ${p&&!p.active?'<div class="fg c12"><label class="chk"><input type="checkbox" id="p-act"> показать снова (сейчас скрыт)</label></div>':""}
   </div></div>
   <div class="mf"><button class="ghost" data-x>Отмена</button><button class="pill" id="p-save" data-save>Сохранить</button></div>`,"mid");
  $("#p-save").onclick=async()=>{
    const ok=await withBusy($("#p-save"),async()=>{
      await api(p?"/api/partners/"+p.id:"/api/partners",{method:p?"PATCH":"POST",body:{
        name:$("#p-name").value,is_supplier:$("#p-sup").checked?1:0,is_investor:$("#p-inv").checked?1:0,
        city:$("#p-city").value,contact:$("#p-contact").value,currency:$("#p-cur").value,note:$("#p-note").value,
        active:p&&!p.active?($("#p-act").checked?1:0):1}});
      toast("Сохранено","ok")});
    if(ok){closeModal();(after||(S.section==="partners"?loadPartners:refreshAfterPay))()}
  };
}

/* ═══════════════════ МАГАЗИНЫ ═══════════════════ */
async function renderStores(){
  $("#main").innerHTML=`<div class="view">${headHtml("Магазины","куда едет товар",`<button class="pill" id="add-s">${I.plus}<span>Магазин</span></button>${avatarHtml()}`)}
    <div class="glass panel" style="--i:1"><div class="list-wrap" id="s-list">${skRows(3)}</div></div></div>`;
  $("#add-s").onclick=()=>storeModal();
  await loadStores();
}
async function loadStores(){
  await loadRefs();const rows=S.stores,el=$("#s-list");if(!el)return;
  const mx=Math.max(...rows.map(s=>s.total),1);
  el.innerHTML=rows.length?`<table class="list-tbl"><thead><tr><th>Номер</th><th>Название</th><th class="num">Партий</th><th class="num">Позиций</th>
      <th>Закуплено</th><th class="num">В пути</th><th></th></tr></thead><tbody>
    ${rows.map((s,i)=>`<tr class="${s.active?"":"inactive"}" data-id="${s.id}" style="--i:${Math.min(i,12)}">
      <td><span class="badge">№${esc(s.number)}</span></td><td><b>${esc(s.name||"—")}</b>${s.active?"":" <span class='chip'>скрыт</span>"}</td>
      <td class="num">${s.shipments}</td><td class="num">${s.items}</td>
      <td><span>${money(s.total)}</span><div class="pb"><i data-w="${Math.round(s.total/mx*100)}"></i></div></td>
      <td class="num" style="color:${s.transit?"var(--green)":"var(--dim)"}">${money(s.transit)}</td>
      <td><div class="acts"><button class="mini-btn" data-edit title="Изменить">${I.edit}</button><button class="mini-btn del" data-del title="Удалить">${I.trash}</button></div></td>
    </tr>`).join("")}</tbody></table>`
    :`<div class="empty">${ILL}<b>Магазинов пока нет</b>Добавьте первый — номер и название<br><button class="pill" onclick="storeModal()">${I.plus}<span>Магазин</span></button></div>`;
  kick(el);
  el.querySelectorAll("tr[data-id]").forEach(tr=>{
    const s=rows.find(x=>x.id===+tr.dataset.id);
    tr.querySelector("[data-edit]").onclick=()=>storeModal(s);
    tr.querySelector("[data-del]").onclick=async()=>{
      if(await confirmBox("Удалить магазин?","№"+s.number+(s.items?" — участвует в партиях, будет скрыт с сохранением истории":""),true)){
        const r=await api("/api/stores/"+s.id,{method:"DELETE"});toast(r.msg||"Удалено","ok");loadStores()}};
  });
}
function storeModal(s){
  openModal(`<div class="mh"><h2>${s?"Магазин №"+esc(s.number):"Новый магазин"}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c3"><label>Номер</label><input id="s-num" value="${esc(s?.number||"")}" placeholder="1" autofocus></div>
    <div class="fg c9"><label>Название</label><input id="s-name" value="${esc(s?.name||"")}" placeholder="Дордой, 3 ряд"></div>
    <div class="fg c12"><label>Комментарий</label><input id="s-note" value="${esc(s?.note||"")}"></div>
    ${s&&!s.active?'<div class="fg c12"><label class="chk"><input type="checkbox" id="s-act"> показать снова</label></div>':""}
   </div></div>
   <div class="mf"><button class="ghost" data-x>Отмена</button><button class="pill" id="s-save" data-save>Сохранить</button></div>`,"small");
  $("#s-save").onclick=async()=>{
    const ok=await withBusy($("#s-save"),async()=>{
      await api(s?"/api/stores/"+s.id:"/api/stores",{method:s?"PATCH":"POST",body:{
        number:$("#s-num").value,name:$("#s-name").value,note:$("#s-note").value,
        active:s&&!s.active?($("#s-act").checked?1:0):1}});
      toast("Сохранено","ok")});
    if(ok){closeModal();loadStores()}
  };
}

/* ═══════════════════ ИНВЕСТОРЫ (этап 4) ═══════════════════ */
async function renderInvestors(){
  await loadRefs();
  const inv=S.partners.filter(p=>p.is_investor);
  $("#main").innerHTML=`<div class="view">${headHtml("Инвесторы <span>и доли</span>","вложения · начисления · выплаты",avatarHtml())}
   <div class="glass panel" style="--i:1"><div class="empty" style="padding:70px 20px">${ILL}
     <b>Раздел появится на этапе 4</b>
     Вложения в партии и общий пул, условия «доля от прибыли» и «процент в месяц»,<br>начисления, выплаты и отчёт инвестору одной страницей.
     ${inv.length?`<div class="chips" style="justify-content:center;margin-top:18px">${inv.map(p=>`<span class="chip">${esc(p.name)}</span>`).join("")}</div>
     <div style="color:var(--dim);font-size:12.5px;margin-top:10px">Эти контрагенты уже помечены как инвесторы — они подхватятся автоматически</div>`:""}
   </div></div></div>`;
}

/* ═══════════════════ СВОДКА ═══════════════════ */
async function renderSummary(){
  $("#main").innerHTML=`<div class="view">${headHtml("Сводка","вся картина за всё время",
    `<a class="ghost" href="/api/export.csv" download>${I.down}<span>Партии в Excel</span></a>${avatarHtml()}`)}
   <div class="kpis" id="kpis">${skKpis()}</div>
   <div class="grid"><div style="display:flex;flex-direction:column;gap:16px;min-width:0">
     <div class="glass panel" style="--i:1"><div class="ph"><h2>Партии по статусам</h2></div><div class="mb" id="sum-status">${skRows(1)}</div></div>
     <div class="glass panel" style="--i:2"><div class="ph"><h2>Топ поставщиков</h2><span class="cnt">по обороту</span></div><div class="mb" id="sum-sup"></div></div>
     <div class="glass panel" style="--i:3"><div class="ph"><h2>Закупки по магазинам</h2></div><div class="mb" id="sum-store"></div></div>
     <div class="glass panel" style="--i:4"><div class="ph"><h2>Ожидается прибытие</h2></div><div id="arr-list"></div></div>
   </div><aside id="aside" style="--i:2">${skAside()}</aside></div></div>`;
  await loadRefs();await loadSummaryUI();
  const d=S.sum;if(!$("#sum-status"))return;
  const st=[["shipping","В пути","#FFB65C"],["new","Не отправлены","#8B94A8"],["arrived","Прибыли","#57E39B"],["cancelled","Отменены","#FF7B93"]];
  const parts=st.map(([k,l,c])=>({v:d.by_status[k].amount,color:c,l}));
  const totalAmt=parts.reduce((a,p)=>a+p.v,0),totalCnt=st.reduce((a,[k])=>a+d.by_status[k].count,0);
  $("#sum-status").innerHTML=`<div class="donut-w"><div class="donut-c">${donutSvg(parts.filter(p=>p.v>0),136,13)}
      <div class="dl"><b>${totalCnt}</b><span>${plural(totalCnt,"партия","партии","партий")}</span></div></div>
    <div class="donut-l">${st.map(([k,l,c])=>{const b=d.by_status[k];return `<div class="stat"><span class="l"><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${c};margin-right:8px"></i>${l} · ${b.count}</span>
      <span class="v">${money(b.amount)}${totalAmt?` <small style="color:var(--dim);font-weight:500">${Math.round(b.amount/totalAmt*100)}%</small>`:""}</span></div>`}).join("")}</div></div>`;
  const mxS=Math.max(...d.top_suppliers.map(x=>x[1]),1);
  $("#sum-sup").innerHTML=d.top_suppliers.length?d.top_suppliers.map(([n,v,debt])=>`<div class="hbar"><div class="hb-l"><span>${esc(n)}</span><b>${money(v)}${debt>0.004?`<small>долг ${money(debt)}</small>`:""}</b></div>
      <div class="hb-t"><i data-w="${Math.round(v/mxS*100)}"></i></div></div>`).join(""):`<div class="empty" style="padding:20px"><b>Пока пусто</b></div>`;
  const mxT=Math.max(...d.by_store.map(x=>x[1]),1);
  $("#sum-store").innerHTML=d.by_store.length?d.by_store.map(([n,v])=>`<div class="hbar"><div class="hb-l"><span>${esc(n)}</span><b>${money(v)}</b></div>
      <div class="hb-t"><i class="g" data-w="${Math.round(v/mxT*100)}"></i></div></div>`).join(""):`<div class="empty" style="padding:20px"><b>Пока пусто</b></div>`;
  $("#arr-list").innerHTML=d.arriving.length?d.arriving.map((x,i)=>`<div class="ship" style="--i:${i}"><div class="ship-top" style="cursor:default">
      <div><div class="who">${esc(x.supplier)}</div><div class="meta">${x.sent?"отправлена "+dRu(x.sent):""}${x.days!=null?" · в пути "+x.days+" дн.":""}</div></div>
      <div class="money"><b>${money(x.amount)}</b><div class="m2 ${x.eta&&x.eta<todayISO()?"v-amber":""}">${x.eta?(x.eta<todayISO()?"задержка — ждали ":"ожидается ")+dRu(x.eta):"срок не указан"}</div></div></div></div>`).join("")
    :`<div class="empty"><b>Ничего не едет</b>Все партии на месте</div>`;
  kick($("#main"));
}

/* ═══════════════════ НАСТРОЙКИ ═══════════════════ */
function renderSettings(){
  $("#main").innerHTML=`<div class="view">${headHtml("Настройки","",avatarHtml())}
   <div class="grid two">
    <div class="glass card spot" style="--i:0"><h3>Данные</h3>
      <div class="stat"><span class="l">Партии и товары — в Excel (CSV)</span><a class="ghost sm" href="/api/export.csv" download>Скачать</a></div>
      <div class="stat"><span class="l">Платежи — в Excel (CSV)</span><a class="ghost sm" href="/api/payments.csv" download>Скачать</a></div>
      <div class="stat"><span class="l">Резервная копия базы</span><button class="ghost sm" id="bk">Сделать сейчас</button></div>
      <div class="stat"><span class="l wrap" style="font-size:12px;color:var(--dim)">Копия делается сама при каждом запуске, хранится 30 последних в папке backups</span></div></div>
    <div class="glass card spot" style="--i:1"><h3>Аккаунт</h3>
      <div class="stat"><span class="l">Вы вошли как</span><span class="v">${esc(S.user?.name||S.user?.login||"")}</span></div>
      <div class="stat"><span class="l">Роль</span><span class="v">${S.user?.role==="owner"?"Владелец":"Помощник"}</span></div>
      <div class="stat"><span class="l">Версия программы</span><span class="v">${esc(S.user?.version||"")}</span></div>
      <div class="stat"><span class="l">Выйти из программы</span><button class="ghost sm" id="out">Выйти</button></div></div>
    <div class="glass card spot" style="--i:2"><h3>Горячие клавиши</h3><div class="keys">
      <div class="stat"><span class="l">Новая партия / платёж / контрагент</span><span class="v"><kbd>N</kbd></span></div>
      <div class="stat"><span class="l">Поиск</span><span class="v"><kbd>/</kbd></span></div>
      <div class="stat"><span class="l">Сохранить в открытом окне</span><span class="v"><kbd>⌘</kbd><kbd>S</kbd></span></div>
      <div class="stat"><span class="l">Закрыть окно</span><span class="v"><kbd>Esc</kbd></span></div>
      <div class="stat"><span class="l">Разделы по порядку</span><span class="v"><kbd>1</kbd><kbd>2</kbd>…<kbd>6</kbd></span></div></div></div>
    <div class="glass card spot" style="--i:3"><h3>На телефон</h3>
      <div class="stat"><span class="l wrap">Откройте адрес программы в Safari → «Поделиться» → «На экран Домой». Откроется как приложение, без адресной строки.</span></div></div>
   </div></div>`;
  $("#bk").onclick=async()=>{const b=$("#bk");b.disabled=true;try{const r=await api("/api/backup",{method:"POST"});toast("Копия сделана: "+r.file,"ok")}catch(e){toast(e.message,"err")}finally{b.disabled=false}};
  $("#out").onclick=async()=>{await api("/api/logout",{method:"POST"});location.reload()};
}

/* ═══════════════════ старт ═══════════════════ */
(async function(){
  const h=location.hash.replace("#","");if(RENDER[h])S.section=h;
  $$("#rail a").forEach(a=>a.onclick=()=>go(a.dataset.sec));
  try{S.user=await api("/api/me");$("#app").classList.remove("off");go(S.section)}
  catch(e){showLogin()}
})();
