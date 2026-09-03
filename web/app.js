"use strict";
/* Китай · учёт — логика интерфейса, v5 (этапы 1–5: локально и в облаке, роль помощника) */

/* ═══════════════════ утилиты ═══════════════════ */
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const CUR={USD:"$",CNY:"¥",KGS:"с"};
const ST_RU={new:"Не отправлен",shipping:"В пути",arrived:"Прибыл",cancelled:"Отменён"};
const KIND_RU={prepay:"Аванс",final:"Доплата",refund:"Возврат"};
const KINDS=["prepay","final","refund"];
const TERMS=["share","fixed"],TERMS_RU={share:"Доля от прибыли",fixed:"Процент в месяц"};
const PO_KINDS=["profit","principal"],PO_RU={profit:"Доля прибыли",principal:"Возврат вложения"};
const METHODS=["Наличные","Перевод на карту","WeChat","Alipay","Через посредника","Другое"];
const MON=["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
const MONTH=["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const PERIODS=[["all","Всё время"],["month","Этот месяц"],["prev","Прошлый месяц"],["quarter","Этот квартал"],["year","Этот год"],["custom","Свой период"]];
const SORTS=[["date_desc","Сначала новые"],["date_asc","Сначала старые"],["amount_desc","По сумме"],["balance_desc","По остатку"],["supplier","По поставщику"]];
const MONEY_SECS=["payments","investors","summary"];
const reduced=()=>matchMedia("(prefers-reduced-motion: reduce)").matches;
const isMobile=()=>matchMedia("(max-width: 820px)").matches;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let UID=0;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function fmtN(v){return (Math.round((+v||0)*100)/100).toLocaleString("ru-RU",{maximumFractionDigits:2}).replace(/,/g,".").replace(/ /g," ")}
function money(v,cur){cur=cur||"USD";const n=+v||0;const s=fmtN(Math.abs(n));const b=cur==="KGS"?s+" с":(CUR[cur]||"")+s;return (n<-0.004?"−":"")+b}
function dRu(d){if(!d)return"";const[y,m,dd]=d.split("-");return dd+"."+m+"."+y}
function dShort(d){if(!d)return"";const[y,m,dd]=d.split("-");return +dd+" "+MON[+m-1]}
function ymRu(ym){const[y,m]=ym.split("-");return MONTH[+m-1]+" "+y}
function iso(x){return x.getFullYear()+"-"+String(x.getMonth()+1).padStart(2,"0")+"-"+String(x.getDate()).padStart(2,"0")}
function todayISO(){return iso(new Date())}
function plural(n,a,b,c){n=Math.abs(n)%100;const n1=n%10;if(n>10&&n<20)return c;if(n1>1&&n1<5)return b;if(n1===1)return a;return c}
function periodRange(p,from,to){const d=new Date(),y=d.getFullYear(),m=d.getMonth();
  if(p==="month")return[iso(new Date(y,m,1)),iso(new Date(y,m+1,0))];
  if(p==="prev")return[iso(new Date(y,m-1,1)),iso(new Date(y,m,0))];
  if(p==="quarter"){const q=Math.floor(m/3)*3;return[iso(new Date(y,q,1)),iso(new Date(y,q+3,0))]}
  if(p==="year")return[iso(new Date(y,0,1)),iso(new Date(y,11,31))];
  if(p==="custom")return[from||"",to||""];
  return["",""]}
function periodLabel(p,from,to){if(p==="custom")return(from?dRu(from):"…")+" — "+(to?dRu(to):"…");return(PERIODS.find(x=>x[0]===p)||PERIODS[0])[1].toLowerCase()}
const termsRu=v=>v.terms==="fixed"?`${+v.terms_value||0}% в месяц`:`${+v.terms_value||0}% от прибыли`;
const M=()=>S.money;
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
  more:'<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  split:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.5 15.5M8.5 8.5L20 20"/></svg>',
  flag:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22V4"/><path d="M4 4h12l-2 4 2 4H4"/></svg>',
  doc:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M14 3v6h6"/><path d="M8 13h8M8 17h6"/></svg>',
  coins:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
  key:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="4"/><path d="M10.9 12.1L21 2"/><path d="M15 8l3 3M18 5l3 3"/></svg>',
  user:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>',
};
const ILL='<svg class="ill" viewBox="0 0 96 96" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 62c14-22 30-22 44-10s22 8 24-6" stroke-dasharray="4 5" opacity=".45"/><path d="M30 44l18-8 18 8-18 8z" stroke="#6C8CFF"/><path d="M30 44v14l18 8 18-8V44" stroke="#6C8CFF"/><path d="M48 52v14" stroke="#6C8CFF"/><circle cx="14" cy="62" r="3" fill="#FFB65C" stroke="none"/><circle cx="82" cy="46" r="3" fill="#57E39B" stroke="none"/></svg>';

/* ═══════════════════ тосты, окна, меню ═══════════════════ */
function toast(msg,cls="info"){
  const t=document.createElement("div");t.className="toast "+cls;
  const life=cls==="err"?4200:2800;t.style.setProperty("--life",life+"ms");
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
/* всплывающее меню действий */
function menuPop(anchor,items){
  let pop=$("#menu-pop");if(!pop){pop=document.createElement("div");pop.id="menu-pop";document.body.appendChild(pop)}
  pop.innerHTML=items.map((it,i)=>`<button class="mi ${it.danger?"danger":""}" data-i="${i}">${it.ic||""}<span>${esc(it.l)}</span></button>`).join("");
  const r=anchor.getBoundingClientRect();
  pop.style.left=Math.max(8,Math.min(r.right-210,innerWidth-218))+"px";pop.style.top=(r.bottom+scrollY+6)+"px";
  pop.classList.add("show");
  pop.querySelectorAll(".mi").forEach(b=>b.onclick=()=>{hidePop();items[+b.dataset.i].fn()});
  setTimeout(()=>document.addEventListener("click",function h(e){if(!pop.contains(e.target)){hidePop();document.removeEventListener("click",h)}}),0);
}
function hidePop(){$("#st-pop")?.classList.remove("show");$("#menu-pop")?.classList.remove("show")}

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
const skSub=()=>`<span class="sk" style="width:220px;height:12px;margin-top:6px"></span>`;

/* ═══════════════════ состояние ═══════════════════ */
const S={user:null,money:true,section:"ships",tab:"",q:"",stores:[],partners:[],ships:null,sum:null,pays:null,inv:null,
  f:{period:"all",from:"",to:"",store:"",supplier:"",sort:"date_desc"},
  sp:{period:"all",from:"",to:""},
  pay:{kind:"",supplier:"",from:"",to:"",q:""},settings:{currency:"USD",rate:null},kpiPrev:{}};
function applyRole(){
  S.money=S.user?.role!=="helper";
  $$("#rail a").forEach(a=>a.style.display=(!S.money&&MONEY_SECS.includes(a.dataset.sec))?"none":"");
}

/* ═══════════════════ вход (облачный режим) ═══════════════════ */
function showLogin(){$("#login-ov").classList.add("show");$("#app").classList.add("off")}
$("#login-form").onsubmit=async e=>{
  e.preventDefault();$("#l-err").textContent="";const btn=$("#l-btn");btn.classList.add("busy");
  try{
    const r=await api("/api/login",{method:"POST",body:{login:$("#l-login").value,password:$("#l-pass").value}});
    S.user=r.user;applyRole();$("#login-ov").classList.remove("show");$("#app").classList.remove("off");go(S.section);
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
  if(!RENDER[sec]||(!S.money&&MONEY_SECS.includes(sec)))sec="ships";
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
    ({payments:payModal,partners:partnerModal,stores:storeModal,investors:investModal}[S.section]||shipModal)();return}
  if(/^[1-6]$/.test(e.key))go(["ships","payments","partners","investors","stores","summary"][+e.key-1]);
});
function headHtml(title,sub,right){
  return `<header class="top"><div><h1>${title}</h1><div class="sub" id="hd-sub">${sub||""}</div></div><div class="hd-r">${right||""}</div></header>`;
}
function avatarHtml(){return `<div class="glass avatar" title="${esc(S.user?.name||"")}" data-go="settings">${esc((S.user?.name||"А")[0])}</div>`}
function periodSel(id,cur){return `<select id="${id}" class="psel">${PERIODS.map(([v,l])=>`<option value="${v}" ${cur===v?"selected":""}>${l}</option>`).join("")}</select>`}

/* ═══════════════════ справочные данные ═══════════════════ */
async function loadRefs(){[S.stores,S.partners,S.settings]=await Promise.all([api("/api/stores"),api("/api/partners"),api("/api/settings")])}
const activeStores=()=>S.stores.filter(s=>s.active);
const activeSuppliers=()=>S.partners.filter(p=>p.active&&p.is_supplier);

/* ═══════════════════ ПАРТИИ ═══════════════════ */
function shipParams(){
  const p=new URLSearchParams();const f=S.f;const[from,to]=periodRange(f.period,f.from,f.to);
  if(S.tab)p.set("status",S.tab);if(S.q)p.set("q",S.q);
  if(from)p.set("from",from);if(to)p.set("to",to);if(f.store)p.set("store",f.store);if(f.supplier)p.set("supplier",f.supplier);
  if(f.sort&&f.sort!=="date_desc")p.set("sort",f.sort);
  return p;
}
async function renderShips(){
  await loadRefs();
  const f=S.f;
  $("#main").innerHTML=`<div class="view">${headHtml("Партии <span>из Китая</span>",skSub(),`
    <div class="srch-w"><span class="srch-ic">${I.search}</span><input class="srch" id="q" placeholder="Поиск: товар, трек, поставщик" value="${esc(S.q)}"><kbd>/</kbd></div>
    <button class="pill" id="add-ship">${I.plus}<span>Новая партия</span></button>${avatarHtml()}`)}
    ${M()?`<div class="kpis" id="kpis">${skKpis()}</div>`:""}
    <div class="grid${M()?"":" one"}"><div class="glass panel" style="--i:1">
      <div class="ph"><h2>Партии в работе <span class="cnt" id="sh-cnt"></span></h2>
        <div class="tabs" id="tabs">${[["","Все"],["shipping","В пути"],["new","Не отправлены"],["arrived","Прибыли"],["cancelled","Отменены"]]
          .map(([v,l])=>`<div class="tab${S.tab===v?" on":""}" data-v="${v}">${l}</div>`).join("")}</div></div>
      <div class="fbar">
        ${periodSel("f-period",f.period)}
        <span class="rng" id="f-rng" ${f.period==="custom"?"":"hidden"}><input type="date" id="f-from" value="${f.from}" title="С даты"><input type="date" id="f-to" value="${f.to}" title="По дату"></span>
        <select id="f-store"><option value="">Все магазины</option>${S.stores.map(s=>`<option value="${s.id}" ${String(f.store)===String(s.id)?"selected":""}>№${esc(s.number)}${s.name?" · "+esc(s.name):""}</option>`).join("")}</select>
        <select id="f-sup"><option value="">Все поставщики</option>${S.partners.filter(p=>p.is_supplier||p.shipments).map(p=>`<option value="${p.id}" ${String(f.supplier)===String(p.id)?"selected":""}>${esc(p.name)}</option>`).join("")}</select>
        <span class="sep"></span>
        <select id="f-sort" title="Сортировка">${SORTS.filter(([v])=>M()||!/amount|balance/.test(v)).map(([v,l])=>`<option value="${v}" ${f.sort===v?"selected":""}>${l}</option>`).join("")}</select>
        ${M()?`<a class="ghost sm" id="f-export" href="/api/export.csv" download title="Выгрузить в Excel по текущему фильтру">${I.down}<span>Excel</span></a>`:""}
      </div>
      <div id="ship-list">${skRows(3)}</div>
    </div>${M()?`<aside id="aside" style="--i:2">${skAside()}</aside>`:""}</div></div>`;
  $("#add-ship").onclick=()=>shipModal();
  let qt;$("#q").oninput=e=>{clearTimeout(qt);qt=setTimeout(()=>{S.q=e.target.value;loadShips()},300)};
  $$("#tabs .tab").forEach(t=>t.onclick=()=>{S.tab=t.dataset.v;$$("#tabs .tab").forEach(x=>x.classList.toggle("on",x===t));loadShips()});
  $("#f-period").onchange=e=>{f.period=e.target.value;$("#f-rng").hidden=f.period!=="custom";if(f.period!=="custom"||(f.from||f.to))loadShips()};
  $("#f-from").onchange=e=>{f.from=e.target.value;loadShips()};$("#f-to").onchange=e=>{f.to=e.target.value;loadShips()};
  $("#f-store").onchange=e=>{f.store=e.target.value;loadShips()};$("#f-sup").onchange=e=>{f.supplier=e.target.value;loadShips()};
  $("#f-sort").onchange=e=>{f.sort=e.target.value;loadShips()};
  await Promise.all([loadShips(),M()?loadSummaryUI():null]);
}
async function loadShips(opts){
  opts=opts||{};
  const p=shipParams();
  const d=await api("/api/shipments?"+p);S.ships=d;
  const el=$("#ship-list");if(!el)return;
  const ex=$("#f-export");if(ex)ex.href="/api/export.csv?"+p;
  const cnt=$("#sh-cnt");if(cnt)cnt.textContent=d.totals.count?"· "+d.totals.count:"";
  const openIds=new Set($$("#ship-list .ship.open").map(x=>+x.dataset.id));
  const filtered=!!(S.tab||S.q||S.f.period!=="all"||S.f.store||S.f.supplier);
  if(!d.rows.length){
    el.innerHTML=`<div class="empty">${ILL}<b>${filtered?"Ничего не найдено":"Партий пока нет"}</b>
      ${filtered?"Попробуйте другой фильтр или период":"Создайте первую партию — это займёт минуту"}
      ${!filtered?`<br><button class="pill" onclick="shipModal()">${I.plus}<span>Новая партия</span></button>`:""}</div>`;
  }else{
    el.innerHTML=d.rows.map((s,i)=>shipHtml(s,Math.min(i,10),openIds.has(s.id))).join("")+
     `<div class="ship" style="background:rgba(255,255,255,.03);--i:11"><div class="ship-top" style="cursor:default">
        <div class="who" style="font-size:13.5px;color:var(--muted)">Итого по фильтру: ${d.totals.count} парт. · ${d.totals.items} поз.${d.totals.closed?` · прибыль по ${d.totals.closed} закрытым ${money(d.totals.profit)}`:""}</div>
        ${M()?`<div class="money"><b>${money(d.totals.amount)}</b><div class="m2">оплачено ${money(d.totals.paid)} · остаток ${money(d.totals.balance)}</div></div>`:""}</div></div>`;
    bindShipActions();kick(el);
    if(opts.pop){const t=el.querySelector(`.ship[data-id="${opts.pop}"] .tag`);if(t)t.classList.add("pop")}
  }
  const sub=$("#hd-sub");
  if(sub){const live=d.rows.filter(s=>s.status==="shipping").length,n=new Date();
    sub.innerHTML=`${filtered?periodLabel(S.f.period,S.f.from,S.f.to):MONTH[n.getMonth()]+" "+n.getFullYear()} · ${d.totals.count} ${plural(d.totals.count,"партия","партии","партий")}`+
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
  const m=M();const chips=[];
  if(s.status==="shipping"&&s.days_transit!=null)chips.push(["в пути "+s.days_transit+" дн."]);
  if(s.status==="shipping"&&s.eta_date){const late=s.eta_date<todayISO();
    chips.push([late?"задержка — ждали "+dRu(s.eta_date):"ожидается "+dRu(s.eta_date),late?"warn":""])}
  if(s.status==="new")chips.push(["заказана "+dRu(s.date)]);
  if(s.status==="arrived"&&s.arrived_date)chips.push(["прибыла "+dRu(s.arrived_date),"ok"]);
  if(s.stores.length)chips.push(["магазин"+(s.stores.length>1?"ы":"")+" №"+s.stores.join(" · №")]);
  if(m&&s.pay_mode==="auto")chips.push([s.payments.length+" "+plural(s.payments.length,"платёж","платежа","платежей"),"info"]);
  if(m&&s.investors?.length)chips.push(["инвестор"+(s.investors.length>1?"ы":"")+": "+s.investors.map(v=>v.name).join(", "),"info"]);
  if(m&&s.profit!=null)chips.push(["закрыта · прибыль "+money(s.profit,s.currency),"ok"]);
  if(m&&s.rate&&s.currency!=="KGS")chips.push(["≈ "+money(s.amount*s.rate,"KGS")]);
  const pay=m&&s.amount?Math.min(100,Math.max(0,s.paid/s.amount*100)):0,over=m&&s.balance<-0.004;
  const m2=!m?"":s.status==="cancelled"?"не считается":over?`переплата <span class="v-rose">${money(-s.balance,s.currency)}</span>`
    :s.balance<=0.004?`<span class="v-green">оплачено полностью</span>`
    :`оплачено ${money(s.paid,s.currency)} · остаток <span class="v-amber">${money(s.balance,s.currency)}</span>`;
  return `<div class="ship spot${open?" open":""}" data-id="${s.id}" style="--i:${i}">
    <div class="ship-top" data-open>
      <div><div class="who">${esc(s.supplier_name)} <span class="chev">${I.chev}</span></div>
        <div class="meta">${dRu(s.date)} · ${s.items.length} поз.${s.track?" · трек "+esc(s.track):""}</div></div>
      <button class="tag t-${s.status}" data-st title="Сменить статус">${ST_RU[s.status]}</button>
      ${m?`<div class="money"><b>${money(s.amount,s.currency)}</b><div class="m2">${m2}</div></div>`:""}
      <div class="acts">
        ${m?`<button class="mini-btn" data-pay title="Записать платёж">${I.pay}</button>`:""}
        <button class="mini-btn" data-edit title="Редактировать">${I.edit}</button>
        <button class="mini-btn" data-more title="Ещё действия">${I.more}</button></div>
    </div>
    ${routeHtml(s)}
    ${chips.length?`<div class="chips">${chips.map(([t,c])=>`<span class="chip ${c||""}">${esc(t)}</span>`).join("")}</div>`:""}
    ${m&&s.status!=="cancelled"&&s.amount?`<div class="paybar${over?" over":""}" title="Оплачено ${Math.round(pay)}%"><i data-w="${pay.toFixed(1)}"></i></div>`:""}
    <div class="ship-x"><div>
      <div class="items-tbl"><table>
        <tr><th>Магазин</th><th>Товар</th><th class="num">Кол-во</th>${m?`<th class="num">Цена</th><th class="num">Сумма</th>`:""}</tr>
        ${s.items.map(it=>`<tr><td><span class="badge">№${esc(it.store_number)}</span></td><td>${esc(it.product)}</td>
          <td class="num">${it.qty?fmtN(it.qty)+" "+esc(it.unit||""):"—"}</td>
          ${m?`<td class="num">${it.unit_price?money(it.unit_price,s.currency):"—"}</td><td class="num"><b>${money(it.amount,s.currency)}</b></td>`:""}</tr>`).join("")}
      </table></div>
      ${m?`<div class="pays"><div class="pays-h"><span>Платежи по партии</span><button class="lnk" data-pay>+ Платёж</button></div>
        ${s.payments.length?s.payments.map(p=>`<div class="pay-line"><span class="d">${dRu(p.date)}</span>
            <span class="tag k-${p.kind}" style="cursor:default">${KIND_RU[p.kind]}</span>
            <span class="n">${esc([p.method,p.note].filter(Boolean).join(" · "))}</span>
            <b class="${p.kind==="refund"?"v-rose":""}">${p.kind==="refund"?"−":""}${money(p.amount,p.currency)}</b></div>`).join("")
          :`<div class="pay-line"><span class="empty-l">${s.paid?"Аванс "+money(s.paid,s.currency)+" введён вручную в карточке партии. Запишите первый платёж — дальше всё посчитается само.":"Платежей пока нет"}</span></div>`}
      </div>
      ${s.shares.length?`<div class="pays"><div class="pays-h"><span>Доли инвесторов от прибыли ${money(s.profit,s.currency)}</span><button class="lnk" data-profit>изменить</button></div>
        ${s.shares.map(x=>`<div class="pay-line"><span class="d">${x.kind==="pool"?"пул":"адресно"}</span><span class="n">${esc(x.name)} · ${esc(x.note)}</span><b class="v-green">${money(x.accrued,s.currency)}</b></div>`).join("")}</div>`
       :s.profit!=null?`<div class="pays"><div class="pays-h"><span>Партия закрыта, прибыль ${money(s.profit,s.currency)}</span><button class="lnk" data-profit>изменить</button></div><div class="pay-line"><span class="empty-l">Инвесторов у этой партии нет — вся прибыль ваша</span></div></div>`:""}`:""}
    </div></div></div>`;
}
function bindShipActions(){
  $$("#ship-list .ship[data-id]").forEach(el=>{
    const id=+el.dataset.id,s=S.ships.rows.find(x=>x.id===id);if(!s)return;
    el.querySelector("[data-open]").onclick=e=>{if(e.target.closest("button"))return;el.classList.toggle("open")};
    el.querySelector("[data-edit]").onclick=()=>shipModal(s);
    el.querySelectorAll("[data-pay]").forEach(b=>b.onclick=()=>payModal({supplier_id:s.supplier_id,shipment_id:s.id}));
    el.querySelectorAll("[data-profit]").forEach(b=>b.onclick=()=>profitModal(s));
    el.querySelector("[data-st]").onclick=e=>{e.stopPropagation();statusPop(e.currentTarget,s)};
    el.querySelector("[data-more]").onclick=e=>{e.stopPropagation();
      const items=[
        {l:"Дублировать (повторный заказ)",ic:I.copy,fn:()=>shipModal({...s,id:null,date:todayISO(),status:"new",sent_date:null,arrived_date:null,
          eta_date:null,track:"",prepaid:0,payments:[],pay_mode:"manual",paid:0,profit:null,closed_at:null,investors:[],shares:[],items:s.items.map(i=>({...i,id:null}))})},
        {l:s.items.length>1?"Разделить партию":"Разделить (нужно ≥ 2 товаров)",ic:I.split,fn:()=>s.items.length>1?splitModal(s):toast("В партии один товар — делить нечего","err")}];
      if(M())items.push(
        {l:s.profit!=null?"Прибыль по партии":"Закрыть партию — ввести прибыль",ic:I.flag,fn:()=>profitModal(s)},
        {l:"Вложение инвестора в эту партию",ic:I.coins,fn:()=>investModal({shipment_id:s.id})},
        {l:"Удалить",ic:I.trash,danger:true,fn:async()=>{
          if(await confirmBox("Удалить партию?",`${s.supplier_name}, ${dRu(s.date)}, ${s.items.length} поз.${M()?" на "+money(s.amount,s.currency):""}. Партия будет скрыта из списков.`,true)){
            await api("/api/shipments/"+id,{method:"DELETE"});toast("Партия удалена","ok");refreshAfterPay()}}});
      menuPop(e.currentTarget,items)};
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
      toast("Статус: "+ST_RU[b.dataset.v],"ok");loadShips({pop:s.id});if(M())loadSummaryUI()}catch(e){toast(e.message,"err")}});
  setTimeout(()=>document.addEventListener("click",function h(e){if(!pop.contains(e.target)){hidePop();document.removeEventListener("click",h)}}),0);
}

/* ═══════════════════ плитки и правая колонка ═══════════════════ */
function kpiHtml(list){
  return list.map(([l,v,c,dt,ser,col],i)=>`<div class="glass kpi spot" style="--i:${i}"><div class="lab">${l}</div>
    <div class="val ${c||""}" data-v="${v}" data-k="${esc(l)}">${money(0)}</div><div class="dt">${dt}</div>
    ${ser?`<div class="kpi-r">${sparkSvg(ser,col)}${deltaHtml(ser)}</div>`:""}</div>`).join("");
}
function runCounters(root){
  root.querySelectorAll(".val[data-v]").forEach(el=>{const k=el.dataset.k,to=+el.dataset.v;counter(el,to,undefined,S.kpiPrev[k]);S.kpiPrev[k]=to});
}
async function loadSummaryUI(range){
  if(!M())return;
  const p=new URLSearchParams();if(range&&range[0])p.set("from",range[0]);if(range&&range[1])p.set("to",range[1]);
  const d=await api("/api/summary?"+p);S.sum=d;const t=d.tiles,sr=d.series;const per=!!(range&&(range[0]||range[1]));
  const k=$("#kpis");if(!k)return;
  k.innerHTML=kpiHtml([
    ["Заказано"+(per?" за период":""),t.ordered,"",`${t.ordered_items} ${plural(t.ordered_items,"позиция","позиции","позиций")} · ${t.ordered_count} ${plural(t.ordered_count,"партия","партии","партий")}`,per?null:sr.ordered,"#6C8CFF"],
    ["Отдано поставщикам"+(per?" за период":""),t.paid,"v-cyan",t.ordered?Math.round(t.paid/t.ordered*100)+"% от суммы закупок":"—",per?null:sr.paid,"#3ED8D0"],
    ["Остаток к оплате",t.debt_total,"v-amber",t.debt_suppliers?`${t.debt_suppliers} ${plural(t.debt_suppliers,"поставщик ждёт","поставщика ждут","поставщиков ждут")} доплату`:"долгов нет",per?null:sr.balance,"#FFB65C"],
    ["Сейчас в пути",t.transit,"v-green",t.transit_count?`${t.transit_count} парт. · дольше всех ${t.transit_max_days} дн.`:"ничего не едет",per?null:sr.sent,"#57E39B"],
  ]);
  runCounters(k);
  const a=$("#aside");if(!a)return;
  a.innerHTML=asideHtml(d);kick(a);
}
function asideHtml(d){
  const t=d.tiles,mx=Math.max(...d.months.map(m=>m.total),1),iv=d.investors;
  return `
   ${iv.count?`<div class="glass card spot"><h3>Инвесторы · к выплате <button class="lnk" data-go="investors">все →</button></h3>
     ${iv.top.slice(0,3).map(x=>{const pct=x.accrued?Math.min(100,x.paid_profit/x.accrued*100):0;return `<div class="inv-row">${ringSvg(pct,x.due>0.004?"#FFB65C":"#57E39B",44,5)}
       <div class="inv-t"><b>${esc(x.name)}</b><span>вложено ${money(x.invested)} · начислено ${money(x.accrued)}</span></div>
       <div class="inv-v ${x.due>0.004?"v-amber":"v-green"}">${money(x.due)}</div></div>`}).join("")}
     <div class="stat tot"><span class="l">Обязательства</span><span class="v v-amber">${money(iv.due)}</span></div></div>`:""}
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
  const isNew=!s||!s.id,m=M();
  const sup=activeSuppliers();
  if(!sup.length&&isNew){toast("Сначала добавьте поставщика (раздел «Поставщики»)","err");return}
  if(!activeStores().length&&isNew){toast("Сначала добавьте магазин (раздел «Магазины»)","err");return}
  ITEMS=(s?.items||[{}]).map(i=>({...i}));if(!ITEMS.length)ITEMS=[{}];
  const auto=s?.pay_mode==="auto";
  const defCur=s?.currency||S.settings.currency||"USD",defRate=s?.rate||(isNew?S.settings.rate:null)||"";
  openModal(`<div class="mh"><h2>${isNew?"Новая партия":"Партия — "+esc(s.supplier_name)}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c3"><label>Дата заказа</label><input type="date" id="f-date" value="${s?.date||todayISO()}"></div>
    <div class="fg c6"><label>Поставщик</label><select id="f-sup">
      ${sup.map(p=>`<option value="${p.id}" ${s?.supplier_id===p.id?"selected":""}>${esc(p.name)}</option>`).join("")}</select></div>
    ${m?`<div class="fg c3"><label>Валюта</label><select id="f-cur">
      ${["USD","CNY","KGS"].map(c=>`<option ${defCur===c?"selected":""}>${c}</option>`).join("")}</select></div>`:`<div class="fg c3"></div>`}
    <div class="fg c3"><label>Статус</label><select id="f-st">
      ${Object.entries(ST_RU).map(([v,l])=>`<option value="${v}" ${((s?.status)||"new")===v?"selected":""}>${l}</option>`).join("")}</select></div>
    <div class="fg c3"><label>Отправлена</label><input type="date" id="f-sent" value="${s?.sent_date||""}"></div>
    <div class="fg c3"><label>Ожидается</label><input type="date" id="f-eta" value="${s?.eta_date||""}"></div>
    <div class="fg c3"><label>Прибыла</label><input type="date" id="f-arr" value="${s?.arrived_date||""}"></div>
    <div class="fg c6"><label>Трек / накладная</label><input id="f-track" value="${esc(s?.track||"")}" placeholder="SF7742019"></div>
    ${m?`<div class="fg c3"><label>${auto?"Оплачено (по платежам)":"Аванс"}</label><input type="number" step="0.01" id="f-pre" value="${auto?s.paid:(s?.prepaid||"")}" placeholder="0" ${auto?"disabled":""}>
      ${auto?`<div class="hint">считается по ${s.payments.length} ${plural(s.payments.length,"платежу","платежам","платежам")} — менять в разделе «Платежи»</div>`:`<div class="hint">или запишите платёж — тогда считается само</div>`}</div>
    <div class="fg c3"><label>Курс к сому</label><input type="number" step="0.01" id="f-rate" value="${defRate}" placeholder="—"></div>`:`<div class="fg c6"></div>`}
    <div class="fg c12"><label>Комментарий</label><input id="f-note" value="${esc(s?.note||"")}"></div>
   </div>
   <div class="itm-head"><h4>Товары в партии</h4><button class="ghost sm" style="margin-left:auto" id="f-add-itm">${I.plus}<span>Товар</span></button></div>
   <div class="itm-cols${m?"":" hm"}"><span>Магазин</span><span>Наименование</span><span class="itm-qty">Кол-во</span><span class="itm-unitcol">Ед.</span>${m?`<span class="itm-qty">Цена</span><span>Сумма</span>`:""}<span></span></div>
   <div id="f-items" class="${m?"":"hm"}"></div>
   <div class="msum"><span>Позиций: <b id="m-cnt">0</b></span>${m?`<span>Сумма: <b id="m-sum">0</b></span><span>Остаток: <b id="m-bal">0</b></span><span id="m-kgs"></span>`:""}</div>
   </div>
   <div class="mf"><span class="hint">⌘S — сохранить</span><button class="ghost" data-x>Отмена</button>
     ${isNew?'<button class="ghost" id="f-save-more">Сохранить и ещё одну</button>':""}
     <button class="pill" id="f-save" data-save>Сохранить</button></div>`);
  renderItems();
  $("#f-add-itm").onclick=()=>{ITEMS.push({});renderItems();const last=$("#f-items .itm-row:last-of-type");last?.querySelector(".i-prod")?.focus()};
  if(m){$("#f-pre").oninput=recalc;$("#f-cur").onchange=recalc;$("#f-rate").oninput=recalc}
  $("#f-st").onchange=()=>{const v=$("#f-st").value;
    if(v==="shipping"&&!$("#f-sent").value)$("#f-sent").value=todayISO();
    if(v==="arrived"&&!$("#f-arr").value)$("#f-arr").value=todayISO()};
  const save=async()=>{
    const body={date:$("#f-date").value,supplier_id:+$("#f-sup").value,
      status:$("#f-st").value,sent_date:$("#f-sent").value||null,eta_date:$("#f-eta").value||null,
      arrived_date:$("#f-arr").value||null,track:$("#f-track").value,note:$("#f-note").value,
      items:ITEMS.filter(i=>i.product||i.amount).map(i=>({id:i.id||null,store_id:+i.store_id||null,product:(i.product||"").trim(),
        qty:+i.qty||null,unit:i.unit||"шт",unit_price:+i.unit_price||null,amount:+i.amount||0,note:i.note||""}))};
    if(m){body.currency=$("#f-cur").value;body.rate=+($("#f-rate").value||0)||null;if(!auto)body.prepaid=+($("#f-pre").value||0)}
    await api(isNew?"/api/shipments":"/api/shipments/"+s.id,{method:isNew?"POST":"PATCH",body});
    toast(isNew?"Партия создана":"Сохранено","ok");
    refreshAfterPay();
  };
  $("#f-save").onclick=async()=>{if(await withBusy($("#f-save"),save))closeModal()};
  if(isNew)$("#f-save-more").onclick=async()=>{if(await withBusy($("#f-save-more"),save))shipModal()};
}
function renderItems(){
  const stores=activeStores(),m=M();
  const defStore=ITEMS.find(i=>i.store_id)?.store_id||stores[0]?.id;
  $("#f-items").innerHTML=ITEMS.map((i,n)=>`<div class="itm-row" data-n="${n}">
    <select class="i-store">${stores.map(st=>`<option value="${st.id}" ${(+i.store_id||defStore)===st.id?"selected":""}>№${esc(st.number)}</option>`).join("")}</select>
    <input class="i-prod" value="${esc(i.product||"")}" placeholder="Наименование товара" list="prod-hints">
    <input class="i-qty itm-qty" type="number" step="0.01" value="${i.qty||""}" placeholder="0">
    <select class="i-unit itm-unitcol">${["шт","кор","кг","м","компл"].map(u=>`<option ${(i.unit||"шт")===u?"selected":""}>${u}</option>`).join("")}</select>
    ${m?`<input class="i-price itm-qty" type="number" step="0.01" value="${i.unit_price||""}" placeholder="0">
    <input class="i-amount" type="number" step="0.01" value="${i.amount||""}" placeholder="0">`:""}
    <button class="itm-del" title="Убрать" type="button">×</button></div>`).join("")+
    `<datalist id="prod-hints">${[...new Set((S.ships?.rows||[]).flatMap(s=>s.items.map(i=>i.product)))].slice(0,80).map(p=>`<option value="${esc(p)}">`).join("")}</datalist>`;
  $$("#f-items .itm-row").forEach(row=>{
    const n=+row.dataset.n,i=ITEMS[n];
    const sync=()=>{i.store_id=row.querySelector(".i-store").value;i.product=row.querySelector(".i-prod").value;
      i.qty=row.querySelector(".i-qty").value;i.unit=row.querySelector(".i-unit").value;
      if(m){i.unit_price=row.querySelector(".i-price").value;i.amount=row.querySelector(".i-amount").value}recalc()};
    row.querySelectorAll("input,select").forEach(el=>el.addEventListener("input",()=>{
      if(m&&(el.classList.contains("i-qty")||el.classList.contains("i-price"))){
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
  if($("#m-cnt"))$("#m-cnt").textContent=cnt;
  if($("#m-sum")){$("#m-sum").textContent=money(sum,cur);
    $("#m-bal").textContent=money(sum-(+$("#f-pre")?.value||0),cur);
    const rate=+$("#f-rate")?.value;$("#m-kgs").textContent=rate&&cur!=="KGS"?"≈ "+money(sum*rate,"KGS"):""}
}
/* разделить партию */
function splitModal(s){
  const m=M(),auto=m&&s.pay_mode==="auto";
  openModal(`<div class="mh"><div><h2>Разделить партию</h2><div class="meta">${esc(s.supplier_name)} · ${dRu(s.date)}${m?" · "+money(s.amount,s.currency):""}</div></div><button class="x" data-x>×</button></div>
   <div class="mb">
    <div class="hint" style="margin-bottom:10px">Отметьте товары, которые уходят в новую партию. У неё будет тот же поставщик и дата заказа, свой статус.</div>
    <div class="pick" id="sp-items">${s.items.map(i=>`<label class="pick-row"><input type="checkbox" value="${i.id}"><span class="badge">№${esc(i.store_number)}</span><span class="pk-n">${esc(i.product)}${i.qty?` <small>${fmtN(i.qty)} ${esc(i.unit||"")}</small>`:""}</span>${m?`<b>${money(i.amount,s.currency)}</b>`:""}</label>`).join("")}</div>
    <div class="frm" style="margin-top:14px">
      <div class="fg c6"><label>Статус новой партии</label><select id="sp-st">${Object.entries(ST_RU).map(([v,l])=>`<option value="${v}" ${v===s.status?"selected":""}>${l}</option>`).join("")}</select></div>
      ${m&&!auto?`<div class="fg c6"><label>Аванс новой партии</label><input type="number" step="0.01" id="sp-pre"><div class="hint" id="sp-pre-h"></div></div>`:""}
    </div>
    ${auto?`<div class="hint" style="margin:14px 0 8px">По партии есть платежи. Отметьте, какие перенести на новую партию (целиком) — остальные останутся на исходной:</div>
      <div class="pick" id="sp-pays">${s.payments.map(p=>`<label class="pick-row"><input type="checkbox" value="${p.id}"><span class="tag k-${p.kind}" style="cursor:default">${KIND_RU[p.kind]}</span><span class="pk-n">${dRu(p.date)}${p.note?" · "+esc(p.note):""}</span><b>${p.kind==="refund"?"−":""}${money(p.amount,p.currency)}</b></label>`).join("")}</div>`:""}
    <div class="split-sum" id="sp-sum"></div>
   </div>
   <div class="mf"><button class="ghost" data-x>Отмена</button><button class="pill" id="sp-ok" data-save>Разделить</button></div>`,"mid");
  const sel=()=>[...$$("#sp-items input:checked")].map(x=>+x.value);
  const rc=()=>{
    const ids=sel();
    if(!m){$("#sp-sum").innerHTML=`<div><span>Остаётся в исходной</span><b>${s.items.length-ids.length} поз.</b></div><div><span>Уходит в новую</span><b>${ids.length} поз.</b></div>`;
      $("#sp-ok").disabled=!ids.length||ids.length===s.items.length;return}
    const msum=s.items.filter(i=>ids.includes(i.id)).reduce((a,i)=>a+(i.amount||0),0),osum=s.amount-msum;
    let pn=0,po=0;
    if(auto){const pids=[...$$("#sp-pays input:checked")].map(x=>+x.value);
      pn=s.payments.filter(p=>pids.includes(p.id)).reduce((a,p)=>a+(p.kind==="refund"?-p.amount:p.amount),0);po=s.paid-pn}
    else{const pre=$("#sp-pre");const prop=s.amount?Math.round(s.paid*msum/s.amount*100)/100:0;
      if(!pre.dataset.touched)pre.value=prop||"";pn=+pre.value||0;po=s.paid-pn;
      $("#sp-pre-h").textContent=`пропорционально: ${money(prop,s.currency)} · в исходной останется ${money(po,s.currency)}`}
    $("#sp-sum").innerHTML=`<div><span>Остаётся в исходной</span><b>${s.items.length-ids.length} поз. · ${money(osum,s.currency)}</b><small>оплачено ${money(po,s.currency)} · остаток ${money(osum-po,s.currency)}</small></div>
      <div><span>Уходит в новую</span><b>${ids.length} поз. · ${money(msum,s.currency)}</b><small>оплачено ${money(pn,s.currency)} · остаток ${money(msum-pn,s.currency)}</small></div>`;
    $("#sp-ok").disabled=!ids.length||ids.length===s.items.length;};
  $$("#sp-items input, #sp-pays input").forEach(i=>i.onchange=rc);
  if(m&&!auto)$("#sp-pre").oninput=e=>{e.target.dataset.touched=1;rc()};
  rc();
  $("#sp-ok").onclick=async()=>{
    const ok=await withBusy($("#sp-ok"),async()=>{
      const body={item_ids:sel(),status:$("#sp-st").value};
      if(auto)body.payment_ids=[...$$("#sp-pays input:checked")].map(x=>+x.value);else if(m)body.prepaid_new=+$("#sp-pre").value||0;
      const r=await api(`/api/shipments/${s.id}/split`,{method:"POST",body});
      toast(m?`Партия разделена: новая на ${money(r.new.amount,r.new.currency)}, в исходной ${money(r.old.amount,r.old.currency)}`:"Партия разделена","ok")});
    if(ok){closeModal();refreshAfterPay()}
  };
}
/* закрыть партию — прибыль */
function profitModal(s){
  const closed=s.profit!=null;
  openModal(`<div class="mh"><div><h2>${closed?"Прибыль по партии":"Закрыть партию"}</h2><div class="meta">${esc(s.supplier_name)} · ${dRu(s.date)} · ${money(s.amount,s.currency)}</div></div><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
     <div class="fg c6"><label>Прибыль по партии</label><input type="number" step="0.01" id="pf-profit" value="${closed?s.profit:""}" placeholder="0" autofocus>
       <div class="hint">одним числом, когда товар распродан — от неё считаются доли инвесторов</div></div>
     <div class="fg c6"><label>Дата закрытия</label><input type="date" id="pf-date" value="${s.closed_at||todayISO()}"></div>
   </div>
   <div class="hint" style="margin-top:14px">${s.investors.length
     ?"Адресные вложения в эту партию: "+s.investors.map(v=>esc(v.name)+" — "+money(v.amount)+" ("+termsRu(v)+")").join("; ")
     :"Адресных вложений в партию нет — прибыль пойдёт в общий пул инвесторов, если он есть. Иначе вся прибыль ваша."}</div>
   </div>
   <div class="mf">${closed?`<button class="ghost" id="pf-reopen">Открыть заново</button>`:""}<button class="ghost" data-x>Отмена</button><button class="pill" id="pf-ok" data-save>${closed?"Сохранить":"Закрыть партию"}</button></div>`,"mid");
  $("#pf-ok").onclick=async()=>{
    const ok=await withBusy($("#pf-ok"),async()=>{const v=$("#pf-profit").value;if(v==="")throw new Error("Укажите прибыль по партии");
      await api("/api/shipments/"+s.id,{method:"PATCH",body:{profit:+v,closed_at:$("#pf-date").value||null}});toast(closed?"Прибыль изменена":"Партия закрыта, доли начислены","ok")});
    if(ok){closeModal();refreshAfterPay()}};
  if(closed)$("#pf-reopen").onclick=async()=>{try{await api("/api/shipments/"+s.id,{method:"PATCH",body:{profit:null}});toast("Партия открыта заново","ok");closeModal();refreshAfterPay()}catch(e){toast(e.message,"err")}};
}

/* ═══════════════════ ПЛАТЕЖИ ═══════════════════ */
function refreshAfterPay(){
  if(S.section==="ships"){loadShips();loadSummaryUI();loadRefs()}
  else if(S.section==="payments"){loadPayments();loadPayKpis()}
  else if(S.section==="partners")loadPartners();
  else if(S.section==="investors")loadInvestors();
  else if(S.section==="stores")loadStores();
  else if(S.section==="summary")renderSummary();
}
async function renderPayments(){
  await loadRefs();
  const sup=S.partners.filter(p=>p.is_supplier||p.shipments||p.payments);
  $("#main").innerHTML=`<div class="view">${headHtml("Платежи <span>поставщикам</span>",skSub(),`
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
    <div class="fg c3"><label>Валюта</label><select id="y-cur">${["USD","CNY","KGS"].map(c=>`<option ${((p?.currency)||pre.currency||S.settings.currency||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
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
  $("#main").innerHTML=`<div class="view">${headHtml("Поставщики <span>и партнёры</span>",skSub(),
    `<button class="pill" id="add-p">${I.plus}<span>Контрагент</span></button>${avatarHtml()}`)}
    <div class="glass panel" style="--i:1"><div class="list-wrap" id="p-list">${skRows(3)}</div></div></div>`;
  $("#add-p").onclick=()=>partnerModal();
  await loadPartners();
}
async function loadPartners(){
  await loadRefs();const rows=S.partners,el=$("#p-list"),m=M();if(!el)return;
  const sub=$("#hd-sub");if(sub)sub.textContent=`${rows.length} ${plural(rows.length,"контрагент","контрагента","контрагентов")}`+(m?` · долг всем ${money(rows.reduce((a,p)=>a+Math.max(0,p.debt||0),0))}`:"");
  el.innerHTML=rows.length?`<table class="list-tbl"><thead><tr><th>Название</th><th>Тип</th><th>Город · контакт</th><th class="num">Партий</th>
      ${m?`<th class="num">Оборот</th><th>Отдано</th><th class="num">Долг</th><th class="num">В пути</th>`:""}<th></th></tr></thead><tbody>
    ${rows.map((p,i)=>`<tr class="clk ${p.active?"":"inactive"}" data-id="${p.id}" style="--i:${Math.min(i,12)}">
      <td><b>${esc(p.name)}</b>${p.active?"":" <span class='chip'>скрыт</span>"}</td>
      <td style="color:var(--muted)">${[p.is_supplier?"поставщик":"",p.is_investor?"инвестор":""].filter(Boolean).join(" + ")||"—"}${m&&p.is_investor&&p.inv_due>0.004?`<div class="meta v-amber">к выплате ${money(p.inv_due)}</div>`:""}</td>
      <td style="color:var(--muted)">${esc([p.city,p.contact].filter(Boolean).join(" · "))||"—"}</td>
      <td class="num">${p.shipments}</td>${m?`<td class="num">${money(p.total)}</td>
      <td><span>${money(p.paid)}</span><div class="pb"><i data-w="${p.total?Math.min(100,Math.max(0,p.paid/p.total*100)).toFixed(0):0}"></i></div></td>
      <td class="num" style="color:${p.debt>0.004?"var(--amber)":p.debt<-0.004?"var(--green)":"var(--dim)"}">${p.debt<-0.004?"+":""}${money(Math.abs(p.debt))}</td>
      <td class="num" style="color:${p.transit?"var(--green)":"var(--dim)"}">${money(p.transit)}</td>`:""}
      <td><div class="acts">${m?`<button class="mini-btn" data-pay title="Записать платёж">${I.pay}</button>`:""}<button class="mini-btn" data-edit title="Изменить">${I.edit}</button>${m?`<button class="mini-btn del" data-del title="Удалить">${I.trash}</button>`:""}</div></td>
    </tr>`).join("")}</tbody></table>`
    :`<div class="empty">${ILL}<b>Контрагентов пока нет</b>Добавьте первого поставщика<br><button class="pill" onclick="partnerModal()">${I.plus}<span>Контрагент</span></button></div>`;
  kick(el);
  el.querySelectorAll("tr[data-id]").forEach(tr=>{
    const p=rows.find(x=>x.id===+tr.dataset.id);
    tr.onclick=e=>{if(e.target.closest("button"))return;m?partnerCard(p.id):partnerModal(p)};
    tr.querySelector("[data-edit]").onclick=()=>partnerModal(p);
    if(m){tr.querySelector("[data-pay]").onclick=()=>payModal({supplier_id:p.id});
    tr.querySelector("[data-del]").onclick=async()=>{
      if(await confirmBox("Удалить контрагента?",p.name+(p.shipments||p.payments?" — у него есть партии или платежи, он будет скрыт с сохранением истории":""),true)){
        const r=await api("/api/partners/"+p.id,{method:"DELETE"});toast(r.msg||"Удалено","ok");loadPartners()}}}
  });
}
async function partnerCard(pid,tab){
  tab=tab||"ships";
  let p;try{p=await api("/api/partners/"+pid)}catch(e){toast(e.message,"err");return}
  const pct=p.total?Math.min(100,Math.max(0,p.paid/p.total*100)):0;
  const types=[p.is_supplier?"поставщик":"",p.is_investor?"инвестор":""].filter(Boolean).join(" + ");
  openModal(`<div class="mh"><div><h2>${esc(p.name)}</h2><div class="meta">${esc([types,p.city,p.contact].filter(Boolean).join(" · "))}</div></div>
     <div class="mh-acts">${p.is_investor?`<button class="ghost sm" id="pc-inv" title="Карточка инвестора">${I.coins}<span>Инвестор</span></button>`:""}<button class="ghost sm" id="pc-pay">${I.pay}<span>Платёж</span></button><button class="ghost sm" id="pc-edit" title="Изменить">${I.edit}</button><button class="x" data-x>×</button></div></div>
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
  if($("#pc-inv"))$("#pc-inv").onclick=()=>investorCard(pid);
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
    <div class="fg c6"><label>Валюта по умолчанию</label><select id="p-cur">${["USD","CNY","KGS"].map(c=>`<option ${((p?.currency)||S.settings.currency||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Комментарий (условия работы)</label><input id="p-note" value="${esc(p?.note||"")}"></div>
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
  await loadRefs();const rows=S.stores,el=$("#s-list"),m=M();if(!el)return;
  const mx=Math.max(...rows.map(s=>s.total||0),1);
  el.innerHTML=rows.length?`<table class="list-tbl"><thead><tr><th>Номер</th><th>Название</th><th class="num">Партий</th><th class="num">Позиций</th>
      ${m?`<th>Закуплено</th><th class="num">В пути</th>`:""}<th></th></tr></thead><tbody>
    ${rows.map((s,i)=>`<tr class="${s.active?"":"inactive"}" data-id="${s.id}" style="--i:${Math.min(i,12)}">
      <td><span class="badge">№${esc(s.number)}</span></td><td><b>${esc(s.name||"—")}</b>${s.active?"":" <span class='chip'>скрыт</span>"}</td>
      <td class="num">${s.shipments}</td><td class="num">${s.items}</td>
      ${m?`<td><span>${money(s.total)}</span><div class="pb"><i data-w="${Math.round(s.total/mx*100)}"></i></div></td>
      <td class="num" style="color:${s.transit?"var(--green)":"var(--dim)"}">${money(s.transit)}</td>`:""}
      <td><div class="acts"><button class="mini-btn" data-edit title="Изменить">${I.edit}</button>${m?`<button class="mini-btn del" data-del title="Удалить">${I.trash}</button>`:""}</div></td>
    </tr>`).join("")}</tbody></table>`
    :`<div class="empty">${ILL}<b>Магазинов пока нет</b>Добавьте первый — номер и название<br><button class="pill" onclick="storeModal()">${I.plus}<span>Магазин</span></button></div>`;
  kick(el);
  el.querySelectorAll("tr[data-id]").forEach(tr=>{
    const s=rows.find(x=>x.id===+tr.dataset.id);
    tr.querySelector("[data-edit]").onclick=()=>storeModal(s);
    if(m)tr.querySelector("[data-del]").onclick=async()=>{
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
  $("#main").innerHTML=`<div class="view">${headHtml("Инвесторы <span>и доли</span>",skSub(),`
     <button class="ghost" id="add-po">${I.pay}<span>Выплата</span></button>
     <button class="pill" id="add-inv">${I.plus}<span>Вложение</span></button>${avatarHtml()}`)}
    <div class="kpis" id="ikpis">${skKpis()}</div>
    <div class="glass panel" style="--i:1"><div class="list-wrap" id="i-list">${skRows(3)}</div></div></div>`;
  $("#add-inv").onclick=()=>investModal();$("#add-po").onclick=()=>payoutModal();
  await loadInvestors();
}
async function loadInvestors(){
  const d=await api("/api/investors");S.inv=d;const el=$("#i-list");if(!el)return;const t=d.totals,rows=d.rows;
  const k=$("#ikpis");
  k.innerHTML=kpiHtml([
    ["Вложено",t.invested,"",`${rows.length} ${plural(rows.length,"инвестор","инвестора","инвесторов")}${t.pool_total?" · общий пул "+money(t.pool_total):""}`],
    ["Начислено",t.accrued,"v-cyan",t.closed_count?`прибыль ${t.closed_count} закрыт${plural(t.closed_count,"ой партии","ых партий","ых партий")}: ${money(t.closed_profit)}`:"закрытых партий пока нет"],
    ["Выплачено долей",t.paid_profit,"v-green",`тело вложений возвращено ${money(t.paid_principal)}`],
    ["К выплате",t.due,"v-amber",t.due>0.004?"начислено минус выплачено":"всё выплачено"],
  ]);runCounters(k);
  const sub=$("#hd-sub");if(sub)sub.textContent=`${rows.length} ${plural(rows.length,"инвестор","инвестора","инвесторов")} · к выплате ${money(t.due)} · у нас их денег ${money(t.principal_out)}`;
  el.innerHTML=rows.length?`<table class="list-tbl"><thead><tr><th>Имя</th><th class="num">Вложено</th><th>Условие</th><th class="num">Начислено</th><th class="num">Выплачено</th><th class="num">К выплате</th><th></th></tr></thead><tbody>
    ${rows.map((p,i)=>`<tr class="clk ${p.active?"":"inactive"}" data-id="${p.id}" style="--i:${Math.min(i,12)}">
      <td><b>${esc(p.name)}</b>${p.contact?`<div class="meta">${esc(p.contact)}</div>`:""}</td>
      <td class="num">${money(p.invested)}${p.principal_out<p.invested-0.004?`<div class="meta">у нас ${money(p.principal_out)}</div>`:""}</td>
      <td style="color:var(--muted)">${p.terms?termsRu(p):"—"}${p.pool_share?`<div class="meta">пул ${p.pool_share}%</div>`:""}${p.open_count?`<div class="meta">${p.open_count} ${plural(p.open_count,"партия","партии","партий")} ещё не закрыт${p.open_count===1?"а":"ы"}</div>`:""}</td>
      <td class="num v-cyan">${money(p.accrued)}</td>
      <td class="num">${money(p.paid_profit)}<div class="pb" style="margin-left:auto"><i data-w="${p.accrued?Math.min(100,p.paid_profit/p.accrued*100).toFixed(0):0}"></i></div></td>
      <td class="num" style="color:${p.due>0.004?"var(--amber)":"var(--green)"}"><b>${money(p.due)}</b></td>
      <td><div class="acts"><button class="mini-btn" data-inv title="Вложение">${I.coins}</button><button class="mini-btn" data-po title="Выплата">${I.pay}</button><a class="mini-btn" data-rep href="/api/investors/${p.id}/report" target="_blank" title="Отчёт инвестору">${I.doc}</a></div></td>
    </tr>`).join("")}</tbody></table>`
    :`<div class="empty">${ILL}<b>Инвесторов пока нет</b>Запишите первое вложение — контрагент станет инвестором автоматически<br><button class="pill" onclick="investModal()">${I.plus}<span>Вложение</span></button></div>`;
  kick(el);
  el.querySelectorAll("tr[data-id]").forEach(tr=>{
    const p=rows.find(x=>x.id===+tr.dataset.id);
    tr.onclick=e=>{if(e.target.closest("button,a"))return;investorCard(p.id)};
    tr.querySelector("[data-inv]").onclick=()=>investModal({investor_id:p.id});
    tr.querySelector("[data-po]").onclick=()=>payoutModal({investor_id:p.id});
  });
}
async function investorCard(iid,tab){
  tab=tab||"inv";
  let p;try{p=await api("/api/investors/"+iid)}catch(e){toast(e.message,"err");return}
  const pct=p.accrued?Math.min(100,Math.max(0,p.paid_profit/p.accrued*100)):0;
  openModal(`<div class="mh"><div><h2>${esc(p.name)}</h2><div class="meta">инвестор${p.contact?" · "+esc(p.contact):""}${p.note?" · "+esc(p.note):""}</div></div>
     <div class="mh-acts"><a class="ghost sm" href="/api/investors/${iid}/report" target="_blank">${I.doc}<span>Отчёт</span></a><button class="ghost sm" id="ic-inv">${I.coins}<span>Вложение</span></button><button class="ghost sm" id="ic-po">${I.pay}<span>Выплата</span></button><button class="x" data-x>×</button></div></div>
   <div class="mb">
     <div class="pc-stats"><div class="pc-ring">${ringSvg(pct,p.due>0.004?"#FFB65C":"#57E39B",78,7)}<div class="pc-ring-l"><b>${Math.round(pct)}%</b><span>выплачено</span></div></div>
       <div class="pc-grid">
         <div class="pc-st"><span>Вложено</span><b>${money(p.invested)}</b><div class="meta">у нас ${money(p.principal_out)}</div></div>
         <div class="pc-st"><span>Начислено</span><b class="v-cyan">${money(p.accrued)}</b></div>
         <div class="pc-st"><span>Выплачено долей</span><b class="v-green">${money(p.paid_profit)}</b></div>
         <div class="pc-st"><span>К выплате</span><b class="${p.due>0.004?"v-amber":"v-green"}">${money(p.due)}</b></div></div></div>
     <div class="tabs" id="ic-tabs" style="margin-left:0;display:inline-flex"><div class="tab${tab==="inv"?" on":""}" data-t="inv">Вложения · ${p.investments.length}</div><div class="tab${tab==="po"?" on":""}" data-t="po">Выплаты · ${p.payouts.length}</div></div>
     <div class="pc-list" id="ic-body"></div></div>`,"wide");
  kick($("#modal"));
  const again=()=>{investorCard(iid,tab);refreshAfterPay()};
  const body=()=>{const b=$("#ic-body");
    if(tab==="inv"){
      b.innerHTML=p.investments.length?p.investments.map((v,i)=>invRowHtml(v,i)).join(""):`<div class="empty"><b>Вложений нет</b></div>`;
      b.querySelectorAll(".pay-row[data-id]").forEach(el=>{const v=p.investments.find(x=>x.id===+el.dataset.id);
        el.querySelector("[data-edit]").onclick=()=>investModal({},v,again);
        el.querySelector("[data-del]").onclick=async()=>{if(await confirmBox("Удалить вложение?",`${dRu(v.date)}, ${money(v.amount,v.currency)}. Начисления пересчитаются.`,true)){try{await api("/api/investments/"+v.id,{method:"DELETE"});toast("Вложение удалено","ok");again()}catch(e){toast(e.message,"err")}}}});
    }else{
      b.innerHTML=p.payouts.length?p.payouts.map((o,i)=>poRowHtml(o,i)).join(""):`<div class="empty"><b>Выплат ещё не было</b></div>`;
      b.querySelectorAll(".pay-row[data-id]").forEach(el=>{const o=p.payouts.find(x=>x.id===+el.dataset.id);
        el.querySelector("[data-edit]").onclick=()=>payoutModal({},o,again);
        el.querySelector("[data-del]").onclick=async()=>{if(await confirmBox("Удалить выплату?",`${dRu(o.date)}, ${money(o.amount,o.currency)}.`,true)){try{await api("/api/payouts/"+o.id,{method:"DELETE"});toast("Выплата удалена","ok");again()}catch(e){toast(e.message,"err")}}}});
    }};
  body();
  $$("#ic-tabs .tab").forEach(t=>t.onclick=()=>{tab=t.dataset.t;$$("#ic-tabs .tab").forEach(x=>x.classList.toggle("on",x===t));body()});
  $("#ic-inv").onclick=()=>investModal({investor_id:iid},null,again);
  $("#ic-po").onclick=()=>payoutModal({investor_id:iid},null,again);
}
function invRowHtml(v,i){
  const[y,m,dd]=v.date.split("-");
  const target=v.shipment_id?`партия от ${dRu(v.ship_date)} · ${esc(v.ship_supplier||"")} · ${money(v.ship_amount)}${v.ship_deleted?" (удалена)":v.ship_profit!=null?" · закрыта, прибыль "+money(v.ship_profit):" · ещё не закрыта"}`:"общий пул";
  return `<div class="pay-row spot" data-id="${v.id}" style="--i:${i}">
    <div class="pd"><b>${+dd}</b><span>${MON[+m-1]} ${y.slice(2)}</span></div>
    <div class="pw"><div class="who">${money(v.amount,v.currency)} <span class="tag ${v.terms==="fixed"?"k-prepay":"k-final"}" style="cursor:default;margin-left:6px">${termsRu(v)}</span></div><div class="meta">${target}${v.end_date?" · возвращено "+dRu(v.end_date):""}${v.note?" · "+esc(v.note):""}</div></div>
    <div class="money" style="min-width:150px"><b class="v-cyan">${money(v.accrued,v.currency)}</b><div class="m2">${esc(v.accrual_note)}</div></div>
    <div class="acts"><button class="mini-btn" data-edit title="Изменить">${I.edit}</button><button class="mini-btn del" data-del title="Удалить">${I.trash}</button></div></div>`;
}
function poRowHtml(o,i){
  const[y,m,dd]=o.date.split("-");
  return `<div class="pay-row spot" data-id="${o.id}" style="--i:${i}">
    <div class="pd"><b>${+dd}</b><span>${MON[+m-1]} ${y.slice(2)}</span></div>
    <div class="pw"><div class="who">${esc(o.investor_name||"")}</div><div class="meta">${o.note?esc(o.note):"—"}</div></div>
    <span class="tag ${o.kind==="profit"?"k-final":"k-prepay"}" style="cursor:default">${PO_RU[o.kind]}</span>
    <div class="money"><b>${money(o.amount,o.currency)}</b></div>
    <div class="acts"><button class="mini-btn" data-edit title="Изменить">${I.edit}</button><button class="mini-btn del" data-del title="Удалить">${I.trash}</button></div></div>`;
}
async function investModal(pre,v,after){
  pre=pre||{};
  await loadRefs();
  const cands=S.partners.filter(x=>x.active).sort((a,b)=>(b.is_investor-a.is_investor)||a.name.localeCompare(b.name));
  if(!cands.length){toast("Сначала добавьте контрагента (раздел «Поставщики»)","err");return}
  const invId=v?.investor_id||pre.investor_id||cands[0].id;
  let terms=v?.terms||pre.terms||"share";
  const ships=(await api("/api/shipments?sort=date_desc")).rows.filter(s=>s.status!=="cancelled"||s.id===(v?.shipment_id||pre.shipment_id));
  const want=v?.shipment_id||pre.shipment_id||"";
  openModal(`<div class="mh"><h2>${v?"Вложение":"Новое вложение"}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c4"><label>Дата</label><input type="date" id="v-date" value="${v?.date||todayISO()}"></div>
    <div class="fg c8"><label>Инвестор</label><select id="v-inv">${cands.map(x=>`<option value="${x.id}" ${x.id===invId?"selected":""}>${esc(x.name)}${x.is_investor?"":" (станет инвестором)"}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Куда вложил</label><select id="v-ship"><option value="">Общий пул — доля от прибыли всех партий без адресных вложений</option>${ships.map(s=>`<option value="${s.id}" ${s.id===want?"selected":""}>${dRu(s.date)} · ${esc(s.supplier_name)} · ${money(s.amount,s.currency)} · ${s.profit!=null?"закрыта, прибыль "+money(s.profit):ST_RU[s.status]}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Условие</label><div class="seg-ctl two" id="v-terms"><i class="thumb"></i>${TERMS.map(k=>`<button type="button" data-k="${k}">${TERMS_RU[k]}</button>`).join("")}</div></div>
    <div class="fg c4"><label>Сумма</label><input type="number" step="0.01" min="0" id="v-amt" value="${v?.amount||pre.amount||""}" placeholder="0" autofocus></div>
    <div class="fg c3"><label>Валюта</label><select id="v-cur">${["USD","CNY","KGS"].map(c=>`<option ${((v?.currency)||S.settings.currency||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
    <div class="fg c5"><label id="v-val-l">Доля, % от прибыли</label><input type="number" step="0.1" min="0" max="100" id="v-val" value="${v?.terms_value??""}" placeholder="30"></div>
    <div class="fg c6" id="v-end-w" hidden><label>Дата возврата вложения (если вернули)</label><input type="date" id="v-end" value="${v?.end_date||""}"><div class="hint">процент начисляется до этой даты; пусто — по сегодня</div></div>
    <div class="fg c12"><label>Комментарий</label><input id="v-note" value="${esc(v?.note||"")}" placeholder="условия договорённости"></div>
   </div><div class="hint" id="v-hint" style="margin-top:12px"></div></div>
   <div class="mf"><span class="hint">⌘S — сохранить</span><button class="ghost" data-x>Отмена</button><button class="pill" id="v-save" data-save>${v?"Сохранить":"Записать вложение"}</button></div>`,"mid");
  const hint=()=>{const sid=+$("#v-ship").value;const s=ships.find(x=>x.id===sid);const val=+$("#v-val").value||0,amt=+$("#v-amt").value||0;
    let h="";
    if(terms==="fixed")h=`Начисляется ${val}% от ${money(amt)} за каждый полный месяц — это ${money(amt*val/100)} в месяц.`;
    else if(s)h=s.profit!=null?`Партия закрыта с прибылью ${money(s.profit)} — инвестору причитается ${money(s.profit*val/100)}.`:`Доля начислится, когда партия будет закрыта с прибылью (меню партии → «Закрыть партию»).`;
    else h=`Доля пула = вложение ÷ все вложения в пул. От прибыли каждой закрытой партии без адресных вложений инвестор получает ${val}% × свою долю пула.`;
    $("#v-hint").textContent=h};
  const setTerms=k=>{terms=k;$$("#v-terms button").forEach(b=>b.classList.toggle("on",b.dataset.k===k));$("#v-terms .thumb").style.transform=`translateX(${TERMS.indexOf(k)*100}%)`;
    $("#v-val-l").textContent=k==="fixed"?"Процент в месяц":"Доля, % от прибыли";$("#v-end-w").hidden=k!=="fixed";hint()};
  setTerms(terms);$$("#v-terms button").forEach(b=>b.onclick=()=>setTerms(b.dataset.k));
  ["v-ship","v-val","v-amt"].forEach(id=>$("#"+id).addEventListener("input",hint));hint();
  $("#v-save").onclick=async()=>{
    const ok=await withBusy($("#v-save"),async()=>{
      const body={date:$("#v-date").value,investor_id:+$("#v-inv").value,shipment_id:+$("#v-ship").value||null,amount:+$("#v-amt").value,currency:$("#v-cur").value,
        terms,terms_value:+$("#v-val").value||0,end_date:terms==="fixed"?($("#v-end").value||null):null,note:$("#v-note").value};
      await api(v?"/api/investments/"+v.id:"/api/investments",{method:v?"PATCH":"POST",body});toast(v?"Вложение изменено":"Вложение записано","ok")});
    if(ok){closeModal();(after||refreshAfterPay)()}
  };
}
async function payoutModal(pre,o,after){
  pre=pre||{};
  await loadRefs();
  const cands=S.partners.filter(x=>x.is_investor||x.id===(o?.investor_id||pre.investor_id));
  if(!cands.length){toast("Инвесторов пока нет — сначала запишите вложение","err");return}
  const invId=o?.investor_id||pre.investor_id||cands[0].id;
  let kind=o?.kind||pre.kind||"profit";let calc=null;
  openModal(`<div class="mh"><h2>${o?"Выплата":"Выплата инвестору"}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c4"><label>Дата</label><input type="date" id="o-date" value="${o?.date||todayISO()}"></div>
    <div class="fg c8"><label>Инвестор</label><select id="o-inv">${cands.map(x=>`<option value="${x.id}" ${x.id===invId?"selected":""}>${esc(x.name)}</option>`).join("")}</select><div class="hint" id="o-hint">Загрузка…</div></div>
    <div class="fg c12"><label>Тип выплаты</label><div class="seg-ctl two" id="o-kind"><i class="thumb"></i>${PO_KINDS.map(k=>`<button type="button" data-k="${k}">${PO_RU[k]}</button>`).join("")}</div></div>
    <div class="fg c6"><label>Сумма</label><div class="amt-w"><input type="number" step="0.01" min="0" id="o-amt" value="${o?.amount||pre.amount||""}" placeholder="0" autofocus><button type="button" class="lnk" id="o-rest" hidden>всё</button></div></div>
    <div class="fg c6"><label>Валюта</label><select id="o-cur">${["USD","CNY","KGS"].map(c=>`<option ${((o?.currency)||S.settings.currency||"USD")===c?"selected":""}>${c}</option>`).join("")}</select></div>
    <div class="fg c12"><label>Комментарий</label><input id="o-note" value="${esc(o?.note||"")}" placeholder="за какие партии, как передали"></div>
   </div></div>
   <div class="mf"><span class="hint">⌘S — сохранить</span><button class="ghost" data-x>Отмена</button><button class="pill" id="o-save" data-save>${o?"Сохранить":"Записать выплату"}</button></div>`,"mid");
  const hint=()=>{const h=$("#o-hint"),r=$("#o-rest");if(!calc){h.textContent="";r.hidden=true;return}
    h.innerHTML=`Начислено <b>${money(calc.accrued)}</b>, выплачено долей <b>${money(calc.paid_profit)}</b>, к выплате <b>${money(calc.due)}</b> · тело вложения у нас <b>${money(calc.principal_out)}</b>`;
    const v=kind==="profit"?calc.due:calc.principal_out;r.hidden=!(v>0.004);r.dataset.v=v;r.textContent=kind==="profit"?"весь остаток":"всё тело"};
  const setKind=k=>{kind=k;$$("#o-kind button").forEach(b=>b.classList.toggle("on",b.dataset.k===k));$("#o-kind .thumb").style.transform=`translateX(${PO_KINDS.indexOf(k)*100}%)`;hint()};
  setKind(kind);$$("#o-kind button").forEach(b=>b.onclick=()=>setKind(b.dataset.k));
  const loadCalc=async()=>{try{calc=await api("/api/investors/"+$("#o-inv").value)}catch(e){calc=null}hint()};
  $("#o-inv").onchange=loadCalc;await loadCalc();
  $("#o-rest").onclick=()=>{$("#o-amt").value=Math.round(+$("#o-rest").dataset.v*100)/100;$("#o-amt").focus()};
  $("#o-save").onclick=async()=>{
    const ok=await withBusy($("#o-save"),async()=>{
      const body={date:$("#o-date").value,investor_id:+$("#o-inv").value,amount:+$("#o-amt").value,currency:$("#o-cur").value,kind,note:$("#o-note").value};
      await api(o?"/api/payouts/"+o.id:"/api/payouts",{method:o?"PATCH":"POST",body});toast(o?"Выплата изменена":"Выплата записана","ok")});
    if(ok){closeModal();(after||refreshAfterPay)()}
  };
}

/* ═══════════════════ СВОДКА ═══════════════════ */
async function renderSummary(){
  const sp=S.sp;
  $("#main").innerHTML=`<div class="view">${headHtml("Сводка",skSub(),
    `${periodSel("sp-period",sp.period)}<span class="rng" id="sp-rng" ${sp.period==="custom"?"":"hidden"}><input type="date" id="sp-from" value="${sp.from}"><input type="date" id="sp-to" value="${sp.to}"></span>
     <a class="ghost" id="sp-export" href="/api/export.csv" download>${I.down}<span>Партии в Excel</span></a>${avatarHtml()}`)}
   <div class="kpis" id="kpis">${skKpis()}</div>
   <div class="grid"><div style="display:flex;flex-direction:column;gap:16px;min-width:0">
     <div class="glass panel" style="--i:1"><div class="ph"><h2>Партии по статусам</h2><span class="cnt" id="st-per"></span></div><div class="mb" id="sum-status">${skRows(1)}</div></div>
     <div class="glass panel" style="--i:2"><div class="ph"><h2>Топ поставщиков</h2><span class="cnt">по обороту за период</span></div><div class="mb" id="sum-sup"></div></div>
     <div class="glass panel" style="--i:3"><div class="ph"><h2>Закупки по магазинам</h2></div><div class="mb" id="sum-store"></div></div>
     <div class="glass panel" style="--i:4"><div class="ph"><h2>Ожидается прибытие</h2></div><div id="arr-list"></div></div>
   </div><aside id="aside" style="--i:2">${skAside()}</aside></div></div>`;
  const reload=()=>fillSummary();
  $("#sp-period").onchange=e=>{sp.period=e.target.value;$("#sp-rng").hidden=sp.period!=="custom";if(sp.period!=="custom"||(sp.from||sp.to))reload()};
  $("#sp-from").onchange=e=>{sp.from=e.target.value;reload()};$("#sp-to").onchange=e=>{sp.to=e.target.value;reload()};
  await loadRefs();await fillSummary();
}
async function fillSummary(){
  const sp=S.sp,range=periodRange(sp.period,sp.from,sp.to);
  await loadSummaryUI(range);
  const d=S.sum;if(!$("#sum-status"))return;
  const per=!!(range[0]||range[1]);
  const ex=$("#sp-export");if(ex){const p=new URLSearchParams();if(range[0])p.set("from",range[0]);if(range[1])p.set("to",range[1]);ex.href="/api/export.csv?"+p}
  const sub=$("#hd-sub");if(sub)sub.textContent=(per?"период: "+periodLabel(sp.period,sp.from,sp.to):"вся картина за всё время")+(d.investors.count?` · обязательства перед инвесторами ${money(d.investors.due)}`:"");
  $("#st-per").textContent=per?periodLabel(sp.period,sp.from,sp.to):"";
  const st=[["shipping","В пути","#FFB65C"],["new","Не отправлены","#8B94A8"],["arrived","Прибыли","#57E39B"],["cancelled","Отменены","#FF7B93"]];
  const parts=st.map(([k,l,c])=>({v:d.by_status[k].amount,color:c,l}));
  const totalAmt=parts.reduce((a,p)=>a+p.v,0),totalCnt=st.reduce((a,[k])=>a+d.by_status[k].count,0);
  $("#sum-status").innerHTML=`<div class="donut-w"><div class="donut-c">${donutSvg(parts.filter(p=>p.v>0),136,13)}
      <div class="dl"><b>${totalCnt}</b><span>${plural(totalCnt,"партия","партии","партий")}</span></div></div>
    <div class="donut-l">${st.map(([k,l,c])=>{const b=d.by_status[k];return `<div class="stat"><span class="l"><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${c};margin-right:8px"></i>${l} · ${b.count}</span>
      <span class="v">${money(b.amount)}${totalAmt?` <small style="color:var(--dim);font-weight:500">${Math.round(b.amount/totalAmt*100)}%</small>`:""}</span></div>`}).join("")}
      ${d.tiles.closed_count?`<div class="stat tot"><span class="l">Закрыто с прибылью · ${d.tiles.closed_count}</span><span class="v v-green">${money(d.tiles.profit)}</span></div>`:""}</div></div>`;
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

/* ═══════════════════ НАСТРОЙКИ, ПОЛЬЗОВАТЕЛИ ═══════════════════ */
async function renderSettings(){
  await loadRefs();const st=S.settings,u=S.user,m=M();
  $("#main").innerHTML=`<div class="view">${headHtml("Настройки","",avatarHtml())}
   <div class="grid two">
    ${m?`<div class="glass card spot" style="--i:0"><h3>По умолчанию</h3>
      <div class="stat"><span class="l">Валюта новых партий и платежей</span><span class="v"><select id="st-cur" class="psel">${["USD","CNY","KGS"].map(c=>`<option ${st.currency===c?"selected":""}>${c}</option>`).join("")}</select></span></div>
      <div class="stat"><span class="l">Курс к сому (подставляется в новую партию)</span><span class="v"><input id="st-rate" class="psel" type="number" step="0.01" value="${st.rate??""}" placeholder="—" style="width:96px"></span></div>
      <div class="stat"><span class="l wrap" style="font-size:12px;color:var(--dim)">Единицы измерения товара: шт · кор · кг · м · компл — выбираются в строке товара</span></div></div>
    <div class="glass card spot" style="--i:1"><h3>Данные</h3>
      <div class="stat"><span class="l">Партии и товары — в Excel (CSV)</span><a class="ghost sm" href="/api/export.csv" download>Скачать</a></div>
      <div class="stat"><span class="l">Платежи — в Excel (CSV)</span><a class="ghost sm" href="/api/payments.csv" download>Скачать</a></div>
      <div class="stat"><span class="l">Вся база одним файлом</span><a class="ghost sm" href="/api/backup.db" download>Скачать .db</a></div>
      <div class="stat"><span class="l wrap">Загрузить базу из файла .db<br><small style="color:var(--dim)">заменит все данные, кроме пользователей — так переносят учёт с компьютера в облако и обратно</small></span><button class="ghost sm" id="rs-btn">Выбрать файл</button><input type="file" id="rs-file" accept=".db" hidden></div>
      ${u?.cloud?"":`<div class="stat"><span class="l">Резервная копия в папку backups</span><button class="ghost sm" id="bk">Сделать сейчас</button></div>`}</div>`:""}
    <div class="glass card spot" style="--i:2"><h3>Программа</h3>
      <div class="stat"><span class="l">Версия</span><span class="v">${esc(u?.version||"")}${u?.cloud?" · облако":" · этот компьютер"}</span></div>
      <div class="stat"><span class="l">Вы вошли как</span><span class="v">${esc(u?.name||u?.login||"")} <small style="color:var(--dim);font-weight:500">${u?.role==="owner"?"владелец":"помощник"}</small></span></div>
      ${u?.auth?`<div class="stat"><span class="l">Пароль</span><button class="ghost sm" id="pw-btn">${I.key}<span>Сменить</span></button></div>
      <div class="stat"><span class="l">Выйти из программы</span><button class="ghost sm" id="out">Выйти</button></div>`:
        `<div class="stat"><span class="l wrap" style="font-size:12px;color:var(--dim)">Локальная версия открывается без пароля. В облачной версии вход по логину и паролю, есть роль помощника без доступа к деньгам.</span></div>`}</div>
    ${m&&u?.auth?`<div class="glass card spot" style="--i:3"><h3>Пользователи <button class="lnk" id="u-add">+ помощник</button></h3><div id="u-list"><span class="sk" style="width:100%;height:12px"></span></div>
      <div class="stat"><span class="l wrap" style="font-size:12px;color:var(--dim)">Помощник заводит партии, товары и статусы, но не видит цен, сумм, платежей, инвесторов и сводки.</span></div></div>`:""}
    <div class="glass card spot" style="--i:4"><h3>Горячие клавиши</h3><div class="keys">
      <div class="stat"><span class="l">Новая партия / платёж / контрагент / вложение</span><span class="v"><kbd>N</kbd></span></div>
      <div class="stat"><span class="l">Поиск</span><span class="v"><kbd>/</kbd></span></div>
      <div class="stat"><span class="l">Сохранить в открытом окне</span><span class="v"><kbd>⌘</kbd><kbd>S</kbd></span></div>
      <div class="stat"><span class="l">Закрыть окно</span><span class="v"><kbd>Esc</kbd></span></div>
      <div class="stat"><span class="l">Разделы по порядку</span><span class="v"><kbd>1</kbd><kbd>2</kbd>…<kbd>6</kbd></span></div></div></div>
    <div class="glass card spot" style="--i:5"><h3>На телефон</h3>
      <div class="stat"><span class="l wrap">Откройте адрес программы в Safari на iPhone → «Поделиться» → «На экран Домой». Откроется как приложение со своей иконкой, без адресной строки.</span></div></div>
   </div></div>`;
  if(m){
    const saveSt=async()=>{try{S.settings=await api("/api/settings",{method:"PATCH",body:{currency:$("#st-cur").value,rate:$("#st-rate").value}});toast("Настройки сохранены","ok")}catch(e){toast(e.message,"err")}};
    $("#st-cur").onchange=saveSt;$("#st-rate").onchange=saveSt;
    if($("#bk"))$("#bk").onclick=async()=>{const b=$("#bk");b.disabled=true;try{const r=await api("/api/backup",{method:"POST"});toast("Копия сделана: "+r.file,"ok")}catch(e){toast(e.message,"err")}finally{b.disabled=false}};
    $("#rs-btn").onclick=()=>$("#rs-file").click();
    $("#rs-file").onchange=async e=>{const f=e.target.files[0];e.target.value="";if(!f)return;
      if(!await confirmBox("Загрузить базу из файла?",`${f.name}, ${Math.round(f.size/1024)} КБ. Все партии, платежи и инвесторы будут заменены данными из файла. Пользователи останутся.`,true))return;
      const b64=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result.split(",")[1]);r.onerror=rej;r.readAsDataURL(f)});
      try{const r=await api("/api/restore",{method:"POST",body:{db_b64:b64}});const c=r.counts||{};
        toast(`База загружена: партий ${c.shipments||0}, платежей ${c.payments||0}, контрагентов ${c.partners||0}`,"ok");setTimeout(()=>location.reload(),1500)}
      catch(err){toast(err.message,"err")}};
    if(u?.auth){loadUsers();$("#u-add").onclick=()=>userModal()}
  }
  if($("#pw-btn"))$("#pw-btn").onclick=passwordModal;
  if($("#out"))$("#out").onclick=async()=>{await api("/api/logout",{method:"POST"});location.reload()};
}
async function loadUsers(){
  const el=$("#u-list");if(!el)return;
  try{const rows=await api("/api/users");
    el.innerHTML=rows.map(r=>`<div class="stat"><span class="l">${I.user?"":""}<b>${esc(r.login)}</b> · ${esc(r.name||"")} <small style="color:var(--dim)">${r.role==="owner"?"владелец":"помощник"}</small></span>
      <span class="v" style="display:flex;gap:2px"><button class="mini-btn" data-pw="${r.id}" title="Имя и пароль">${I.edit}</button>${r.id!==S.user.id?`<button class="mini-btn del" data-del="${r.id}" title="Удалить">${I.trash}</button>`:""}</span></div>`).join("");
    el.querySelectorAll("[data-pw]").forEach(b=>b.onclick=()=>userModal(rows.find(r=>r.id===+b.dataset.pw)));
    el.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{const r=rows.find(x=>x.id===+b.dataset.del);
      if(await confirmBox("Удалить пользователя?",`${r.login} (${r.name||""}) больше не сможет войти.`,true)){try{await api("/api/users/"+r.id,{method:"DELETE"});toast("Удалён","ok");loadUsers()}catch(e){toast(e.message,"err")}}});
  }catch(e){el.innerHTML=`<div class="stat"><span class="l">${esc(e.message)}</span></div>`}
}
function userModal(u){
  openModal(`<div class="mh"><h2>${u?"Пользователь "+esc(u.login):"Новый помощник"}</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    ${u?"":`<div class="fg c6"><label>Логин (латиницей)</label><input id="u-login" placeholder="aida" autofocus autocapitalize="off"></div>`}
    <div class="fg c6"><label>Имя</label><input id="u-name" value="${esc(u?.name||"")}" placeholder="Аида" ${u?"autofocus":""}></div>
    <div class="fg c6"><label>${u?"Новый пароль (пусто — не менять)":"Пароль"}</label><input id="u-pass" type="text" placeholder="не короче 6 символов" autocomplete="off"></div>
    ${u?"":`<div class="fg c6"><label>Роль</label><select id="u-role"><option value="helper">Помощник — без денег</option><option value="owner">Владелец — полный доступ</option></select></div>`}
   </div><div class="hint" style="margin-top:12px">Пароль передайте человеку лично — в программе он больше не показывается.</div></div>
   <div class="mf"><button class="ghost" data-x>Отмена</button><button class="pill" id="u-save" data-save>Сохранить</button></div>`,"mid");
  $("#u-save").onclick=async()=>{
    const ok=await withBusy($("#u-save"),async()=>{
      if(u)await api("/api/users/"+u.id,{method:"PATCH",body:{name:$("#u-name").value,password:$("#u-pass").value||null}});
      else await api("/api/users",{method:"POST",body:{login:$("#u-login").value,name:$("#u-name").value,password:$("#u-pass").value,role:$("#u-role").value}});
      toast("Сохранено","ok")});
    if(ok){closeModal();loadUsers()}};
}
function passwordModal(){
  openModal(`<div class="mh"><h2>Сменить пароль</h2><button class="x" data-x>×</button></div>
   <div class="mb"><div class="frm">
    <div class="fg c12"><label>Старый пароль</label><input id="pw-old" type="password" autofocus autocomplete="current-password"></div>
    <div class="fg c6"><label>Новый пароль</label><input id="pw-new" type="password" autocomplete="new-password"></div>
    <div class="fg c6"><label>Ещё раз</label><input id="pw-new2" type="password" autocomplete="new-password"></div>
   </div></div>
   <div class="mf"><button class="ghost" data-x>Отмена</button><button class="pill" id="pw-save" data-save>Сменить</button></div>`,"mid");
  $("#pw-save").onclick=async()=>{
    const ok=await withBusy($("#pw-save"),async()=>{
      if($("#pw-new").value!==$("#pw-new2").value)throw new Error("Новые пароли не совпадают");
      await api("/api/password",{method:"POST",body:{old:$("#pw-old").value,new:$("#pw-new").value}});toast("Пароль изменён","ok")});
    if(ok)closeModal()};
}

/* ═══════════════════ старт ═══════════════════ */
(async function(){
  const h=location.hash.replace("#","");if(RENDER[h])S.section=h;
  $$("#rail a").forEach(a=>a.onclick=()=>go(a.dataset.sec));
  try{S.user=await api("/api/me");applyRole();$("#app").classList.remove("off");go(S.section)}
  catch(e){showLogin()}
})();
