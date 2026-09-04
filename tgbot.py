#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Китай · учёт — управление голосом через Telegram (этап 6).

Владелец наговаривает в бота обычными словами (кыргызский, русский, смесь, китайский),
бот сам расшифровывает речь, понимает смысл и заполняет учёт:
партии, товары по магазинам, авансы и платежи, долги, вложения инвесторов, статусы.

Цепочка: голос → Whisper (Groq, бесплатно) → LLM-разбор в набор операций →
те же самые /api/… что и у сайта → короткий отчёт в чат + кнопка «Отменить».

Модуль сознательно не лезет в базу напрямую: все записи идут через внутренние
HTTP-запросы к своему же серверу, поэтому вся проверка данных, автоперенос аванса
в платежи и пересчёт долгов работают ровно так же, как при вводе руками.
"""
import io, json, os, re, difflib, threading, time, queue, urllib.request, urllib.error
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- настройки
TOKEN   = (os.environ.get("KN_TG_TOKEN") or "").strip()
SECRET  = (os.environ.get("KN_TG_SECRET") or "").strip()          # подпись вебхука Telegram
ALLOW   = {s.strip() for s in (os.environ.get("KN_TG_ALLOW") or "").split(",") if s.strip()}
HOOK_URL = (os.environ.get("KN_TG_HOOK_URL") or "").strip()       # https://…/api/tg/hook — если пусто, работаем опросом
POLL    = os.environ.get("KN_TG_POLL") == "1"
THREAD  = (os.environ.get("KN_TG_THREAD") or "").strip()   # id темы в группе, если нужно слушать только её

AI_KEY   = (os.environ.get("KN_AI_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
AI_BASE  = (os.environ.get("KN_AI_BASE") or "https://api.groq.com/openai/v1").rstrip("/")
AI_MODEL = os.environ.get("KN_AI_MODEL") or "openai/gpt-oss-120b"
STT_MODEL = os.environ.get("KN_STT_MODEL") or "whisper-large-v3"

API = "https://api.telegram.org/bot%s/" % TOKEN
FILE_API = "https://api.telegram.org/file/bot%s/" % TOKEN
CFG = {}          # заполняет server.py при старте: port, token(), log()

def enabled(): return bool(TOKEN and AI_KEY)

# ---------------------------------------------------------------- мелкая утварь
def log(*a):
    print("[бот]", *a, flush=True)

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
        log(method, "ошибка", e.code, e.read()[:300].decode("utf-8", "replace")); return {}
    except Exception as e:
        log(method, "ошибка", e); return {}

def say(chat, text, kb=None, reply_to=None, thread=None):
    p = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb: p["reply_markup"] = {"inline_keyboard": kb}
    if reply_to: p["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    if thread: p["message_thread_id"] = thread
    return tg("sendMessage", **p)

def react(chat, msg_id, emoji):
    """Реакция на сообщение владельца: 👀 принял в работу, 👍 записал, 🤔 нужен ответ, 😐 не смог."""
    tg("setMessageReaction", chat_id=chat, message_id=msg_id,
       reaction=[{"type": "emoji", "emoji": emoji}] if emoji else [])

def typing(chat, action="typing"):
    tg("sendChatAction", chat_id=chat, action=action)

# ---------------------------------------------------------------- свой API (та же логика, что у сайта)
def api(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (CFG.get("port", 8902), path)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    hdr = {"Content-Type": "application/json; charset=utf-8", "Cookie": "kn_session=" + (CFG.get("token", lambda: "")() or "")}
    try:
        return _req(url, data=data, headers=hdr, method=method, timeout=90)
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read().decode("utf-8")).get("error") or ("код %d" % e.code)
        except Exception: msg = "код %d" % e.code
        raise RuntimeError(msg)

# ---------------------------------------------------------------- деньги, даты, валюты
CUR_WORDS = {
    "USD": ["доллар", "доллор", "бакс", "usd", "$", "долар", "доллары", "долларов"],
    "CNY": ["юань", "юан", "жуань", "rmb", "cny", "куай", "женьмин", "юаня", "юаней"],
    "KGS": ["сом", "сому", "сомов", "kgs", "сомго", "сомду"],
    "KZT": ["тенге", "тнг", "kzt", "теңге"],
    "RUB": ["рубл", "руб", "rub", "рублей"],
    "UZS": ["сум", "узбекс", "uzs", "сумов"],
}
CUR_SIGN = {"USD": "$", "CNY": "¥", "KGS": "сом", "KZT": "₸", "RUB": "₽", "UZS": "сум"}
_fx = {"at": 0, "rates": {}}

def fx_rates():
    """Курсы к доллару — бесплатный открытый источник, обновляем не чаще раза в 12 часов."""
    if _fx["rates"] and time.time() - _fx["at"] < 12 * 3600: return _fx["rates"]
    try:
        d = _req("https://open.er-api.com/v6/latest/USD", timeout=20)
        if d.get("result") == "success" and d.get("rates"):
            _fx["rates"] = d["rates"]; _fx["at"] = time.time()
    except Exception as e:
        log("курсы недоступны:", e)
    return _fx["rates"]

def convert(amount, frm, to):
    """Перевод суммы в валюту партии. Возвращает (сумма, пояснение) — пояснение уходит в комментарий записи."""
    if not amount or not frm or frm == to: return amount, ""
    r = fx_rates()
    if not (r.get(frm) and r.get(to)): return amount, ""
    usd = float(amount) / float(r[frm])
    out = round(usd * float(r[to]), 2)
    return out, "%s %s по курсу %s" % (money(amount, frm), "→", round(float(r[to]) / float(r[frm]), 4))

def money(v, cur="USD"):
    try: v = float(v or 0)
    except Exception: v = 0.0
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    if "." in s: whole, frac = s.split("."); frac = "," + frac
    else: whole, frac = s, ""
    neg = whole.startswith("-"); whole = whole.lstrip("-")
    whole = " ".join(re.findall(r"\d{1,3}(?=(?:\d{3})*$)", whole)) or whole
    return ("−" if neg else "") + whole + frac + " " + CUR_SIGN.get(cur, cur)

def d_ru(s):
    try: return datetime.strptime((s or "")[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception: return s or ""

def today(): return date.today().isoformat()

def norm(s):
    """Грубая нормализация имени: без регистра, без ё/й-различий и лишних знаков — для сопоставления на слух."""
    s = (s or "").lower().replace("ё", "е").replace("ү", "у").replace("ө", "о").replace("ң", "н")
    return re.sub(r"[^a-zа-я0-9]+", "", s)

# ---------------------------------------------------------------- речь → текст
def _multipart(fields, fname, fbytes, ctype="audio/ogg"):
    b = b"--boundary41\r\n"
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(b); out.write(('Content-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (k, v)).encode("utf-8"))
    out.write(b)
    out.write(('Content-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: %s\r\n\r\n' % (fname, ctype)).encode("utf-8"))
    out.write(fbytes); out.write(b"\r\n--boundary41--\r\n")
    return out.getvalue()

def transcribe(audio, fname, hint="", language=None):
    fields = {"model": STT_MODEL, "response_format": "json", "temperature": "0"}
    if hint: fields["prompt"] = hint[:800]
    if language: fields["language"] = language
    body = _multipart(fields, fname, audio)
    try:
        d = _req(AI_BASE + "/audio/transcriptions", data=body,
                 headers={"Authorization": "Bearer " + AI_KEY,
                          "Content-Type": "multipart/form-data; boundary=boundary41"}, timeout=180)
        return (d.get("text") or "").strip()
    except urllib.error.HTTPError as e:
        log("расшифровка:", e.code, e.read()[:200].decode("utf-8", "replace")); return ""
    except Exception as e:
        log("расшифровка:", e); return ""

def listen(audio, fname, hint):
    """Две расшифровки сразу — свободная и «как русскую речь». Кыргызского в Whisper нет,
    поэтому две версии дают LLM шанс восстановить слова по расхождениям."""
    res = {}
    def go(key, lang):
        res[key] = transcribe(audio, fname, hint, language=lang)
    th = [threading.Thread(target=go, args=("a", None)), threading.Thread(target=go, args=("b", "ru"))]
    for t in th: t.start()
    for t in th: t.join(180)
    out, seen = [], set()
    for k in ("a", "b"):
        t = (res.get(k) or "").strip()
        if t and norm(t) not in seen: seen.add(norm(t)); out.append(t)
    return (out[0] if out else ""), out

# ---------------------------------------------------------------- справочники и контекст
def context():
    """Всё, что нужно LLM, чтобы попадать в существующие имена, а не плодить двойников."""
    parts = api("GET", "/api/partners")
    stores = api("GET", "/api/stores")
    ships = api("GET", "/api/shipments?limit=400").get("rows", [])
    return {"partners": parts, "stores": stores, "ships": ships}

def brief(ctx):
    p = [{"id": x["id"], "имя": x["name"], "валюта": x.get("currency") or "USD",
          "город": x.get("city") or "", "роль": ("инвестор" if x.get("is_investor") else "") + ("поставщик" if x.get("is_supplier") else "")}
         for x in ctx["partners"] if x.get("active", 1)]
    s = [{"id": x["id"], "номер": x.get("number"), "название": x.get("name") or ""} for x in ctx["stores"] if x.get("active", 1)]
    sh = [{"id": x["id"], "дата": x["date"], "поставщик": x.get("supplier_name"), "сумма": x.get("amount"),
           "валюта": x.get("currency"), "статус": x.get("status"), "долг": x.get("balance")}
          for x in ctx["ships"][:8]]
    return json.dumps({"поставщики_и_инвесторы": p, "магазины": s, "последние_партии": sh},
                      ensure_ascii=False)

def hints(ctx):
    """Подсказка для Whisper: имена и слова, которые он иначе перевирает."""
    names = [x["name"] for x in ctx["partners"] if x.get("active", 1)][:25]
    st = [str(x.get("name") or x.get("number")) for x in ctx["stores"] if x.get("active", 1)][:15]
    goods = [i.get("product") for x in ctx["ships"][:40] for i in (x.get("items") or [])]
    goods = list(dict.fromkeys([g for g in goods if g]))[:20]
    return ("Закуп товаров из Китая. Имена: %s. Магазины: %s. Товары: %s. "
            "Слова: аванс, карыз, калганы, доллар, юань, сом, жүз, миң, партия, доставка, Гуанчжоу, Иу, Урумчи, Шэньчжэнь."
            % (", ".join(names), ", ".join(st), ", ".join(goods) or "чемодан, посуда, фен, пылесос"))

def ai(payload, timeout=120, tries=4):
    """Запрос к ИИ с терпением: на 429/5xx ждём столько, сколько просит сервер, и повторяем."""
    last = None
    for i in range(tries):
        try:
            d = _req(AI_BASE + "/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                     headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"}, timeout=timeout)
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 520, 522): raise
            wait = 2 + i * 3
            try: wait = min(30, max(wait, float(e.headers.get("retry-after") or 0)))
            except Exception: pass
            log("ИИ занят (%d), жду %.0f с" % (e.code, wait)); time.sleep(wait)
    raise RuntimeError("ИИ не отвечает (%s)" % getattr(last, "code", "?"))

# ---------------------------------------------------------------- разбор смысла
SYSTEM = """Ты — учётчик закупок товаров из Китая. Владелец диктует голосом на кыргызском, русском,
их смеси или по-китайски. Твоя работа: превратить сказанное в операции учёта и вернуть ЧИСТЫЙ JSON.

