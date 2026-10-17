#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Бутики · учёт — помощник в Telegram.

Владелец пишет или наговаривает голосовое обычными словами — по-кыргызски, по-русски,
вперемешку или по-китайски. Помощник расшифровывает речь, понимает задачу и сам делает
всё в программе: заводит компании, бутики и товары, записывает депозит и платежи Санжара,
отмечает получение товара, исправляет и удаляет записи, отвечает на вопросы по цифрам.

Доступ к данным полный — через два инструмента (чтение и запись) ко всем /api/… того же
сервера. Помощник умеет ровно то же, что владелец умеет руками на сайте: проверка данных
и пересчёт остатков работают одинаково.

Речь: whisper-large-v3 на Groq (бесплатно), две расшифровки сразу. Кыргызского в Whisper
нет, поэтому смысл восстанавливает модель по справочнику имён и правилам числительных.
"""
import io, json, os, re, threading, time, queue, urllib.request, urllib.error
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- настройки
TOKEN    = (os.environ.get("KN_TG_TOKEN") or "").strip()
SECRET   = (os.environ.get("KN_TG_SECRET") or "").strip()          # подпись вебхука Telegram
ALLOW    = {s.strip() for s in (os.environ.get("KN_TG_ALLOW") or "").split(",") if s.strip()}
HOOK_URL = (os.environ.get("KN_TG_HOOK_URL") or "").strip()        # https://…/api/tg/hook — иначе опрос
POLL     = os.environ.get("KN_TG_POLL") == "1"
THREAD   = (os.environ.get("KN_TG_THREAD") or "").strip()          # id темы в группе, если слушаем только её

AI_KEY   = (os.environ.get("KN_AI_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
AI_BASE  = (os.environ.get("KN_AI_BASE") or "https://api.groq.com/openai/v1").rstrip("/")
AI_MODEL = os.environ.get("KN_AI_MODEL") or "openai/gpt-oss-120b"
STT_MODEL = os.environ.get("KN_STT_MODEL") or "whisper-large-v3"
# У бесплатного Groq лимит 8000 токенов в минуту на каждую модель. Когда упираемся в одну,
# сразу берём вторую с таким же умением вызывать инструменты — вместо того чтобы ждать минуту.
MODELS = [m.strip() for m in (os.environ.get("KN_AI_MODELS") or (AI_MODEL + ",qwen/qwen3.8-27b")).split(",") if m.strip()]

API = "https://api.telegram.org/bot%s/" % TOKEN
FILE_API = "https://api.telegram.org/file/bot%s/" % TOKEN
CFG = {}          # server.py кладёт сюда port и web_url

# Помощник правит на сайте всё: компании, бутики, товары, депозиты, платежи, получение,
# настройки, резервные копии. Закрыт один адрес, который нечем откатить:
# замена всей базы файлом.
FORBIDDEN = ("/api/restore",)

def enabled(): return bool(TOKEN and AI_KEY)

# ---------------------------------------------------------------- мелкая утварь
def log(*a): print("[бот]", *a, flush=True)

UA = "curl/8.7.1"   # Cloudflare перед Groq отвечает 403 на стандартный User-Agent питона

def _req(url, data=None, headers=None, method=None, timeout=120, raw=False):
    h = dict(headers or {}); h.setdefault("User-Agent", UA)
    r = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
    return body if raw else json.loads(body.decode("utf-8") or "{}")

def tg(method, **payload):
    """Вызов Telegram Bot API. Ошибки не роняют бота — только пишутся в журнал."""
    try:
        return _req(API + method, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, timeout=60)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        log(method, "ошибка", e.code, body)
        return {"ok": False, "description": body}
    except Exception as e:
        log(method, "ошибка", e); return {"ok": False, "description": str(e)}

def say(chat, text, kb=None, reply_to=None, thread=None):
    """Ответ в чат. Если модель написала разметку, которую Telegram не принял, шлём чистым текстом."""
    p = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb: p["reply_markup"] = {"inline_keyboard": kb}
    if reply_to: p["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    if thread: p["message_thread_id"] = thread
    r = tg("sendMessage", **p)
    if not r.get("ok") and "parse" in (r.get("description") or "").lower():
        p.pop("parse_mode", None); p["text"] = re.sub(r"</?[a-zA-Z][^>]*>", "", text)[:4000]
        r = tg("sendMessage", **p)
    return r

def react(chat, msg_id, emoji):
    """Реакция на сообщение владельца: 👀 принял, 👍 сделал, 🤔 нужен ответ, 😐 не смог."""
    tg("setMessageReaction", chat_id=chat, message_id=msg_id,
       reaction=[{"type": "emoji", "emoji": emoji}] if emoji else [])

def typing(chat): tg("sendChatAction", chat_id=chat, action="typing")

# ---------------------------------------------------------------- доступ к данным программы
def api(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (CFG.get("port", 8902), path)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    hdr = {"Content-Type": "application/json; charset=utf-8"}
    try:
        return _req(url, data=data, headers=hdr, method=method, timeout=90)
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read().decode("utf-8")).get("error") or ("код %d" % e.code)
        except Exception: msg = "код %d" % e.code
        raise RuntimeError(msg)

KINDS = {"companies": "компания", "boutiques": "бутик", "items": "товар", "payments": "платёж", "settings": "настройки"}
# вычисляемые поля карточек — их нельзя записать обратно
SKIP = {"ok", "items_total", "total", "paid_own", "paid", "remaining", "overpaid",
        "items_count", "payments_count", "qty_total", "received_total", "company_name", "company_date",
        "boutiques", "boutiques_count", "items", "payments", "boutique", "created_at", "updated_at"}

def fetch_one(path):
    """Состояние записи до изменения — чтобы кнопка «Отменить» вернула как было."""
    if path != "/api/settings" and not re.match(r"^/api/(companies|boutiques|items|payments)/\d+$", path): return None
    try: return api("GET", path)
    except Exception: return None

def clean(row):
    """Убираем вычисляемые поля — остаётся только то, что можно записать обратно."""
    if not isinstance(row, dict): return row
    return {k: v for k, v in row.items() if k not in SKIP}

def data_get(path):
    if not path.startswith("/api/"): path = "/api/" + path.lstrip("/")
    return api("GET", path)

def data_write(method, path, body, journal):
    """Запись с журналом отката. Опасное (восстановление базы, пользователи) закрыто."""
    if not path.startswith("/api/"): path = "/api/" + path.lstrip("/")
    if any(path.startswith(x) for x in FORBIDDEN):
        return {"error": "это можно только руками на сайте"}
    method = (method or "POST").upper()
    before = fetch_one(path) if method in ("PATCH", "DELETE", "POST") and path == "/api/settings" \
             else (fetch_one(path) if method in ("PATCH", "DELETE") else None)
    r = api(method, path, None if method == "DELETE" else (body or {}))
    base = re.sub(r"/\d+$", "", path)
    kind = KINDS.get(base.rsplit("/", 1)[-1], "запись")
    if method == "POST":
        nid = (r.get("id") or (r.get("row") or {}).get("id")) if isinstance(r, dict) else None
        if nid:
            journal.append({"what": "%s №%s создана" % (kind, nid),
                            "undo": ("DELETE", "%s/%s" % (base, nid), None)})
    elif method == "PATCH" and before is not None:
        if path == "/api/settings":
            journal.append({"what": "настройки изменены", "undo": ("PATCH", path, clean(before))})
        else:
            journal.append({"what": "%s №%s изменена" % (kind, path.rsplit("/", 1)[-1]), "undo": ("PATCH", path, clean(before))})
    elif method == "DELETE" and before is not None:
        journal.append({"what": "%s №%s удалена" % (kind, path.rsplit("/", 1)[-1]), "undo": ("POST", base, clean(before))})
    return r

def undo(journal):
    done = []
    for op in reversed(journal or []):
        m, path, body = op["undo"]
        try:
            api(m, path, body); done.append(op["what"])
        except Exception as e:
            log("откат не удался:", m, path, e)
    return done

# ---------------------------------------------------------------- деньги, даты, валюты
CUR_SIGN = {"USD": "$", "CNY": "¥", "KGS": "сом", "KZT": "₸", "RUB": "₽", "UZS": "сум"}
_fx = {"at": 0, "rates": {}}

def fx_rates():
    """Курсы к доллару — бесплатный открытый источник, не чаще раза в 12 часов."""
    if _fx["rates"] and time.time() - _fx["at"] < 12 * 3600: return _fx["rates"]
    try:
        d = _req("https://open.er-api.com/v6/latest/USD", timeout=20)
        if d.get("result") == "success" and d.get("rates"):
            _fx["rates"] = d["rates"]; _fx["at"] = time.time()
    except Exception as e:
        log("курсы недоступны:", e)
    return _fx["rates"]

def fx_line():
    r = fx_rates()
    got = [(c, r.get(c)) for c in ("CNY", "KGS", "KZT", "RUB") if r.get(c)]
    return ("Курсы за 1 доллар: " + ", ".join("%s %g" % (c, round(v, 2)) for c, v in got)) if got else ""

def money(v, cur="USD"):
    try: v = float(v or 0)
    except Exception: v = 0.0
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    whole, frac = (s.split(".") + [""])[:2]
    neg = whole.startswith("-"); whole = whole.lstrip("-")
    whole = " ".join(re.findall(r"\d{1,3}(?=(?:\d{3})*$)", whole)) or whole
    return ("−" if neg else "") + whole + ("," + frac if frac else "") + " " + CUR_SIGN.get(cur, cur)

def d_ru(s):
    try: return datetime.strptime((s or "")[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception: return s or ""

def today(): return date.today().isoformat()

def norm(s):
    s = (s or "").lower().replace("ё", "е").replace("ү", "у").replace("ө", "о").replace("ң", "н")
    return re.sub(r"[^a-zа-я0-9]+", "", s)

# ---------------------------------------------------------------- речь → текст
def _multipart(fields, fname, fbytes, ctype="audio/ogg"):
    b = b"--boundary41\r\n"
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(b); out.write(('Content-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (k, v)).encode("utf-8"))
    out.write(b)
    out.write(('Content-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
               % (fname, ctype)).encode("utf-8"))
    out.write(fbytes); out.write(b"\r\n--boundary41--\r\n")
    return out.getvalue()

def transcribe(audio, fname, hint="", language=None):
    fields = {"model": STT_MODEL, "response_format": "json", "temperature": "0"}
    if hint: fields["prompt"] = hint[:800]
    if language: fields["language"] = language
    try:
        d = _req(AI_BASE + "/audio/transcriptions", data=_multipart(fields, fname, audio),
                 headers={"Authorization": "Bearer " + AI_KEY,
                          "Content-Type": "multipart/form-data; boundary=boundary41"}, timeout=180)
        return (d.get("text") or "").strip()
    except urllib.error.HTTPError as e:
        log("расшифровка:", e.code, e.read()[:200].decode("utf-8", "replace")); return ""
    except Exception as e:
        log("расшифровка:", e); return ""

def listen(audio, fname, hint):
    """Две расшифровки одновременно: свободная и «как русскую речь»."""
    res = {}
    def go(key, lang): res[key] = transcribe(audio, fname, hint, language=lang)
    th = [threading.Thread(target=go, args=("a", None)), threading.Thread(target=go, args=("b", "ru"))]
    for t in th: t.start()
    for t in th: t.join(180)
    out, seen = [], set()
    for k in ("a", "b"):
        t = (res.get(k) or "").strip()
        if t and norm(t) not in seen: seen.add(norm(t)); out.append(t)
    return (out[0] if out else ""), out

# ---------------------------------------------------------------- справочник для подсказок
def context():
    return {"companies": api("GET", "/api/companies").get("rows", []),
            "boutiques": api("GET", "/api/boutiques").get("rows", []),
            "currency": (api("GET", "/api/settings") or {}).get("currency") or "USD"}

def brief(ctx):
    co = [{"id": x["id"], "название": x.get("name") or "", "дата": x["date"], "бутиков": x.get("boutiques_count"),
           "стоимость": x.get("total"), "оплачено": x.get("paid"), "остаток": x.get("remaining")} for x in ctx["companies"]]
    bs = [{"id": x["id"], "компания_id": x["company_id"], "город": x["city"], "бутик": x["name"],
           "стоимость": x.get("total"), "депозит": x.get("deposit"),
           "санжар_заплатил": x.get("paid_own"), "остаток": x.get("remaining"), "получение": x.get("receipt_status")}
          for x in ctx["boutiques"][-30:]]
    return json.dumps({"валюта": ctx["currency"], "компании": co, "бутики": bs}, ensure_ascii=False)

def hints(ctx):
    cities = list(dict.fromkeys(x["city"] for x in ctx["boutiques"]))[:12]
    names = [x["name"] for x in ctx["boutiques"]][-20:]
    return ("Закуп товаров у бутиков. Города: %s. Бутики: %s. "
            "Слова: Санжар, депозит, заплатил, остаток, получил, бутик, компания, доллар, юань, сом, жүз, миң, Гуанчжоу, Иу, Урумчи."
            % (", ".join(cities) or "Гуанчжоу, Иу", ", ".join(names) or "бутик 12"))

# ---------------------------------------------------------------- помощник с полным доступом
SYSTEM = """Ты — помощник владельца в его программе учёта закупок у бутиков. Общаешься в Telegram, по-русски,
коротко и по-человечески. У тебя ПОЛНЫЙ доступ к данным программы через инструменты data_get (читать)
и data_write (создавать, изменять, удалять). Работу делаешь сам, не отправляй владельца «зайти на сайт».

