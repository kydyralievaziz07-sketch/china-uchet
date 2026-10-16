"use strict";
/* Бутики · учёт — интерфейс. Три экрана без перезагрузки страницы:
   Компании → Бутики компании → Закупка и финансы бутика. Плюс маленький экран настроек. */

/* ───────────── утилиты ───────────── */
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const SYM={USD:"$",KGS:"сом",KZT:"₸",RUB:"₽",CNY:"¥",EUR:"€"};
const REC={none:"Не получен",partial:"Получен частично",full:"Получен полностью"};
const S={user:null,settings:{currency:"USD"}};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtN=v=>(Math.round((+v||0)*100)/100).toLocaleString("ru-RU",{maximumFractionDigits:2});
const money=v=>{const n=+v||0;return (n<-0.004?"−":"")+fmtN(Math.abs(n))+" "+(SYM[S.settings.currency]||S.settings.currency)};
const dRu=d=>{if(!d)return"";const[y,m,dd]=String(d).slice(0,10).split("-");return dd+"."+m+"."+y};
const todayISO=()=>{const x=new Date();return x.getFullYear()+"-"+String(x.getMonth()+1).padStart(2,"0")+"-"+String(x.getDate()).padStart(2,"0")};
const plural=(n,a,b,c)=>{n=Math.abs(n)%100;const n1=n%10;if(n>10&&n<20)return c;if(n1>1&&n1<5)return b;if(n1===1)return a;return c};
const cnt=(n,a,b,c)=>n+" "+plural(n,a,b,c);
const v=id=>($("#"+id)?.value??"").trim();
const isMobile=()=>matchMedia("(max-width:600px)").matches;
async function api(path,opts={}){
  const r=await fetch(path,{headers:{"Content-Type":"application/json"},...opts,body:opts.body?JSON.stringify(opts.body):undefined});
  if(r.status===401){showLogin();throw new Error("Нужен вход")}
  const j=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(j.error||"Ошибка "+r.status);
  return j;
}
const I={
  back:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
  chev:'<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  edit:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>',
  gear:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2 2 2 0 11-4 0 1.7 1.7 0 00-2.9-1.2l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.7 1.7 0 003 15a2 2 0 110-4 1.7 1.7 0 001.2-2.9l-.1-.1a2 2 0 112.8-2.8l.1.1A1.7 1.7 0 009 4.6a2 2 0 114 0 1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1A1.7 1.7 0 0021 11a2 2 0 110 4z"/></svg>',
  box:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/></svg>',
  shop:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l1.5-5h15L21 9"/><path d="M4 9v11h16V9"/><path d="M3 9a3 3 0 006 0 3 3 0 006 0 3 3 0 006 0"/><path d="M10 20v-6h4v6"/></svg>',
};

/* ───────────── сообщения, окна, подтверждения ───────────── */
function toast(msg,cls){const t=document.createElement("div");t.className="toast "+(cls||"");t.textContent=msg;$("#toasts").appendChild(t);setTimeout(()=>t.remove(),cls==="err"?4500:2400)}
function openModal(title,body,footer){
  const m=$("#modal");
  m.innerHTML=`<form id="mform" novalidate autocomplete="off"><div class="mh"><h2>${esc(title)}</h2><button type="button" class="x" data-x aria-label="Закрыть">×</button></div>
    <div class="mb">${body}<div class="err-box" id="m-err"></div></div><div class="mf">${footer}</div></form>`;
  $("#modal-ov").classList.add("show");
  $$("#modal [data-x]").forEach(b=>b.onclick=closeModal);
  setTimeout(()=>{if(!isMobile())m.querySelector("[autofocus]")?.focus()},60);
}
function closeModal(){$("#modal-ov").classList.remove("show")}
$("#modal-ov").addEventListener("mousedown",e=>{if(e.target.id==="modal-ov")closeModal()});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeModal()});
const FOOT=(ok,x)=>`<button type="button" class="btn" data-x>${x||"Отмена"}</button><button type="submit" class="btn primary">${ok||"Сохранить"}</button>`;
function onSubmit(fn){
  const f=$("#mform");
  f.onsubmit=async e=>{e.preventDefault();const btn=f.querySelector("button[type=submit]");$("#m-err").textContent="";
    btn.classList.add("busy");btn.disabled=true;
    try{await fn()}catch(err){if(err.message!=="Нужен вход")$("#m-err").textContent=err.message}
    finally{btn.classList.remove("busy");btn.disabled=false}};
}
function confirmBox(title,text,okLabel){
  return new Promise(res=>{
    openModal(title,`<p class="hint" style="font-size:15.5px;color:var(--text)">${esc(text)}</p>`,
      `<button type="button" class="btn" data-x>Отмена</button><button type="submit" class="btn danger primary" autofocus>${esc(okLabel||"Удалить")}</button>`);
    $("#mform").onsubmit=e=>{e.preventDefault();closeModal();res(true)};
    $$("#modal [data-x]").forEach(b=>b.onclick=()=>{closeModal();res(false)});
  });
}
function fld(type,id,label,val,o={}){
  const common=`id="${id}" ${o.autofocus?"autofocus":""} placeholder="${esc(o.ph||"")}"`;
  let inp;
  if(type==="area")inp=`<textarea ${common} rows="2">${esc(val??"")}</textarea>`;
  else if(type==="num")inp=`<input type="text" inputmode="decimal" ${common} value="${esc(val??"")}">`;
  else if(type==="date")inp=`<input type="date" ${common} value="${esc(val??"")}">`;
  else inp=`<input type="text" ${common} value="${esc(val??"")}">`;
  return `<div class="fg${o.full?" full":""}"><label for="${id}">${label}</label>${inp}${o.hint?`<div class="hint">${o.hint}</div>`:""}</div>`;
}
function bar(title,sub,backHash,backLabel,acts){
  return `<div class="bar">${backHash!=null?`<a class="back" href="#${backHash}">${I.back}<span>${esc(backLabel)}</span></a>`:""}
    <h1>${esc(title)}${sub?`<small>${esc(sub)}</small>`:""}</h1><div class="acts">${acts||""}</div></div>`;
}