Тебе дают одну или две расшифровки одного и того же голоса (Whisper не знает кыргызского и коверкает слова).
Восстанавливай смысл: сравнивай версии, опирайся на справочник имён и на кыргызские числительные.

Кыргызские числа: бир 1, эки 2, үч 3, төрт 4, беш 5, алты 6, жети 7, сегиз 8, тогуз 9, он 10,
жыйырма 20, отуз 30, кырк 40, элүү 50, алтымыш 60, жетимиш 70, сексен 80, токсон 90, жүз 100, миң 1000, миллион.
Whisper коверкает так: «жүз»→«герц/юз/гуз/жуз», «миң»→«мин/минг/мың/минк», «беш»→«биш/бещ», «үч»→«уч/уй»,
«элүү»→«элу/елу», «эки»→«эке/яки». «беш жүз» = 500, «эки миң» = 2000, «он беш миң» = 15000.

Слова: алдым/сатып алдым — купил; бердим/төлөдүм — заплатил; берди — дал мне; аванс/алдын ала — предоплата;
карыз/калганы — долг/остаток; келет — придёт; жөнөттү/чыкты — отправлено; келди/жетти — пришло;
дүкөн/магазин/бутик — магазин; базар — рынок; бүгүн сегодня, кечээ вчера, эртең завтра,
«он күндөн кийин» — через 10 дней.