УСТРОЙСТВО УЧЁТА: Компания → Бутики → Закупка бутика (товары + финансы).
• /api/summary — итоги по всем компаниям.
• /api/companies — GET список, POST создать {date ГГГГ-ММ-ДД, name, note}.
  /api/companies/{id} — GET карточка с бутиками, PATCH изменить, DELETE удалить вместе с бутиками.
• /api/boutiques — GET список (?company=id), POST создать {company_id, city, name (номер или название), note}.
  /api/boutiques/{id} — GET карточка: товары items[], платежи payments[] и все цифры; PATCH изменить; DELETE удалить.
  Поля PATCH: city, name, note; total_mode (items — стоимость по товарам | manual — одной суммой) и manual_total;
  deposit (сумма депозита), deposit_date, deposit_note; receipt_status (none не получен | partial частично | full полностью),
  receipt_date, receipt_note, received: [{id товара, received_qty}].
• /api/items — POST {boutique_id, product, qty, unit_price, amount, note}; /api/items/{id} — GET, PATCH, DELETE.
  qty, unit_price, amount, note необязательны. Если есть qty и unit_price, amount считается сам.
• /api/payments — платежи Санжара (его собственные деньги): POST {boutique_id, date, amount, note}; /api/payments/{id} — GET, PATCH, DELETE.
  Поле source не передавай: депозит платежом не списывается.