/* ───────────── навигация ───────────── */
const nav=h=>{if(location.hash.replace(/^#\/?/,"")===h)route();else location.hash=h};
let routeSeq=0;
async function route(){
  const seq=++routeSeq;
  const [a,b]=location.hash.replace(/^#\/?/,"").split("/");
  try{
    if(a==="company"&&b)await renderCompany(+b);
    else if(a==="boutique"&&b)await renderBoutique(+b);
    else if(a==="settings")await renderSettings();
    else await renderCompanies();
    if(seq===routeSeq)window.scrollTo(0,0);
  }catch(e){if(e.message!=="Нужен вход"){toast(e.message,"err");if(a)nav("")}}
}
addEventListener("hashchange",route);
async function refresh(fn){const y=scrollY;await fn();window.scrollTo(0,y)}

/* ───────────── уровень 1: компании ───────────── */
const coTitle=c=>c.name||("Компания от "+dRu(c.date));
async function renderCompanies(){
  const rows=(await api("/api/companies")).rows;
  $("#main").innerHTML=`<div class="view">${bar("Компании",rows.length?cnt(rows.length,"компания","компании","компаний"):"",null,"",
      `<a class="ibtn" href="#settings" title="Настройки" aria-label="Настройки">${I.gear}</a>`)}
    ${rows.length?`<div class="list">${rows.map(companyRow).join("")}</div>
      <div class="add-row"><button class="btn primary big add-main" id="add-co">${I.plus}Создать компанию</button></div>`
    :`<div class="empty card"><div class="big-ic">${I.box}</div><b>Компаний пока нет</b>
      <p>Создайте первую компанию. Внутри неё будут бутики, а в каждом бутике — закупка и финансы.</p>
      <button class="btn primary big" id="add-co">${I.plus}Создать компанию</button></div>`}</div>`;
  $("#add-co").onclick=()=>companyModal();
}
function companyRow(c){
  return `<a class="card row" href="#company/${c.id}"><div class="main"><div class="ttl">${esc(coTitle(c))}</div>
    <div class="sub">создана ${dRu(c.date)} · ${cnt(c.boutiques_count,"бутик","бутика","бутиков")}</div>
    <div class="nums"><div><span>Закупки</span><b>${money(c.total)}</b></div><div><span>Оплачено</span><b>${money(c.paid)}</b></div>
      <div><span>Осталось оплатить</span><b class="${c.remaining>0?"warn":"ok"}">${money(c.remaining)}</b></div>
      ${c.overpaid>0?`<div><span>Переплата</span><b class="bad">${money(c.overpaid)}</b></div>`:""}</div></div>${I.chev}</a>`;
}
function companyModal(c){
  const isNew=!c;
  openModal(isNew?"Новая компания":"Компания",`<div class="frm">
    ${fld("date","co-date","Дата создания",c?.date||todayISO(),{autofocus:true})}
    ${fld("text","co-name","Название (необязательно)",c?.name,{ph:"например, Осень 2026"})}
    ${fld("area","co-note","Комментарий (необязательно)",c?.note,{full:true})}</div>`,FOOT(isNew?"Создать":"Сохранить"));
  onSubmit(async()=>{
    const body={date:v("co-date"),name:v("co-name"),note:v("co-note")};
    const r=await api(isNew?"/api/companies":"/api/companies/"+c.id,{method:isNew?"POST":"PATCH",body});
    closeModal();toast(isNew?"Компания создана":"Сохранено","ok");
    isNew?nav("company/"+r.id):route();
  });
}

/* ───────────── уровень 2: бутики компании ───────────── */
const bTitle=b=>b.city+" · "+b.name;
async function renderCompany(id){
  const c=await api("/api/companies/"+id),bs=c.boutiques;
  $("#main").innerHTML=`<div class="view">${bar(coTitle(c),"создана "+dRu(c.date)+(c.note?" · "+c.note:""),"","Компании",
      `<button class="ibtn" id="co-edit" title="Изменить компанию">${I.edit}</button><button class="ibtn danger" id="co-del" title="Удалить компанию">${I.trash}</button>`)}
    <div class="tiles">
      <div class="card tile"><span>Бутиков</span><b>${bs.length}</b></div>
      <div class="card tile"><span>Закупки</span><b>${money(c.total)}</b></div>
      <div class="card tile accent"><span>Оплачено</span><b>${money(c.paid)}</b><small>Санжар ${money(c.paid_own)} · депозит ${money(c.deposit_used)}</small></div>
      <div class="card tile ${c.remaining>0?"warn":"ok"}"><span>Осталось оплатить</span><b>${money(c.remaining)}</b>${c.overpaid>0?`<small>переплата ${money(c.overpaid)}</small>`:""}</div>
    </div>
    ${bs.length?`<div class="list">${bs.map(boutRow).join("")}</div>
      <div class="add-row"><button class="btn primary big add-main" id="add-b">${I.plus}Добавить бутик</button></div>`
    :`<div class="empty card"><div class="big-ic">${I.shop}</div><b>Бутиков пока нет</b>
      <p>Добавьте бутик: город, номер или название. Внутри будут товары, депозит и платежи.</p>
      <button class="btn primary big" id="add-b">${I.plus}Добавить бутик</button></div>`}</div>`;
  $("#add-b").onclick=()=>boutiqueModal(c.id);
  $("#co-edit").onclick=()=>companyModal(c);
  $("#co-del").onclick=async()=>{
    const inside=bs.length?` Вместе с ней удалятся ${cnt(bs.length,"бутик","бутика","бутиков")}, их товары и платежи.`:"";
    if(!await confirmBox("Удалить компанию?",`«${coTitle(c)}» будет удалена.${inside} Отменить это нельзя.`))return;
    try{await api("/api/companies/"+c.id,{method:"DELETE"});toast("Компания удалена","ok");nav("")}catch(e){toast(e.message,"err")}};
}
function boutRow(b){
  return `<a class="card row" href="#boutique/${b.id}"><div class="main"><div class="ttl">${esc(bTitle(b))}</div>
    <div class="sub">${cnt(b.items_count,"товар","товара","товаров")} · <span class="chip ${b.receipt_status}">${REC[b.receipt_status]}</span>${b.note?" · "+esc(b.note):""}</div>
    <div class="nums"><div><span>Стоимость</span><b>${money(b.total)}</b></div><div><span>Оплачено</span><b>${money(b.paid)}</b></div>
      <div><span>Осталось</span><b class="${b.remaining>0?"warn":"ok"}">${money(b.remaining)}</b></div>
      ${b.overpaid>0?`<div><span>Переплата</span><b class="bad">${money(b.overpaid)}</b></div>`:""}</div></div>${I.chev}</a>`;
}
function boutiqueModal(companyId,b){
  const isNew=!b;
  openModal(isNew?"Новый бутик":"Бутик",`<div class="frm">
    ${fld("text","b-city","Город",b?.city,{ph:"Гуанчжоу",autofocus:true})}
    ${fld("text","b-name","Номер или название бутика",b?.name,{ph:"№12"})}
    ${fld("area","b-note","Комментарий (необязательно)",b?.note,{full:true,ph:"этаж, ряд, контакт…"})}</div>`,FOOT(isNew?"Добавить":"Сохранить"));
  onSubmit(async()=>{
    const body={city:v("b-city"),name:v("b-name"),note:v("b-note")};if(isNew)body.company_id=companyId;
    const r=await api(isNew?"/api/boutiques":"/api/boutiques/"+b.id,{method:isNew?"POST":"PATCH",body});
    closeModal();toast(isNew?"Бутик добавлен":"Сохранено","ok");
    isNew?nav("boutique/"+r.id):route();
  });
}

/* ───────────── уровень 3: закупка и финансы бутика ───────────── */
async function renderBoutique(id){
  const b=await api("/api/boutiques/"+id),items=b.items,pays=b.payments;
  const sym=SYM[S.settings.currency]||S.settings.currency;
  const noAmount=items.filter(i=>i.amount==null).length;
  $("#main").innerHTML=`<div class="view">${bar(bTitle(b),b.note||"","company/"+b.company_id,b.company_name||"Компания",
      `<button class="ibtn" id="b-edit" title="Изменить бутик">${I.edit}</button><button class="ibtn danger" id="b-del" title="Удалить бутик">${I.trash}</button>`)}

    <section>
      <div class="sec-h"><h2>Товары <span class="cnt">${items.length||""}</span></h2><button class="btn sm primary" id="add-item">${I.plus}Добавить товар</button></div>
      ${items.length?`<div class="card">${items.map(i=>itemRow(i,b,sym)).join("")}</div>`
      :`<div class="card empty" style="padding:26px 16px"><b>Товаров пока нет</b><p>Запишите, что закупаете в этом бутике. Количество, цена и комментарий — по желанию.</p>
        <button class="btn primary" id="add-item2">${I.plus}Добавить товар</button></div>`}
    </section>

    <section>
      <div class="sec-h"><h2>Финансы</h2></div>
      <div class="tiles">
        <div class="card tile"><span>Стоимость закупки</span><b>${money(b.total)}</b><small>${b.total_mode==="manual"?"указана вручную":"по товарам"}</small></div>
        <div class="card tile"><span>Депозит</span><b>${money(b.deposit)}</b><small>${b.deposit>0?`использовано ${money(b.deposit_used)}`:"не вносился"}</small></div>
        <div class="card tile accent"><span>Заплатил Санжар</span><b>${money(b.paid)}</b><small>свои ${money(b.paid_own)} · депозит ${money(b.deposit_used)}</small></div>
        <div class="card tile ${b.remaining>0?"warn":"ok"}"><span>Осталось оплатить</span><b>${money(b.remaining)}</b><small>${b.overpaid>0?"переплата "+money(b.overpaid):(b.total>0&&b.remaining<=0?"закупка оплачена":"")}</small></div>
      </div>

      <div class="card fin"><div class="fin-h"><h3>Общая стоимость закупки</h3><button class="btn sm" id="ed-total">Изменить</button></div>
        <div class="big">${money(b.total)}</div>
        <div class="line">${b.total_mode==="manual"
          ?`Указана вручную одной суммой. По товарам получается <b>${money(b.items_total)}</b> — в расчёте не участвует.`
          :`Считается по товарам: ${cnt(items.length,"позиция","позиции","позиций")}.${noAmount?` У ${cnt(noAmount,"позиции","позиций","позиций")} нет суммы — можно указать общую стоимость вручную.`:""}`}</div></div>

      <div class="card fin"><div class="fin-h"><h3>Депозит</h3><button class="btn sm" id="ed-dep">${b.deposit>0?"Изменить":"Внести"}</button></div>
        <div class="big">${money(b.deposit)}</div>
        <div class="line">${b.deposit>0
          ?`${b.deposit_date?"внесён "+dRu(b.deposit_date)+" · ":""}использовано <b>${money(b.deposit_used)}</b> · ещё не использовано <b>${money(b.deposit_left)}</b>${b.deposit_note?" · "+esc(b.deposit_note):""}`
          :"Депозит не вносился."} Депозит считается отдельно от денег Санжара и засчитывается в оплату только платежом «из депозита».</div></div>

      <div class="card fin"><div class="fin-h"><h3>Оплаты Санжара</h3><button class="btn sm primary" id="add-pay">${I.plus}Добавить платёж</button></div>
        <div class="line">Всего заплатил <b>${money(b.paid)}</b> · из своих денег <b>${money(b.paid_own)}</b> · из депозита <b>${money(b.deposit_used)}</b></div>
        <div class="formula">Осталось оплатить = ${money(b.total)} (стоимость) − ${money(b.deposit_used)} (использованный депозит) − ${money(b.paid_own)} (деньги Санжара) = <b>${money(b.remaining)}</b>${b.overpaid>0?` · оплачено больше стоимости: переплата <b>${money(b.overpaid)}</b>`:""}</div>
        ${pays.length?`<div class="pays">${pays.map(payRow).join("")}</div>`:`<div class="hint" style="margin-top:10px">Платежей пока нет.</div>`}</div>

      <div class="card fin"><div class="fin-h"><h3>Получение товара</h3><button class="btn sm" id="ed-rec">Отметить</button></div>
        <div class="big"><span class="chip ${b.receipt_status}" style="font-size:15px;padding:6px 13px">${REC[b.receipt_status]}</span></div>
        <div class="line">${[b.receipt_date?"дата "+dRu(b.receipt_date):"",
          b.qty_total!=null&&b.receipt_status!=="none"?`получено <b>${fmtN(b.received_total)}</b> из <b>${fmtN(b.qty_total)}</b> шт`:"",
          b.receipt_note?esc(b.receipt_note):""].filter(Boolean).join(" · ")||"Оплата и получение — разные вещи: оплаченный товар не считается полученным сам."}</div></div>
    </section></div>`;

  const again=()=>refresh(()=>renderBoutique(id));
  $("#b-edit").onclick=()=>boutiqueModal(b.company_id,b);
  $("#b-del").onclick=async()=>{
    if(!await confirmBox("Удалить бутик?",`«${bTitle(b)}» будет удалён вместе с товарами, депозитом и платежами. Отменить это нельзя.`))return;
    try{await api("/api/boutiques/"+b.id,{method:"DELETE"});toast("Бутик удалён","ok");nav("company/"+b.company_id)}catch(e){toast(e.message,"err")}};
  $$("#add-item,#add-item2").forEach(x=>x.onclick=()=>itemModal(b,null,again));
  $$("[data-ie]").forEach(x=>x.onclick=()=>itemModal(b,items.find(i=>i.id===+x.dataset.ie),again));
  $$("[data-id]").forEach(x=>x.onclick=async()=>{const i=items.find(i=>i.id===+x.dataset.id);
    if(!await confirmBox("Удалить товар?",`«${i.product}» будет удалён из закупки.`))return;
    try{await api("/api/items/"+i.id,{method:"DELETE"});toast("Товар удалён","ok");again()}catch(e){toast(e.message,"err")}});
  $("#ed-total").onclick=()=>totalModal(b,again);
  $("#ed-dep").onclick=()=>depositModal(b,again);
  $("#add-pay").onclick=()=>paymentModal(b,null,again);
  $$("[data-pe]").forEach(x=>x.onclick=()=>paymentModal(b,pays.find(p=>p.id===+x.dataset.pe),again));
  $$("[data-pd]").forEach(x=>x.onclick=async()=>{const p=pays.find(p=>p.id===+x.dataset.pd);
    if(!await confirmBox("Удалить платёж?",`Платёж ${money(p.amount)} от ${dRu(p.date)} будет удалён, остаток пересчитается.`))return;
    try{await api("/api/payments/"+p.id,{method:"DELETE"});toast("Платёж удалён","ok");again()}catch(e){toast(e.message,"err")}});
  $("#ed-rec").onclick=()=>receiptModal(b,again);
}
function itemRow(i,b,sym){
  const parts=[i.qty!=null?fmtN(i.qty)+" шт":"",i.unit_price!=null?fmtN(i.unit_price)+" "+sym+" за шт":"",i.note?esc(i.note):""].filter(Boolean);
  if(i.qty>0&&b.receipt_status!=="none")parts.push(`получено ${fmtN(i.received_qty||0)} из ${fmtN(i.qty)}`);
  return `<div class="item"><div class="main"><div class="ttl">${esc(i.product)}</div>${parts.length?`<div class="sub">${parts.join(" · ")}</div>`:""}</div>
    <div class="amt">${i.amount!=null?money(i.amount):"<small>без суммы</small>"}</div>
    <div class="acts"><button class="mini" data-ie="${i.id}" title="Изменить">${I.edit}</button><button class="mini del" data-id="${i.id}" title="Удалить">${I.trash}</button></div></div>`;
}
function payRow(p){
  return `<div class="item"><div class="main"><div class="ttl">${money(p.amount)} <span class="chip ${p.source}">${p.source==="deposit"?"из депозита":"свои деньги"}</span></div>
    <div class="sub">${dRu(p.date)}${p.note?" · "+esc(p.note):""}</div></div>
    <div class="acts"><button class="mini" data-pe="${p.id}" title="Изменить">${I.edit}</button><button class="mini del" data-pd="${p.id}" title="Удалить">${I.trash}</button></div></div>`;
}
function itemModal(b,i,after){
  const isNew=!i;
  openModal(isNew?"Новый товар":"Товар",`<div class="frm">
    ${fld("text","i-name","Название товара",i?.product,{full:true,ph:"например, сумка кожаная",autofocus:true})}
    ${fld("num","i-qty","Количество, шт",i?.qty,{ph:"необязательно"})}
    ${fld("num","i-price","Цена за единицу",i?.unit_price,{ph:"необязательно"})}
    ${fld("num","i-amount","Общая стоимость позиции",i?.amount,{full:true,ph:"считается сама из количества × цены",hint:"Если указаны количество и цена, считается автоматически. Можно ввести свою сумму."})}
    ${fld("text","i-note","Комментарий",i?.note,{full:true,ph:"необязательно"})}</div>`,FOOT(isNew?"Добавить":"Сохранить"));
  const q=$("#i-qty"),p=$("#i-price"),a=$("#i-amount");
  const auto=()=>{const qq=+q.value.replace(",","."),pp=+p.value.replace(",",".");
    if(q.value.trim()&&p.value.trim()&&!isNaN(qq)&&!isNaN(pp))a.value=String(Math.round(qq*pp*100)/100)};
  q.oninput=p.oninput=auto;
  onSubmit(async()=>{
    const body={boutique_id:b.id,product:v("i-name"),qty:v("i-qty"),unit_price:v("i-price"),amount:v("i-amount"),note:v("i-note")};
    await api(isNew?"/api/items":"/api/items/"+i.id,{method:isNew?"POST":"PATCH",body});
    closeModal();toast(isNew?"Товар добавлен":"Сохранено","ok");after();
  });
}
function totalModal(b,after){
  const noAmount=b.items.filter(i=>i.amount==null).length;
  openModal("Общая стоимость закупки",`<div class="choice">
    <label><input type="radio" name="tm" value="items" ${b.total_mode==="items"?"checked":""}><div><span class="t">По товарам: ${money(b.items_total)}</span>
      <span class="d">сумма всех позиций${noAmount?` · у ${cnt(noAmount,"позиции","позиций","позиций")} сумма не указана`:""}</span></div></label>
    <label><input type="radio" name="tm" value="manual" ${b.total_mode==="manual"?"checked":""}><div><span class="t">Указать вручную</span>
      <span class="d">если стоимость закупки известна одной суммой</span></div></label></div>
    <div class="frm" style="margin-top:12px">${fld("num","t-manual","Общая стоимость закупки",b.manual_total??"",{full:true,ph:"0"})}</div>
    <div class="hint" style="margin-top:8px">В расчёте участвует только один способ — двойного учёта нет.</div>`,FOOT());
  const sync=()=>{const man=$("#mform input[name=tm]:checked").value==="manual";$("#t-manual").disabled=!man;if(man&&!isMobile())$("#t-manual").focus()};
  $$("#mform input[name=tm]").forEach(r=>r.onchange=sync);sync();
  onSubmit(async()=>{
    const mode=$("#mform input[name=tm]:checked").value;
    const body=mode==="manual"?{total_mode:"manual",manual_total:v("t-manual")}:{total_mode:"items"};
    await api("/api/boutiques/"+b.id,{method:"PATCH",body});closeModal();toast("Сохранено","ok");after();
  });
}
function depositModal(b,after){
  openModal("Депозит",`<div class="frm">
    ${fld("num","d-amount","Сумма депозита",b.deposit||"",{ph:"0",autofocus:true})}
    ${fld("date","d-date","Дата внесения (необязательно)",b.deposit_date||"")}
    ${fld("text","d-note","Комментарий",b.deposit_note,{full:true,ph:"необязательно"})}</div>
    <div class="hint" style="margin-top:10px">Депозит не вычитается из стоимости сам по себе. Чтобы оплатить закупку депозитом, добавьте платёж «из депозита».
    ${b.deposit_used>0?` Уже использовано ${money(b.deposit_used)} — меньше этой суммы указать нельзя.`:""}</div>`,FOOT());
  onSubmit(async()=>{
    await api("/api/boutiques/"+b.id,{method:"PATCH",body:{deposit:v("d-amount")||0,deposit_date:v("d-date"),deposit_note:v("d-note")}});
    closeModal();toast("Депозит сохранён","ok");after();
  });
}
function paymentModal(b,p,after){
  const isNew=!p;
  const avail=b.deposit_left+(p?.source==="deposit"?+p.amount:0);
  openModal(isNew?"Платёж Санжара":"Платёж",`<div class="frm">
    ${fld("date","p-date","Дата платежа",p?.date||todayISO())}
    ${fld("num","p-amount","Сумма",p?.amount,{ph:"0",autofocus:true})}
    <div class="fg full"><label>Откуда деньги</label><div class="choice">
      <label><input type="radio" name="src" value="own" ${!p||p.source==="own"?"checked":""}><div><span class="t">Свои деньги Санжара</span><span class="d">Санжар платит из собственных средств</span></div></label>
      <label><input type="radio" name="src" value="deposit" ${p?.source==="deposit"?"checked":""} ${b.deposit>0?"":"disabled"}><div><span class="t">Из депозита</span>
        <span class="d">${b.deposit>0?`ещё не использовано ${money(avail)}`:"сначала внесите депозит в блоке «Депозит»"}</span></div></label></div></div>
    ${fld("text","p-note","Комментарий",p?.note,{full:true,ph:"необязательно"})}</div>`,FOOT(isNew?"Добавить":"Сохранить"));
  onSubmit(async()=>{
    const body={boutique_id:b.id,date:v("p-date"),amount:v("p-amount"),source:$("#mform input[name=src]:checked").value,note:v("p-note")};
    await api(isNew?"/api/payments":"/api/payments/"+p.id,{method:isNew?"POST":"PATCH",body});
    closeModal();toast(isNew?"Платёж добавлен":"Сохранено","ok");after();
  });
}
function receiptModal(b,after){
  const qi=b.items.filter(i=>i.qty>0);
  openModal("Получение товара",`<div class="choice">
    ${["none","partial","full"].map(s=>`<label><input type="radio" name="rs" value="${s}" ${b.receipt_status===s?"checked":""}><div><span class="t">${REC[s]}</span></div></label>`).join("")}</div>
    <div class="frm" style="margin-top:12px">
      ${fld("date","r-date","Дата получения",b.receipt_date||todayISO())}
      ${fld("text","r-note","Комментарий",b.receipt_note,{ph:"необязательно"})}</div>
    ${qi.length?`<div class="fg full" style="margin-top:12px"><label>Полученное количество</label><div class="rec-list">
      ${qi.map(i=>`<div class="r"><span>${esc(i.product)}<small>заказано ${fmtN(i.qty)} шт</small></span><input inputmode="decimal" data-rid="${i.id}" value="${i.received_qty??""}" placeholder="0"></div>`).join("")}</div></div>`:""}
    <div class="hint" style="margin-top:10px">Получение не зависит от оплаты: отмечайте его, когда товар физически пришёл.</div>`,FOOT());
  const sync=()=>{const s=$("#mform input[name=rs]:checked").value;
    $("#r-date").disabled=s==="none";
    $$("#mform [data-rid]").forEach(inp=>{const it=qi.find(i=>i.id===+inp.dataset.rid);
      if(s==="full")inp.value=it.qty;else if(s==="none")inp.value="";inp.disabled=s!=="partial"})};
  $$("#mform input[name=rs]").forEach(r=>r.onchange=sync);sync();
  onSubmit(async()=>{
    const s=$("#mform input[name=rs]:checked").value;
    const received=$$("#mform [data-rid]").map(inp=>({id:+inp.dataset.rid,received_qty:inp.value.trim()}));
    await api("/api/boutiques/"+b.id,{method:"PATCH",body:{receipt_status:s,receipt_date:s==="none"?"":v("r-date"),receipt_note:v("r-note"),received}});
    closeModal();toast("Сохранено","ok");after();
  });
}

/* ───────────── настройки ───────────── */
async function renderSettings(){
  const u=S.user;S.settings=await api("/api/settings");
  $("#main").innerHTML=`<div class="view">${bar("Настройки","","","Компании","")}
    <div class="card fin"><div class="fin-h"><h3>Валюта</h3><select id="st-cur" style="height:40px;border:1px solid var(--line);border-radius:10px;padding:0 10px;background:var(--bg)">
      ${Object.keys(SYM).map(c=>`<option ${S.settings.currency===c?"selected":""}>${c}</option>`).join("")}</select></div>
      <div class="hint" style="margin-top:6px">Все суммы показываются в этой валюте.</div></div>
    <div class="card fin"><div class="fin-h"><h3>Данные</h3></div><div class="stat-list">
      <div class="item"><div class="main"><div class="ttl">Вся база одним файлом</div><div class="sub">можно сохранить как копию или перенести на другой компьютер / в облако</div></div><a class="btn sm" href="/api/backup.db" download>Скачать .db</a></div>
      <div class="item"><div class="main"><div class="ttl">Загрузить базу из файла .db</div><div class="sub">заменит все компании, бутики, товары и платежи данными из файла</div></div><button class="btn sm" id="rs-btn">Выбрать файл</button><input type="file" id="rs-file" accept=".db" hidden></div>
      ${u?.cloud?"":`<div class="item"><div class="main"><div class="ttl">Резервная копия в папку backups</div><div class="sub">делается сама при каждом запуске, хранятся 30 последних</div></div><button class="btn sm" id="bk">Сделать сейчас</button></div>`}
    </div></div>
    ${u?.auth?`<div class="card fin"><div class="fin-h"><h3>Вход</h3></div><div class="stat-list">
      ${u.link?`<div class="item"><div class="main"><div class="ttl">Личная ссылка входа</div><div class="sub">открыли один раз — устройство помнит вход год. На iPhone: Safari → «Поделиться» → «На экран Домой». Ссылка заменяет пароль, не пересылайте её посторонним.</div>
        <div class="linkbox"><code id="ph-link">${esc(location.origin+u.link)}</code><button type="button" class="btn sm" id="ph-copy">Скопировать</button></div></div></div>`:""}
      <div class="item"><div class="main"><div class="ttl">Пароль</div><div class="sub">вы вошли как ${esc(u.name||u.login)}</div></div><button class="btn sm" id="pw-btn">Сменить</button></div>
      <div class="item"><div class="main"><div class="ttl">Выйти из программы</div></div><button class="btn sm" id="out">Выйти</button></div>
    </div></div>`:""}
    <div class="card fin"><div class="fin-h"><h3>Программа</h3></div>
      <div class="hint">Версия ${esc(u?.version||"")} · ${u?.cloud?"облако":"этот компьютер"}. Структура: Компании → Бутики → Закупка и финансы.</div></div></div>`;
  $("#st-cur").onchange=async()=>{try{S.settings=await api("/api/settings",{method:"PATCH",body:{currency:$("#st-cur").value}});toast("Валюта сохранена","ok")}catch(e){toast(e.message,"err")}};
  $("#rs-btn").onclick=()=>$("#rs-file").click();
  $("#rs-file").onchange=async e=>{const f=e.target.files[0];e.target.value="";if(!f)return;
    if(!await confirmBox("Загрузить базу из файла?",`${f.name}, ${Math.round(f.size/1024)} КБ. Все компании, бутики, товары и платежи будут заменены данными из файла.`,"Загрузить"))return;
    const b64=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result.split(",")[1]);r.onerror=rej;r.readAsDataURL(f)});
    try{const r=await api("/api/restore",{method:"POST",body:{db_b64:b64}});const c=r.counts||{};
      toast(`База загружена: компаний ${c.companies||0}, бутиков ${c.boutiques||0}, платежей ${c.boutique_payments||0}`,"ok");setTimeout(()=>location.reload(),1500)}
    catch(err){toast(err.message,"err")}};
  if($("#bk"))$("#bk").onclick=async()=>{try{const r=await api("/api/backup",{method:"POST"});toast("Копия сделана: "+r.file,"ok")}catch(e){toast(e.message,"err")}};
  if($("#ph-copy"))$("#ph-copy").onclick=async()=>{const t=$("#ph-link").textContent;
    try{await navigator.clipboard.writeText(t);toast("Ссылка скопирована","ok")}
    catch(e){const r=document.createRange();r.selectNode($("#ph-link"));getSelection().removeAllRanges();getSelection().addRange(r);toast("Ссылка выделена — скопируйте её","")}};
  if($("#pw-btn"))$("#pw-btn").onclick=passwordModal;
  if($("#out"))$("#out").onclick=async()=>{await api("/api/logout",{method:"POST"});location.reload()};
}
function passwordModal(){
  openModal("Сменить пароль",`<div class="frm">
    <div class="fg full"><label for="pw-old">Старый пароль</label><input id="pw-old" type="password" autofocus autocomplete="current-password"></div>
    <div class="fg"><label for="pw-new">Новый пароль</label><input id="pw-new" type="password" autocomplete="new-password"></div>
    <div class="fg"><label for="pw-new2">Ещё раз</label><input id="pw-new2" type="password" autocomplete="new-password"></div></div>`,FOOT("Сменить"));
  onSubmit(async()=>{
    if($("#pw-new").value!==$("#pw-new2").value)throw new Error("Новые пароли не совпадают");
    await api("/api/password",{method:"POST",body:{old:$("#pw-old").value,new:$("#pw-new").value}});closeModal();toast("Пароль изменён","ok");
  });
}

/* ───────────── вход (облачный режим) и старт ───────────── */
function showLogin(){$("#login-ov").classList.add("show");$("#main").classList.add("off")}
$("#login-form").onsubmit=async e=>{
  e.preventDefault();$("#l-err").textContent="";const btn=$("#l-btn");btn.classList.add("busy");
  try{
    const r=await api("/api/login",{method:"POST",body:{login:$("#l-login").value,password:$("#l-pass").value}});
    S.user=r.user;S.settings=await api("/api/settings");$("#login-ov").classList.remove("show");$("#main").classList.remove("off");route();
  }catch(err){$("#l-err").textContent=err.message}
  finally{btn.classList.remove("busy")}
};
(async function(){
  try{S.user=await api("/api/me");S.settings=await api("/api/settings");$("#main").classList.remove("off");route()}
  catch(e){showLogin()}
})();