ОПЕРАЦИИ (поле op):
1) "shipment" — новая закупка. Поля: supplier (имя), date, currency (USD/CNY/KGS/KZT/RUB/UZS),
   city, items[{store, product, qty, unit, unit_price, amount}], prepay {amount, currency},
   eta_days или eta_date, track, note, status (new/shipping/arrived).
2) "payment" — деньги поставщику. Поля: supplier, amount, currency, kind (prepay аванс | final доплата | refund возврат мне),
   shipment ("last" = последняя партия этого поставщика, или число-id, или null), date, method, note.
3) "investment" — инвестор вложил деньги. Поля: investor, amount, currency, terms ("share" доля прибыли % | "fixed" % в месяц),
   terms_value (число процентов), shipment (id или null = общий пул), date, end_date, note.
4) "payout" — выплата инвестору. Поля: investor, amount, currency, kind (profit доля | principal возврат вложения), date, note.
5) "status" — движение партии. Поля: shipment ("last" или id), status (shipping отправлено | arrived пришло | new | cancelled), date.
6) "close" — закрыть партию с прибылью. Поля: shipment, profit, currency.
7) "items" — дописать товары в существующую партию. Поля: shipment ("last" или id), items[...].
8) "store" — новый магазин. Поля: number, name.
9) "partner" — новый поставщик/инвестор. Поля: name, is_supplier, is_investor, city, currency, contact.
10) "update" — исправить уже записанное. Поля: kind (shipment|payment|investment|payout), id, fields {…}.
11) "delete" — удалить запись. Поля: kind, id.
12) "query" — владелец не диктует, а спрашивает (сколько должен, какие партии, итоги). Поле: question.

ПРАВИЛА:
— Имена бери из справочника, если звучит похоже (Ли Вэй ≈ «левей», «ли уэй»). Нет похожего — оставь как услышал, программа заведёт нового.
— Обращения ага, аке, байке, эже, апа, агай, аба, мырза — вежливость, а НЕ часть имени: «Ли Вэй ага» → поставщик «Ли Вэй».
— product — это вещь (чемодан, посуда, фен, пылесос, куртка), НИКОГДА не имя человека, не город и не магазин.
  Не расслышал товар — пиши "товар", но не подставляй туда имя поставщика.
— Whisper часто склеивает слова в одно («икиньчимагазингичимаданалдым» = «экинчи магазинге чемодан алдым»).
  Разбирай такие склейки по кусочкам, опираясь на список товаров и магазинов.
— Магазин называй номером или названием из справочника («экинчи магазин» = магазин 2).
— Сумма без валюты = валюта поставщика из справочника, иначе USD.
— «Дал авансом» вместе с покупкой — это поле prepay внутри shipment, отдельную операцию payment не создавай.
— Если сказана и общая сумма, и цена за штуку — заполни оба, amount = сумма строки.
— Дата не названа — сегодня. Считай даты сам от сегодняшней.
— Партия не названа («партия вышла», «товар келди», «дагы төлөдүм») — ставь shipment:"last", это последняя партия
  названного поставщика, а если поставщик не назван — просто последняя. Не переспрашивай про номер партии.
— Не выдумывай числа. Если суммы или имени нет — не создавай запись, а задай короткий вопрос в поле ask.
— Одно сообщение может содержать несколько операций — верни их списком по порядку.