• /api/settings — GET, PATCH: currency (USD|KGS|KZT|RUB|CNY|EUR). /api/backup — POST резервная копия.

ФИНАНСЫ БУТИКА считает программа, ты только записываешь операции:
стоимость = сумма товаров (или manual_total); депозит — залог / предоплата, он СРАЗУ вычитается из стоимости;
остаток = стоимость − депозит − платежи Санжара; переплата показывается отдельно. Депозит и платежи Санжара — разные
вещи: не записывай депозит как платёж и не дублируй его.
Оплата и получение товара — разные вещи: receipt_status меняй только когда владелец говорит, что товар пришёл.

КАК РАБОТАТЬ:
— Справочник компаний и бутиков дан ниже: бери id оттуда, лишний раз не запрашивай.
— Бутик не назван — бери последний подходящий из справочника; если неясно, спроси одной строкой: «В какой бутик?».
— Бутика нет, но владелец назвал его («бутик 12 в Гуанчжоу») — создай в последней компании и используй.
  Нет ни одной компании — создай с сегодняшней датой. Город не назван — спроси, заглушек не заводи.
— «Внёс депозит» → PATCH бутика deposit. «Заплатил», «Санжар заплатил» → POST /api/payments.
  Залог, предоплата, «оставил в залог» — это депозит (PATCH бутика), а не платёж. «Товар на столько-то» без списка → total_mode manual.