ОТВЕТ строго такой JSON:
{"understood":"пересказ одной строкой по-русски","confidence":0.0-1.0,"ask":"","actions":[{"op":"…"}]}
Если это болтовня или непонятно — actions пустой и ask с вопросом."""

def understand(texts, ctx, history):
    msg = [{"role": "system", "content": SYSTEM},
           {"role": "system", "content": "Сегодня %s. Справочник: %s" % (d_ru(today()), brief(ctx))}]
    for h in history[-6:]:
        msg.append(h)
    if not texts: texts = [""]
    body = "Расшифровки голоса:\n" + "\n".join("вариант %d: %s" % (i + 1, t) for i, t in enumerate(texts)) \
        if len(texts) > 1 else "Сказано: " + texts[0]
    msg.append({"role": "user", "content": body})
    raw = ai({"model": AI_MODEL, "messages": msg, "temperature": 0.1,
              "response_format": {"type": "json_object"}})
    try: return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else {"actions": [], "ask": "Не понял, повторите пожалуйста"}

def answer(question, ctx):
    """Свободный вопрос по учёту — отвечаем словами, ничего не записывая."""
    sm = api("GET", "/api/summary")
    data = {"итоги": sm, "справочник": json.loads(brief(ctx))}
    return ai({"model": os.environ.get("KN_AI_MODEL_LIGHT") or "openai/gpt-oss-20b", "temperature": 0.2, "messages": [
        {"role": "system", "content": "Ты помощник по учёту закупок из Китая. Отвечай по-русски, коротко, "
                                      "числами из данных. Суммы пиши с валютой. Не выдумывай."},
        {"role": "user", "content": "Данные: %s\n\nВопрос: %s" % (json.dumps(data, ensure_ascii=False)[:12000], question)}],
    }, timeout=90).strip()

# ---------------------------------------------------------------- сопоставление со справочником
def find_partner(ctx, name, investor=False, create=True):
    if not name: return None
    n = norm(name)
    best, score = None, 0.0
    for p in ctx["partners"]:
        s = difflib.SequenceMatcher(None, n, norm(p["name"])).ratio()
        if n and (n in norm(p["name"]) or norm(p["name"]) in n): s = max(s, 0.9)
        if s > score: best, score = p, s
    if best and score >= 0.62:
        if investor and not best.get("is_investor"):
            api("PATCH", "/api/partners/%d" % best["id"], {**best, "is_investor": 1})
            best["is_investor"] = 1
        return best
    if not create: return None
    r = api("POST", "/api/partners", {"name": name.strip(), "is_supplier": 0 if investor else 1,
                                      "is_investor": 1 if investor else 0, "currency": "USD"})
    p = {"id": r["id"], "name": name.strip(), "currency": "USD", "is_investor": 1 if investor else 0,
         "is_supplier": 0 if investor else 1, "active": 1, "city": ""}
    ctx["partners"].append(p); p["_new"] = True
    return p

def find_store(ctx, val, create=True):
    if val in (None, "", 0):
        act = [s for s in ctx["stores"] if s.get("active", 1)]
        return act[0] if len(act) == 1 else None
    v = str(val).strip(); n = norm(v)
    digits = re.sub(r"\D", "", v)
    for s in ctx["stores"]:
        if digits and str(s.get("number") or "").strip() == digits: return s
    best, score = None, 0.0
    for s in ctx["stores"]:
        for field in (s.get("name") or "", s.get("number") or ""):
            r = difflib.SequenceMatcher(None, n, norm(field)).ratio()
            if r > score: best, score = s, r
    if best and score >= 0.66: return best
    if not create: return None
    r = api("POST", "/api/stores", {"number": digits or v[:12], "name": "" if digits else v})
    s = {"id": r["id"], "number": digits or v[:12], "name": "" if digits else v, "active": 1}
    ctx["stores"].append(s); s["_new"] = True
    return s

def find_ship(ctx, ref, supplier_id=None):
    ships = [s for s in ctx["ships"] if not supplier_id or s["supplier_id"] == supplier_id]
    if ref in (None, "", "last", "последняя", 0):
        opened = [s for s in ships if not s.get("closed_at")]
        pool = opened or ships
        return max(pool, key=lambda s: (s["date"], s["id"])) if pool else None
    try: sid = int(re.sub(r"\D", "", str(ref)))
    except Exception: return None
    for s in ctx["ships"]:
        if s["id"] == sid: return s
    return None

def cur_of(x, default="USD"):
    c = (x or "").upper()
    if c in CUR_SIGN: return c
    low = (x or "").lower()
    for code, words in CUR_WORDS.items():
        if any(w in low for w in words): return code
    return default

def num(v):
    if v in (None, ""): return None
    if isinstance(v, (int, float)): return float(v)
    s = re.sub(r"[^\d.,-]", "", str(v)).replace(",", ".")
    try: return float(s)
    except Exception: return None

# ---------------------------------------------------------------- выполнение операций
def do_shipment(a, ctx):
    sup = find_partner(ctx, a.get("supplier"))
    if not sup: return None, "не понял поставщика"
    cur = cur_of(a.get("currency"), sup.get("currency") or "USD")
    items, total = [], 0.0
    for it in (a.get("items") or []):
        st = find_store(ctx, it.get("store"))
        if not st: return None, "не понял магазин"
        qty, price, amount = num(it.get("qty")), num(it.get("unit_price")), num(it.get("amount"))
        if amount is None and qty and price: amount = round(qty * price, 2)
        if amount is None: amount = 0.0
        if price is None and qty and amount: price = round(amount / qty, 2)
        items.append({"store_id": st["id"], "product": (it.get("product") or "товар").strip(),
                      "qty": qty, "unit": it.get("unit") or "шт", "unit_price": price,
                      "amount": amount, "note": it.get("note") or ""})
        total += amount
    if not items: return None, "не понял, какой товар"
    body = {"date": a.get("date") or today(), "supplier_id": sup["id"], "currency": cur,
            "status": a.get("status") or "new", "track": a.get("track") or "",
            "note": a.get("note") or "", "items": items}
    pre = a.get("prepay") or {}
    pa = num(pre.get("amount") if isinstance(pre, dict) else pre)
    if pa:
        pc = cur_of((pre or {}).get("currency") if isinstance(pre, dict) else None, cur)
        pa, expl = convert(pa, pc, cur)
        body["prepaid"] = pa
        if expl: body["note"] = (body["note"] + " · аванс " + expl).strip(" ·")
    days = num(a.get("eta_days"))
    if a.get("eta_date"): body["eta_date"] = a["eta_date"]
    elif days: body["eta_date"] = (date.today() + timedelta(days=int(days))).isoformat()
    city = (a.get("city") or "").strip()
    if city and not (sup.get("city") or "").strip():
        api("PATCH", "/api/partners/%d" % sup["id"], {**sup, "city": city}); sup["city"] = city
    r = api("POST", "/api/shipments", body)
    ctx["ships"].insert(0, r)
    lines = ["<b>Партия №%d</b> · %s · %s" % (r["id"], sup["name"], d_ru(r["date"]))]
    for i in r.get("items", []):
        q = ("%g %s × %s = " % (i["qty"], i["unit"], money(i["unit_price"], cur))) if (i.get("qty") and i.get("unit_price")) \
            else (("%g %s · " % (i["qty"], i["unit"])) if i.get("qty") else "")
        lines.append("• маг. %s — %s: %s%s" % (i.get("store_number") or "?", i["product"], q, money(i["amount"], cur)))
    lines.append("Сумма: <b>%s</b>" % money(r.get("amount"), cur))
    if r.get("prepaid"): lines.append("Аванс: %s · долг: <b>%s</b>" % (money(r["prepaid"], cur), money(r.get("balance"), cur)))
    if r.get("eta_date"): lines.append("Ждём: %s" % d_ru(r["eta_date"]))
    if sup.get("_new"): lines.append("<i>поставщик заведён впервые</i>")
    return {"kind": "shipment", "id": r["id"]}, "\n".join(lines)

def do_items(a, ctx):
    sh = find_ship(ctx, a.get("shipment"))
    if not sh: return None, "не нашёл партию"
    full = api("GET", "/api/shipments/%d" % sh["id"])
    cur = full.get("currency") or "USD"
    items = [{"id": i["id"], "store_id": i["store_id"], "product": i["product"], "qty": i["qty"],
              "unit": i["unit"], "unit_price": i["unit_price"], "amount": i["amount"], "note": i.get("note") or ""}
             for i in full.get("items", [])]
    added = []
    for it in (a.get("items") or []):
        st = find_store(ctx, it.get("store")) or {"id": full.get("default_store_id") or items[0]["store_id"], "number": "?"}
        qty, price, amount = num(it.get("qty")), num(it.get("unit_price")), num(it.get("amount"))
        if amount is None and qty and price: amount = round(qty * price, 2)
        items.append({"store_id": st["id"], "product": (it.get("product") or "товар").strip(), "qty": qty,
                      "unit": it.get("unit") or "шт", "unit_price": price, "amount": amount or 0, "note": ""})
        added.append("• маг. %s — %s: %s" % (st.get("number") or "?", it.get("product") or "товар", money(amount or 0, cur)))
    if not added: return None, "не понял товары"
    r = api("PATCH", "/api/shipments/%d" % sh["id"], {"items": items})
    return {"kind": "items", "id": sh["id"], "count": len(added)}, \
           "<b>Дописал в партию №%d</b>\n%s\nСумма партии: <b>%s</b>" % (sh["id"], "\n".join(added), money(r.get("amount"), cur))

def do_payment(a, ctx):
    sup = find_partner(ctx, a.get("supplier"))
    if not sup: return None, "не понял, кому платим"
    amount = num(a.get("amount"))
    if not amount: return None, "не понял сумму"
    sh = find_ship(ctx, a.get("shipment"), sup["id"]) if a.get("shipment") not in (None, "", "null") else None
    cur = cur_of(a.get("currency"), (sh or {}).get("currency") or sup.get("currency") or "USD")
    note = a.get("note") or ""
    if sh and cur != (sh.get("currency") or cur):
        amount, expl = convert(amount, cur, sh["currency"])
        if expl: note = (note + " · " + expl).strip(" ·")
        cur = sh["currency"]
    body = {"date": a.get("date") or today(), "supplier_id": sup["id"], "amount": amount, "currency": cur,
            "kind": a.get("kind") or "prepay", "method": a.get("method") or "", "note": note,
            "shipment_id": sh["id"] if sh else None}
    r = api("POST", "/api/payments", body)
    kind_ru = {"prepay": "Аванс", "final": "Доплата", "refund": "Возврат от поставщика"}
    out = ["<b>%s</b> · %s · %s" % (kind_ru.get(body["kind"], "Платёж"), sup["name"], money(amount, cur))]
    if sh:
        fresh = api("GET", "/api/shipments/%d" % sh["id"])
        out.append("Партия №%d: оплачено %s из %s" % (sh["id"], money(fresh.get("paid"), cur), money(fresh.get("amount"), cur)))
        out.append("Долг по партии: <b>%s</b>" % money(fresh.get("balance"), cur))
        if r.get("converted"): out.append("<i>прежний аванс %s перенесён в платежи</i>" % money(r["converted"], cur))
    else:
        fin = api("GET", "/api/partners/%d" % sup["id"])
        out.append("Общий долг поставщику: <b>%s</b>" % money(fin.get("balance"), cur))
    return {"kind": "payment", "id": r["id"]}, "\n".join(out)

def do_investment(a, ctx):
    inv = find_partner(ctx, a.get("investor"), investor=True)
    if not inv: return None, "не понял инвестора"
    amount = num(a.get("amount"))
    if not amount: return None, "не понял сумму вложения"
    cur = cur_of(a.get("currency"), "USD")
    sh = find_ship(ctx, a.get("shipment")) if a.get("shipment") not in (None, "", "null", "pool") else None
    body = {"date": a.get("date") or today(), "investor_id": inv["id"], "amount": amount, "currency": cur,
            "terms": a.get("terms") or "share", "terms_value": num(a.get("terms_value")),
            "shipment_id": sh["id"] if sh else None, "note": a.get("note") or "", "end_date": a.get("end_date")}
    r = api("POST", "/api/investments", body)
    t = ("доля %g%% от прибыли" % body["terms_value"]) if body["terms"] == "share" and body["terms_value"] \
        else ("%g%% в месяц" % (body["terms_value"] or 0))
    out = ["<b>Вложение</b> · %s · %s" % (inv["name"], money(amount, cur)), "Условие: %s" % t,
           "Партия: %s" % ("№%d" % sh["id"] if sh else "общий пул")]
    return {"kind": "investment", "id": r.get("id") or r.get("row", {}).get("id")}, "\n".join(out)

def do_payout(a, ctx):
    inv = find_partner(ctx, a.get("investor"), investor=True)
    amount = num(a.get("amount"))
    if not (inv and amount): return None, "не понял выплату"
    cur = cur_of(a.get("currency"), "USD")
    r = api("POST", "/api/payouts", {"date": a.get("date") or today(), "investor_id": inv["id"], "amount": amount,
                                     "currency": cur, "kind": a.get("kind") or "profit", "note": a.get("note") or ""})
    k = "доля прибыли" if (a.get("kind") or "profit") == "profit" else "возврат вложения"
    return {"kind": "payout", "id": r.get("id")}, "<b>Выплата инвестору</b> · %s · %s (%s)" % (inv["name"], money(amount, cur), k)

def do_status(a, ctx):
    sup = find_partner(ctx, a.get("supplier"), create=False) if a.get("supplier") else None
    sh = find_ship(ctx, a.get("shipment"), sup["id"] if sup else None)
    if not sh: return None, "не нашёл партию"
    st = a.get("status") or "shipping"
    body = {"status": st}
    if st == "shipping" and a.get("date"): body["sent_date"] = a["date"]
    if st == "arrived": body["arrived_date"] = a.get("date") or today()
    r = api("PATCH", "/api/shipments/%d" % sh["id"], body)
    ru = {"new": "новая", "shipping": "в пути", "arrived": "пришла", "cancelled": "отменена"}
    return {"kind": "status", "id": sh["id"], "prev": sh.get("status")}, \
           "<b>Партия №%d</b> (%s) — теперь <b>%s</b>" % (sh["id"], r.get("supplier_name") or "", ru.get(st, st))

def do_close(a, ctx):
    sh = find_ship(ctx, a.get("shipment"))
    profit = num(a.get("profit"))
    if not sh: return None, "не нашёл партию"
    if profit is None: return None, "не понял прибыль"
    r = api("PATCH", "/api/shipments/%d" % sh["id"], {"profit": profit, "closed_at": a.get("date") or today()})
    cur = r.get("currency") or "USD"
    out = ["<b>Партия №%d закрыта</b> · прибыль %s" % (sh["id"], money(profit, cur))]
    for s in (r.get("shares") or []):
        out.append("• %s: %s" % (s.get("name"), money(s.get("amount"), cur)))
    return {"kind": "close", "id": sh["id"]}, "\n".join(out)

def do_store(a, ctx):
    st = find_store(ctx, a.get("number") or a.get("name"))
    return {"kind": "store", "id": st["id"]}, "<b>Магазин</b> %s %s" % (st.get("number") or "", st.get("name") or "")

def do_partner(a, ctx):
    p = find_partner(ctx, a.get("name"), investor=bool(a.get("is_investor")))
    if a.get("city") or a.get("contact") or a.get("currency"):
        api("PATCH", "/api/partners/%d" % p["id"], {**p, "city": a.get("city") or p.get("city") or "",
                                                    "contact": a.get("contact") or p.get("contact") or "",
                                                    "currency": cur_of(a.get("currency"), p.get("currency") or "USD")})
    return {"kind": "partner", "id": p["id"]}, "<b>Контрагент</b> %s записан" % p["name"]

def do_update(a, ctx):
    kind, oid, f = a.get("kind"), a.get("id"), (a.get("fields") or {})
    path = {"shipment": "/api/shipments/%s", "payment": "/api/payments/%s",
            "investment": "/api/investments/%s", "payout": "/api/payouts/%s"}.get(kind)
    if not (path and oid and f): return None, "не понял, что исправить"
    if kind == "payment":
        cur_row = [p for p in api("GET", "/api/payments").get("rows", []) if p["id"] == int(oid)]
        if cur_row: f = {**{k: cur_row[0][k] for k in ("date", "supplier_id", "shipment_id", "amount", "currency", "kind", "method", "note")}, **f}
    api("PATCH", path % oid, f)
    return {"kind": "update", "id": oid}, "<b>Исправил</b> %s №%s" % (kind, oid)

def do_delete(a, ctx):
    kind, oid = a.get("kind"), a.get("id")
    path = {"shipment": "/api/shipments/%s", "payment": "/api/payments/%s",
            "investment": "/api/investments/%s", "payout": "/api/payouts/%s"}.get(kind)
    if not (path and oid): return None, "не понял, что удалить"
    api("DELETE", path % oid)
    return {"kind": "deleted", "id": oid}, "<b>Удалил</b> %s №%s" % (kind, oid)

OPS = {"shipment": do_shipment, "items": do_items, "payment": do_payment, "investment": do_investment,
       "payout": do_payout, "status": do_status, "close": do_close, "store": do_store,
       "partner": do_partner, "update": do_update, "delete": do_delete}

def run_plan(plan, ctx):
    """Выполняет операции по порядку. Возвращает (текст отчёта, список записей для отмены)."""
    parts, ops, problems = [], [], []
    for a in (plan.get("actions") or []):
        op = (a.get("op") or "").strip()
        if op == "query":
            try: parts.append(answer(a.get("question") or plan.get("understood") or "", ctx))
            except Exception as e: problems.append("не смог ответить: %s" % e)
            continue
        fn = OPS.get(op)
        if not fn: problems.append("неизвестная операция «%s»" % op); continue
        try:
            ref, text = fn(a, ctx)
            if ref: ops.append(ref)
            parts.append(text if ref else "⚠️ " + text)
        except Exception as e:
            log("операция", op, "не удалась:", e)
            problems.append("%s: %s" % (op, e))
    if problems: parts.append("⚠️ " + "; ".join(problems))
    return "\n\n".join(p for p in parts if p), ops

def undo(ops):
    """Откат записей одной кнопкой — в обратном порядке."""
    done = []
    for o in reversed(ops):
        k, i = o.get("kind"), o.get("id")
        try:
            if k == "shipment": api("DELETE", "/api/shipments/%s" % i); done.append("партия №%s" % i)
            elif k == "payment": api("DELETE", "/api/payments/%s" % i); done.append("платёж")
            elif k == "investment": api("DELETE", "/api/investments/%s" % i); done.append("вложение")
            elif k == "payout": api("DELETE", "/api/payouts/%s" % i); done.append("выплата")
            elif k == "status": api("PATCH", "/api/shipments/%s" % i, {"status": o.get("prev") or "new"}); done.append("статус партии №%s" % i)
            elif k == "close": api("PATCH", "/api/shipments/%s" % i, {"profit": None}); done.append("закрытие партии №%s" % i)
            elif k in ("store", "partner"): api("DELETE", "/api/%s/%s" % ("stores" if k == "store" else "partners", i)); done.append(k)
        except Exception as e:
            log("отмена не удалась:", k, i, e)
    return done

# ---------------------------------------------------------------- разговор
HIST = {}        # chat_id → последние реплики, чтобы понимать «нет, 5000, а не 500»
LAST = {}        # chat_id → последние записанные операции (для кнопки «Отменить»)
SEEN = set()     # update_id, чтобы не выполнить одно и то же дважды
Q = queue.Queue()

HELP = ("<b>Китай · учёт — голосовой ввод</b>\n\n"
        "Просто наговорите голосовое, как рассказали бы человеку:\n"
        "«Ли Вэй ага, Гуанчжоудан экинчи магазинге чемодан алдым, беш жүз доллар, "
        "аванс бердим эки жүз, калганы он күндөн кийин».\n\n"
        "Бот сам заведёт партию, товар, аванс и посчитает долг.\n\n"
        "Можно и текстом. Можно спрашивать: «сколько я должен Ли Вэю?», «итоги за месяц».\n\n"
        "Команды: /итоги · /долги · /партии · /помощь")

def cmd(chat, text, thread):
    t = text.lower().lstrip("/")
    if t.startswith(("start", "помощь", "help")): say(chat, HELP, thread=thread); return True
    if t.startswith("id"): say(chat, "Ваш id: <code>%s</code>" % chat, thread=thread); return True
    if t.startswith(("итог", "сводка")):
        s = api("GET", "/api/summary")
        say(chat, "<b>Итоги</b>\nПартий: %s · на сумму %s\nОплачено: %s · долг: %s\nПрибыль закрытых: %s" % (
            s.get("count"), money(s.get("amount")), money(s.get("paid")), money(s.get("debt")), money(s.get("profit"))), thread=thread)
        return True
    if t.startswith(("долг", "карыз")):
        ps = [p for p in api("GET", "/api/partners") if (p.get("balance") or 0) > 0]
        ps.sort(key=lambda p: -(p.get("balance") or 0))
        say(chat, "<b>Долги поставщикам</b>\n" + ("\n".join("• %s — %s" % (p["name"], money(p["balance"], p.get("currency") or "USD"))
                                                            for p in ps) or "нет долгов"), thread=thread)
        return True
    if t.startswith(("парти", "список")):
        rows = api("GET", "/api/shipments").get("rows", [])[:10]
        st = {"new": "новая", "shipping": "в пути", "arrived": "пришла", "cancelled": "отменена"}
        say(chat, "<b>Последние партии</b>\n" + "\n".join(
            "• №%d %s · %s · %s · %s" % (r["id"], d_ru(r["date"]), r.get("supplier_name") or "",
                                         money(r.get("amount"), r.get("currency")), st.get(r.get("status"), ""))
            for r in rows), thread=thread)
        return True
    return False

def handle(u):
    msg = u.get("message") or u.get("edited_message")
    cb = u.get("callback_query")
    if cb: return handle_button(cb)
    if not msg: return
    chat = msg["chat"]["id"]
    frm = str((msg.get("from") or {}).get("id") or "")
    thread = msg.get("message_thread_id")
    if ALLOW and frm not in ALLOW and str(chat) not in ALLOW:
        say(chat, "Это личный бот учёта. Доступ только у владельца.\nВаш id: <code>%s</code>" % frm, thread=thread)
        log("чужой:", frm, (msg.get("from") or {}).get("username")); return
    mid = msg["message_id"]
    voice = msg.get("voice") or msg.get("audio") or msg.get("video_note")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if text.startswith("/") and cmd(chat, text, thread): return
    if not (voice or text): return
    # В группе бот молчит, пока к нему не обратились: голосом, ответом на его сообщение,
    # упоминанием или командой. Иначе он лез бы в любую переписку.
    if msg["chat"].get("type") in ("group", "supergroup"):
        me = "@" + (CFG.get("me") or "")
        mine = ((msg.get("reply_to_message") or {}).get("from") or {}).get("is_bot")
        if THREAD and str(thread or "") != THREAD: return
        if not (voice or mine or (me != "@" and me.lower() in text.lower()) or text.startswith("/")): return
        text = re.sub(r"@\w+", "", text).strip()

    react(chat, mid, "👀")
    typing(chat)
    try:
        ctx = context()
        texts = []
        if voice:
            f = tg("getFile", file_id=voice["file_id"]).get("result") or {}
            if not f.get("file_path"): react(chat, mid, "😐"); say(chat, "Не смог забрать голосовое, пришлите ещё раз", thread=thread); return
            audio = _req(FILE_API + f["file_path"], raw=True, timeout=120)
            ext = (os.path.splitext(f["file_path"])[1] or "").lower()
            name = "voice.ogg" if ext in ("", ".oga", ".ogg") else "voice" + ext   # .oga Groq не принимает
            best, texts = listen(audio, name, hints(ctx))
            if not texts:
                react(chat, mid, "😐"); say(chat, "Не разобрал речь. Попробуйте ещё раз или напишите текстом.", thread=thread); return
            if text: texts = [t + " " + text for t in texts]
        else:
            texts = [text]

        plan = understand(texts, ctx, HIST.get(chat, []))
        heard = texts[0]
        report, ops = run_plan(plan, ctx)
        ask = (plan.get("ask") or "").strip()

        head = ("🎙 <i>%s</i>\n\n" % heard[:300]) if voice else ""
        if ops:
            LAST[chat] = ops
            kb = [[{"text": "↩️ Отменить", "callback_data": "undo"}]]
            if (CFG.get("web_url") or "").startswith("https://"):   # Telegram принимает только внешние адреса
                kb[0].append({"text": "📋 Открыть", "url": CFG["web_url"]})
            say(chat, head + (report or "Записал"), kb=kb, reply_to=mid, thread=thread)
            react(chat, mid, "👍")
        elif ask:
            say(chat, head + "🤔 " + ask, reply_to=mid, thread=thread)
            react(chat, mid, "🤔")
        else:
            say(chat, head + (report or "Не понял, что записать. Скажите иначе или напишите текстом."), reply_to=mid, thread=thread)
            react(chat, mid, "🤔" if not report else "👍")

        h = HIST.setdefault(chat, [])
        h.append({"role": "user", "content": heard})
        h.append({"role": "assistant", "content": json.dumps({"understood": plan.get("understood"),
                                                              "actions": plan.get("actions"), "записано": ops}, ensure_ascii=False)[:1200]})
        del h[:-8]
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
        tg("editMessageReplyMarkup", chat_id=chat, message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        say(chat, "↩️ Отменил: " + (", ".join(done) if done else "нечего"))

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
    """Локальный режим: опрашиваем Telegram сами (в облаке вместо этого вебхук)."""
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
    """Вызывается из server.py при старте. Возвращает True, если бот включён."""
    CFG.update(cfg)
    if not enabled():
        if TOKEN and not AI_KEY: log("нет ключа ИИ (KN_AI_KEY) — голосовой ввод выключен")
        return False
    for _ in range(2):
        threading.Thread(target=worker, daemon=True).start()
    me = (tg("getMe").get("result") or {}).get("username")
    CFG["me"] = me
    if HOOK_URL:
        r = tg("setWebhook", url=HOOK_URL, secret_token=SECRET, allowed_updates=["message", "edited_message", "callback_query"],
               drop_pending_updates=True)
        log("вебхук @%s → %s: %s" % (me, HOOK_URL, "готов" if r.get("ok") else r))
    elif POLL:
        threading.Thread(target=poll, daemon=True).start()
        log("опрос Telegram запущен, бот @%s" % me)
    else:
        log("бот @%s подключён (ни вебхука, ни опроса — включите KN_TG_POLL=1 или KN_TG_HOOK_URL)" % me)
    return True