— «Товар пришёл / келди / жетти» → receipt_status full (или partial с количествами), оплату не трогай.
— Даты ГГГГ-ММ-ДД. Не названа — сегодня. «Через 10 дней» считай сам.
— Сумма в другой валюте — переведи по курсам ниже в валюту программы, а в note укажи исходную сумму и курс.
— Не выдумывай числа и имена. Не уверен — сделай понятную часть, а про остальное спроси одним коротким вопросом.
— Прежде чем отвечать про цифры, посмотри данные через data_get, не считай по памяти.
— Сделал — ответь коротко: что записал, суммы, сколько осталось оплатить. Разметка только <b>жирный</b> и <i>курсив</i>.
— Одного делать нельзя: заменить всю базу файлом (/api/restore) — про это скажи, что это только на сайте, кнопкой.
— Прежде чем удалять несколько записей разом или менять настройки, скажи одной строкой, что именно
  удаляешь, и сделай. Владелец всегда может вернуть кнопкой «Отменить» или командой /отмена.

РЕЧЬ ВЛАДЕЛЬЦА: кыргызский, русский, смесь, иногда китайский. Могут дать две расшифровки одного
голосового — сравни их. Whisper не знает кыргызского и коверкает слова, восстанавливай смысл:
бир 1, эки 2, үч 3, төрт 4, беш 5, алты 6, жети 7, сегиз 8, тогуз 9, он 10, жыйырма 20, отуз 30, кырк 40,
элүү 50, алтымыш 60, жетимиш 70, сексен 80, токсон 90, жүз 100, миң 1000. Искажения: «жүз»→«герц/юз/гуз»,
«миң»→«мин/минг/мың», «беш»→«биш/бещ», «үч»→«уч/уй». «беш жүз» = 500, «он беш миң» = 15000.
Слова: алдым купил, бердим/төлөдүм заплатил, берди дал мне, аванс предоплата, карыз/калганы долг/остаток,
келет придёт, жөнөттү/чыкты отправлено, келди/жетти пришло, дүкөн/магазин магазин, базар рынок,
бүгүн сегодня, кечээ вчера, эртең завтра. Обращения ага, аке, байке, эже, апа, агай — вежливость,
а не часть имени: «Ли Вэй ага» → поставщик «Ли Вэй». Товар — это вещь (чемодан, посуда, фен),
никогда не имя человека и не город."""

TOOLS = [
    {"type": "function", "function": {
        "name": "data_get",
        "description": "Прочитать данные учёта по адресу API, например /api/summary или /api/boutiques/5",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "data_write",
        "description": "Создать (POST), изменить (PATCH) или удалить (DELETE) запись учёта",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string", "enum": ["POST", "PATCH", "DELETE"]},
            "path": {"type": "string"},
            "body": {"type": "object", "description": "Поля записи для POST и PATCH"}},
            "required": ["method", "path"]}}},
]

def ai(payload, timeout=120, rounds=3):
    """Запрос к модели: занята — берём следующую из списка, кончились — ждём и заходим снова."""
    last = None
    for rnd in range(rounds):
        for model in MODELS:
            try:
                d = _req(AI_BASE + "/chat/completions",
                         data=json.dumps({**payload, "model": model}, ensure_ascii=False).encode("utf-8"),
                         headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"},
                         timeout=timeout)
                return d["choices"][0]["message"]
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (400, 429, 500, 502, 503, 520, 522): raise
                log("%s занята (%d)" % (model, e.code))
        wait = 4 + rnd * 6
        try: wait = min(25, max(wait, float(last.headers.get("retry-after") or 0)))
        except Exception: pass
        log("все модели заняты, жду %.0f с" % wait); time.sleep(wait)
    raise RuntimeError("модель не отвечает (%s)" % getattr(last, "code", "?"))

def sane(ans, journal):
    """Запасная модель под нагрузкой иногда выдаёт кашу («Ай только только только»).
    Данные при этом записаны верно — тогда отвечаем по журналу, а не бредом."""
    txt = re.sub(r"<[^>]+>", " ", ans or "").strip()
    words = re.findall(r"\w+", txt.lower())
    bad = not txt or (len(words) >= 3 and len(set(words)) <= max(2, len(words) // 3))
    if not bad: return ans
    if journal:
        return "Записал: " + ", ".join(x["what"] for x in journal) + ".\nСловами объяснить не смог — модель была занята."
    return "Модель сейчас перегружена, ничего не записал. Повторите, пожалуйста."

def work(texts, ctx, history):
    """Один заход помощника: читает и меняет данные, пока не ответит словами."""
    said = ("Расшифровки одного голосового:\n" + "\n".join("%d) %s" % (i + 1, t) for i, t in enumerate(texts))) \
        if len(texts) > 1 else (texts[0] if texts else "")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "system", "content": "Сегодня %s (%s). %s\nСправочник: %s"
             % (d_ru(today()), today(), fx_line(), brief(ctx))}]
    msgs += history[-4:]
    msgs.append({"role": "user", "content": said})
    journal, steps = [], []
    for _ in range(12):
        m = ai({"messages": msgs, "tools": TOOLS, "tool_choice": "auto", "temperature": 0.1})
        calls = m.get("tool_calls") or []
        if not calls:
            return sane((m.get("content") or "").strip(), journal), journal, steps, said
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = (c.get("function") or {}).get("name")
            try: args = json.loads((c.get("function") or {}).get("arguments") or "{}")
            except Exception: args = {}
            try:
                if fn == "data_get":
                    res = data_get(args.get("path") or "/api/summary")
                elif fn == "data_write":
                    res = data_write(args.get("method"), args.get("path") or "", args.get("body") or {}, journal)
                    steps.append("%s %s" % (args.get("method"), args.get("path")))
                else:
                    res = {"error": "нет такого инструмента"}
            except Exception as e:
                res = {"error": str(e)}
            msgs.append({"role": "tool", "tool_call_id": c.get("id"),
                         "content": json.dumps(res, ensure_ascii=False)[:3500]})
    return "Запутался в задаче — скажите иначе, пожалуйста.", journal, steps, said

# ---------------------------------------------------------------- разговор
HIST = {}        # chat_id → последние реплики
LAST = {}        # chat_id → журнал последних изменений (для кнопки «Отменить»)
SEEN = set()     # update_id, чтобы не выполнить одно и то же дважды
Q = queue.Queue()

HELP = ("<b>Бутики · учёт — ваш помощник</b>\n\n"
        "Говорите или пишите обычными словами, как человеку:\n"
        "«Гуанчжоу, бутик 12: он сумка алдым, ар бири жыйырма беш доллар, депозит жүз, "
        "Санжар элүү доллар төлөдү».\n\n"
        "Я сам запишу бутик, товары, депозит и платёж и скажу, сколько осталось оплатить. "
        "Могу менять и удалять записи, отмечать получение товара, менять валюту.\n\n"
        "Только замену всей базы файлом делайте сами на сайте.\n\n"
        "Спрашивайте что угодно: «канча калды?», «сколько заплатил Санжар в бутике 12», «итоги».\n\n"
        "Команды: /итоги · /долги · /бутики · /отмена · /помощь")

def cur():
    try: return (api("GET", "/api/settings") or {}).get("currency") or "USD"
    except Exception: return "USD"

def cmd(chat, text, thread):
    t = text.lower().lstrip("/").split("@")[0]
    if t.startswith(("start", "помощь", "help")): say(chat, HELP, thread=thread); return True
    if t.startswith("id"):
        say(chat, "Этот чат: <code>%s</code>\nТема: <code>%s</code>" % (chat, thread or "—"), thread=thread); return True
    if t.startswith(("итог", "сводка")):
        d, c = api("GET", "/api/summary"), cur()
        say(chat, "<b>Итоги</b>\nКомпаний: %s · бутиков: %s\nСтоимость закупок: %s\nОплачено: %s (депозит %s · Санжар %s)\n"
                  "Осталось оплатить: %s%s"
            % (d.get("companies"), d.get("boutiques"), money(d.get("total"), c), money(d.get("paid"), c),
               money(d.get("deposit"), c), money(d.get("paid_own"), c), money(d.get("remaining"), c),
               ("\nПереплата: " + money(d.get("overpaid"), c)) if d.get("overpaid") else ""), thread=thread); return True
    if t.startswith(("долг", "карыз", "остат")):
        bs = [b for b in api("GET", "/api/boutiques").get("rows", []) if (b.get("remaining") or 0) > 0]
        bs.sort(key=lambda b: -(b.get("remaining") or 0)); c = cur()
        say(chat, "<b>Осталось оплатить</b>\n" + ("\n".join(
            "• %s · %s — %s" % (b["city"], b["name"], money(b["remaining"], c)) for b in bs) or "всё оплачено"),
            thread=thread); return True
    if t.startswith(("отмен", "откат")):
        done = undo(LAST.pop(chat, []))
        say(chat, "↩️ Вернул как было: " + (", ".join(done) if done else "нечего отменять"), thread=thread); return True
    if t.startswith(("бутик", "парти", "список")):
        rows = api("GET", "/api/boutiques").get("rows", [])[-10:]; c = cur()
        st = {"none": "не получен", "partial": "получен частично", "full": "получен полностью"}
        say(chat, "<b>Бутики</b>\n" + ("\n".join(
            "• №%d %s · %s — %s, оплачено %s, остаток %s, %s" % (r["id"], r["city"], r["name"], money(r.get("total"), c),
                                                                 money(r.get("paid"), c), money(r.get("remaining"), c),
                                                                 st.get(r.get("receipt_status"), ""))
            for r in rows) or "пока пусто"), thread=thread); return True
    return False

def handle(u):
    msg = u.get("message") or u.get("edited_message")
    if u.get("callback_query"): return handle_button(u["callback_query"])
    if not msg: return
    chat = msg["chat"]["id"]
    who = msg.get("from") or {}
    frm = str(who.get("id") or "")
    thread = msg.get("message_thread_id")
    if who.get("is_bot"): return                       # чужие боты в группе нас не касаются
    if ALLOW and frm not in ALLOW and str(chat) not in ALLOW:
        say(chat, "Это личный помощник владельца.\nВаш id: <code>%s</code>" % frm, thread=thread)
        log("чужой:", frm, who.get("username")); return
    mid = msg["message_id"]
    voice = msg.get("voice") or msg.get("audio") or msg.get("video_note")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if text.startswith("/") and cmd(chat, text, thread): return
    if not (voice or text): return
    # В группе голосовые берём из любой темы, а текст — только из своей (или когда обратились к боту),
    # чтобы не встревать в переписку владельца с другими помощниками.
    if msg["chat"].get("type") in ("group", "supergroup") and THREAD and str(thread or "") != THREAD:
        me = "@" + (CFG.get("me") or "")
        replied = ((msg.get("reply_to_message") or {}).get("from") or {}).get("is_bot")
        if not voice:
            if not (replied or (me != "@" and me.lower() in text.lower())): return
            say(chat, "Я слушаю в своей теме — напишите там, и я всё сделаю.", reply_to=mid, thread=thread)
            return
    text = re.sub(r"@\w+", "", text).strip() if text else text

    react(chat, mid, "👀")
    typing(chat)
    try:
        ctx = context()
        if voice:
            f = tg("getFile", file_id=voice["file_id"]).get("result") or {}
            if not f.get("file_path"):
                react(chat, mid, "😐"); say(chat, "Не смог забрать голосовое, пришлите ещё раз", thread=thread); return
            audio = _req(FILE_API + f["file_path"], raw=True, timeout=120)
            ext = (os.path.splitext(f["file_path"])[1] or "").lower()
            name = "voice.ogg" if ext in ("", ".oga", ".ogg") else "voice" + ext   # .oga Groq не принимает
            _, texts = listen(audio, name, hints(ctx))
            if not texts:
                react(chat, mid, "😐")
                say(chat, "Не разобрал речь — попробуйте ещё раз или напишите текстом.", thread=thread); return
            log("голос:", " | ".join(t[:160] for t in texts))   # видно в журнале — по нему подстраиваю распознавание
            if text: texts = [t + " " + text for t in texts]
        else:
            texts = [text]

        reply, journal, steps, said = work(texts, ctx, HIST.get(chat, []))
        head = ("🎙 <i>%s</i>\n\n" % texts[0][:300]) if voice else ""
        kb = None
        if journal:
            LAST[chat] = journal
            kb = [[{"text": "↩️ Отменить", "callback_data": "undo"}]]
            if (CFG.get("web_url") or "").startswith("https://"):
                kb[0].append({"text": "📋 Открыть", "url": CFG["web_url"]})
        say(chat, head + (reply or "Готово."), kb=kb, reply_to=mid, thread=thread)
        react(chat, mid, "👍" if journal else "🤔")

        h = HIST.setdefault(chat, [])
        h.append({"role": "user", "content": said})
        h.append({"role": "assistant",
                  "content": (reply or "")[:1500] + (("\n[сделано: " + "; ".join(steps) + "]") if steps else "")})
        del h[:-6]
    except Exception as e:
        import traceback; traceback.print_exc()
        react(chat, mid, "😐")
        say(chat, "Не смог обработать: %s" % e, thread=thread)

def handle_button(cb):
    chat = cb["message"]["chat"]["id"]
    frm = str((cb.get("from") or {}).get("id") or "")
    if ALLOW and frm not in ALLOW and str(chat) not in ALLOW:
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Только владельцу"); return
    if cb.get("data") == "undo":
        done = undo(LAST.pop(chat, []))
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Отменено" if done else "Уже нечего отменять")
        tg("editMessageReplyMarkup", chat_id=chat, message_id=cb["message"]["message_id"],
           reply_markup={"inline_keyboard": []})
        say(chat, "↩️ Вернул как было: " + (", ".join(done) if done else "нечего отменять"))

# ---------------------------------------------------------------- запуск
def worker():
    while True:
        u = Q.get()
        try: handle(u)
        except Exception as e: log("сбой обработчика:", e)
        finally: Q.task_done()

def enqueue(update):
    uid = update.get("update_id")
    if uid in SEEN: return
    SEEN.add(uid)
    if len(SEEN) > 800: SEEN.clear()
    Q.put(update)

def poll():
    """Локальная отладка: опрашиваем Telegram сами (в облаке вместо этого вебхук)."""
    tg("deleteWebhook", drop_pending_updates=False)
    off = 0
    while True:
        try:
            d = _req(API + "getUpdates?timeout=50&offset=%d" % off, timeout=70)
            for u in d.get("result", []):
                off = u["update_id"] + 1
                enqueue(u)
        except Exception as e:
            log("опрос:", e); time.sleep(3)

def start(cfg):
    """Вызывается из server.py при старте. Возвращает True, если помощник включён."""
    CFG.update(cfg)
    if not enabled():
        if TOKEN and not AI_KEY: log("нет ключа ИИ (KN_AI_KEY) — помощник выключен")
        return False
    for _ in range(2):
        threading.Thread(target=worker, daemon=True).start()
    me = (tg("getMe").get("result") or {}).get("username")
    CFG["me"] = me
    if HOOK_URL:
        r = tg("setWebhook", url=HOOK_URL, secret_token=SECRET,
               allowed_updates=["message", "edited_message", "callback_query"], drop_pending_updates=True)
        log("вебхук @%s → %s: %s" % (me, HOOK_URL, "готов" if r.get("ok") else r))
    elif POLL:
        threading.Thread(target=poll, daemon=True).start()
        log("опрос Telegram запущен, помощник @%s" % me)
    else:
        log("помощник @%s подключён (нужен KN_TG_POLL=1 или KN_TG_HOOK_URL)" % me)
    return True
