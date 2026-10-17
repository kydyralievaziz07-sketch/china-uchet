#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Учёт закупок у бутиков — простая программа: Сезон → Одежда → Бутики → Закупка и финансы.

Уровни:
  1. Сезон (Зима, Лето…; в базе — таблица companies) — сколько бутиков, стоимость закупок, оплачено, остаток.
  2. Одежда — мужская, женская, детская (поле category у бутика).
  3. Бутик — город, номер/название, комментарий.
  4. Закупка бутика — товары (название, количество, цена, сумма, комментарий) и финансовый блок:
     стоимость закупки (по товарам или вручную), депозит (залог / предоплата), оплаты Санжара,
     получение товара (не получен / частично / полностью).

Финансовая логика бутика:
  стоимость     = сумма товаров, либо введённая вручную (режим выбирается явно, двойного учёта нет);
  депозит       = залог / предоплата: вычитается из стоимости сразу, отдельным платежом его вносить не нужно;
  оплачено      = депозит + платежи Санжара (его собственные деньги);
  остаток       = стоимость − депозит − платежи Санжара (не ниже нуля);
  переплата     = если оплачено больше стоимости — показывается отдельно.

Стандартная библиотека Python + SQLite локально; в облаке — pg8000 и Postgres (DATABASE_URL).
Старые таблицы прежней версии (партии, поставщики, инвесторы, пользователи) в базе не трогаются.

Входа нет: программа открывается по обычной ссылке, без логина, пароля и ключей.
"""
import base64, hashlib, json, os, re, shutil, sqlite3, secrets, struct, threading, time, zlib
from collections import defaultdict
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

VERSION = "7.4.0"
ROOT = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(ROOT, "china.db")
WEB  = os.path.join(ROOT, "web")
PORT = int(os.environ.get("PORT", "8902"))
HOST = "0.0.0.0" if (os.environ.get("RENDER") or os.environ.get("KN_HOST") == "0.0.0.0") else "127.0.0.1"
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
PG_SCHEMA = re.sub(r"[^a-z0-9_]", "", (os.environ.get("KN_PG_SCHEMA") or "china").lower()) or "china"
try:
    import tgbot            # голосовое управление через Telegram (необязательно)
except Exception as _e:
    tgbot = None; print("Голосовой бот не подключён:", _e)

def web_url():
    """Адрес программы для кнопки «Открыть» в Telegram."""
    u = (os.environ.get("KN_WEB_URL") or "").strip()
    if not u:
        ka = (os.environ.get("KN_KEEPALIVE_URL") or "").strip()
        u = ka.replace("/api/ping", "")
    u = u.rstrip("/")
    return u or None

# ---------------------------------------------------------------- база: схема
# Таблицы прежней версии (partners, stores, shipments, shipment_items, payments, investments, investor_payouts)
# остаются в базе как есть — данные не теряются, их можно скачать файлом .db. Новая программа ими не пользуется.
LEGACY_SQLITE = """
CREATE TABLE IF NOT EXISTS partners(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, is_supplier INTEGER NOT NULL DEFAULT 1,
  is_investor INTEGER NOT NULL DEFAULT 0, contact TEXT, city TEXT, currency TEXT NOT NULL DEFAULT 'USD', note TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL, name TEXT, note TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS shipments(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, supplier_id INTEGER NOT NULL REFERENCES partners(id),
  currency TEXT NOT NULL DEFAULT 'USD', rate REAL, prepaid REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new',
  sent_date TEXT, arrived_date TEXT, eta_date TEXT, track TEXT, default_store_id INTEGER REFERENCES stores(id),
  profit REAL, closed_at TEXT, note TEXT, deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS shipment_items(id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  store_id INTEGER NOT NULL REFERENCES stores(id), product TEXT NOT NULL, qty REAL, unit TEXT DEFAULT 'шт', unit_price REAL,
  amount REAL NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, supplier_id INTEGER NOT NULL REFERENCES partners(id),
  shipment_id INTEGER REFERENCES shipments(id), amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  kind TEXT NOT NULL DEFAULT 'prepay', method TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS investments(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, investor_id INTEGER NOT NULL REFERENCES partners(id),
  shipment_id INTEGER REFERENCES shipments(id), amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  terms TEXT NOT NULL DEFAULT 'share', terms_value REAL, note TEXT, end_date TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS investor_payouts(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, investor_id INTEGER NOT NULL REFERENCES partners(id),
  amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', kind TEXT NOT NULL DEFAULT 'profit', note TEXT, created_at TEXT);
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS companies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,                            -- дата создания компании (вводит пользователь)
  name TEXT, note TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS boutiques(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,   -- сезон (Зима, Лето…)
  category TEXT NOT NULL DEFAULT 'men',          -- men | women | kids: мужская / женская / детская одежда
  city TEXT NOT NULL,
  name TEXT NOT NULL,                            -- номер или название бутика
  note TEXT,
  total_mode TEXT NOT NULL DEFAULT 'items',      -- items: по товарам | manual: введено вручную
  manual_total REAL,
  deposit REAL NOT NULL DEFAULT 0,               -- внесённый депозит
  deposit_date TEXT, deposit_note TEXT,
  receipt_status TEXT NOT NULL DEFAULT 'none',   -- none | partial | full
  receipt_date TEXT, receipt_note TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS boutique_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  boutique_id INTEGER NOT NULL REFERENCES boutiques(id) ON DELETE CASCADE,
  product TEXT NOT NULL,
  qty REAL, unit_price REAL, amount REAL,
  received_qty REAL,
  note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS boutique_payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  boutique_id INTEGER NOT NULL REFERENCES boutiques(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  amount REAL NOT NULL,
  source TEXT NOT NULL DEFAULT 'own',            -- own: деньги Санжара | deposit: из депозита
  note TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bq_company ON boutiques(company_id);
CREATE INDEX IF NOT EXISTS idx_bi_boutique ON boutique_items(boutique_id);
CREATE INDEX IF NOT EXISTS idx_bp_boutique ON boutique_payments(boutique_id);
-- справочник: поставщики, их накладные и товары с ценой прихода (к бутикам не привязаны)
CREATE TABLE IF NOT EXISTS suppliers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, name_cn TEXT, contact TEXT, goods TEXT, place TEXT, phones TEXT, note TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS supplier_invoices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  number TEXT, date TEXT, paper_total REAL, deposit REAL NOT NULL DEFAULT 0, note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS catalog_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  invoice_id INTEGER REFERENCES supplier_invoices(id) ON DELETE SET NULL,
  article TEXT, name TEXT NOT NULL, what TEXT, qty REAL, price REAL, note TEXT,
  unsure INTEGER NOT NULL DEFAULT 0,             -- 1: прочитано с накладной неуверенно, проверить
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_si_supplier ON supplier_invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ci_supplier ON catalog_items(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ci_article ON catalog_items(article);
""" + LEGACY_SQLITE
# Та же схема для Postgres: SERIAL вместо AUTOINCREMENT, DOUBLE PRECISION вместо REAL, даты остаются текстом.
PG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS companies(id SERIAL PRIMARY KEY, date TEXT NOT NULL, name TEXT, note TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS boutiques(id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  category TEXT NOT NULL DEFAULT 'men', city TEXT NOT NULL, name TEXT NOT NULL, note TEXT, total_mode TEXT NOT NULL DEFAULT 'items', manual_total DOUBLE PRECISION,
  deposit DOUBLE PRECISION NOT NULL DEFAULT 0, deposit_date TEXT, deposit_note TEXT,
  receipt_status TEXT NOT NULL DEFAULT 'none', receipt_date TEXT, receipt_note TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS boutique_items(id SERIAL PRIMARY KEY, boutique_id INTEGER NOT NULL REFERENCES boutiques(id) ON DELETE CASCADE,
  product TEXT NOT NULL, qty DOUBLE PRECISION, unit_price DOUBLE PRECISION, amount DOUBLE PRECISION, received_qty DOUBLE PRECISION,
  note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS boutique_payments(id SERIAL PRIMARY KEY, boutique_id INTEGER NOT NULL REFERENCES boutiques(id) ON DELETE CASCADE,
  date TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL, source TEXT NOT NULL DEFAULT 'own', note TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_bq_company ON boutiques(company_id);
CREATE INDEX IF NOT EXISTS idx_bi_boutique ON boutique_items(boutique_id);
CREATE INDEX IF NOT EXISTS idx_bp_boutique ON boutique_payments(boutique_id);
ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'men';
CREATE TABLE IF NOT EXISTS suppliers(id SERIAL PRIMARY KEY, name TEXT NOT NULL, name_cn TEXT, contact TEXT, goods TEXT, place TEXT,
  phones TEXT, note TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS supplier_invoices(id SERIAL PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  number TEXT, date TEXT, paper_total DOUBLE PRECISION, deposit DOUBLE PRECISION NOT NULL DEFAULT 0, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS catalog_items(id SERIAL PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  invoice_id INTEGER REFERENCES supplier_invoices(id) ON DELETE SET NULL, article TEXT, name TEXT NOT NULL, what TEXT,
  qty DOUBLE PRECISION, price DOUBLE PRECISION, note TEXT, unsure INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_si_supplier ON supplier_invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ci_supplier ON catalog_items(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ci_article ON catalog_items(article)
"""
LEGACY_TABLES = ["partners", "stores", "shipments", "shipment_items", "payments", "investments", "investor_payouts"]
TABLES = ["settings", "companies", "boutiques", "boutique_items", "boutique_payments",
          "suppliers", "supplier_invoices", "catalog_items"] + LEGACY_TABLES

# ---------------------------------------------------------------- база: подключение (SQLite локально / Postgres в облаке)
if IS_PG:
    import ssl, queue
    import pg8000.dbapi
    _u = urlparse(DATABASE_URL)
    PG_KW = dict(user=unquote(_u.username or ""), password=unquote(_u.password or ""), host=_u.hostname,
                 port=_u.port or 5432, database=((_u.path or "/postgres").lstrip("/") or "postgres"))
    _pool = queue.LifoQueue()
    _POOL_IDLE = 240   # сек: дольше не держим соединение — пул Supabase его всё равно закроет

    class PgCur:
        """Курсор, отдающий строки словарями — как sqlite3.Row."""
        def __init__(self, cur): self.c = cur; self.lastrowid = None; self._cols = None
        def _row(self, r):
            if r is None: return None
            if self._cols is None: self._cols = [d[0] for d in self.c.description]
            return dict(zip(self._cols, r))
        def fetchone(self): return self._row(self.c.fetchone())
        def fetchall(self): return [self._row(r) for r in self.c.fetchall()]
        def __iter__(self): return iter(self.fetchall())

    class PgConn:
        """Обёртка с интерфейсом sqlite3.Connection: `?` → `%s`, lastrowid через RETURNING id."""
        def __init__(self, raw): self.raw = raw; self.broken = False; self.closed = False
        def execute(self, sql, params=()):
            sql = sql.replace("?", "%s")
            m = re.match(r"\s*INSERT\s+INTO\s+(\w+)\s*\(", sql, re.I)
            want_id = bool(m) and m.group(1).lower() != "settings" and "RETURNING" not in sql.upper()
            if want_id: sql = sql.rstrip().rstrip(";") + " RETURNING id"
            cur = self.raw.cursor()
            try: cur.execute(sql, tuple(params) if params is not None else ())
            except Exception:
                self.broken = True; raise
            pc = PgCur(cur)
            if want_id:
                r = cur.fetchone(); pc.lastrowid = r[0] if r else None
            return pc
        def executescript(self, script):
            for st in script.split(";"):
                if st.strip(): self.raw.cursor().execute(st)
        def commit(self): self.raw.commit()
        def rollback(self): self.raw.rollback()
        def create_function(self, *a, **k): pass
        def close(self):
            if self.closed: return
            self.closed = True
            if self.broken:
                try: self.raw.close()
                except Exception: pass
                return
            try: self.raw.rollback()
            except Exception: return
            _pool.put((self.raw, time.time()))

    def _pg_connect():
        ctx = ssl.create_default_context()
        try:
            raw = pg8000.dbapi.connect(**PG_KW, ssl_context=ctx, timeout=20)
        except ssl.SSLError:
            ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
            raw = pg8000.dbapi.connect(**PG_KW, ssl_context=ctx, timeout=20)
        cur = raw.cursor(); cur.execute("SET search_path TO %s, public" % PG_SCHEMA); raw.commit()
        return raw

    def db():
        while True:
            try: raw, ts = _pool.get_nowait()
            except queue.Empty: return PgConn(_pg_connect())
            if time.time() - ts < _POOL_IDLE: return PgConn(raw)
            try: raw.close()
            except Exception: pass
else:
    def db():
        c = sqlite3.connect(DB)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def today(): return date.today().isoformat()

def migrate_sqlite(c):
    """Добавляем колонки, которых нет в старых базах SQLite (без потери данных)."""
    def cols(t):
        try: return [r["name"] for r in c.execute("PRAGMA table_info(%s)" % t)]
        except Exception: return []
    for t, col in (("payments", "created_at"), ("investments", "end_date"), ("investments", "created_at"),
                   ("investor_payouts", "created_at")):
        if cols(t) and col not in cols(t): c.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (t, col))
    # v7.4: у бутика появился вид одежды; всё, что заведено раньше, — мужская одежда
    if cols("boutiques") and "category" not in cols("boutiques"):
        c.execute("ALTER TABLE boutiques ADD COLUMN category TEXT NOT NULL DEFAULT 'men'")

def init_db():
    c = db()
    if IS_PG:
        c.execute("CREATE SCHEMA IF NOT EXISTS %s" % PG_SCHEMA)
        c.executescript(PG_SCHEMA_SQL)
    else:
        c.executescript(SCHEMA); migrate_sqlite(c)
    commit(c)
    c.close()

def backup_db(keep=30):
    if IS_PG: return None   # в облаке копии хранит Supabase; ручная копия — «Скачать .db»
    bdir = os.path.join(ROOT, "backups"); os.makedirs(bdir, exist_ok=True)
    if os.path.exists(DB):
        dst = os.path.join(bdir, "china-%s.db" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(DB, dst)
        old = sorted(f for f in os.listdir(bdir) if f.startswith("china-"))
        for f in old[:-keep]: os.remove(os.path.join(bdir, f))
        return dst
    return None

def export_sqlite_bytes():
    """Вся база одним файлом SQLite — и локально (сам файл), и из облака (собираем из Postgres)."""
    if not IS_PG:
        backup_db(); return open(DB, "rb").read()
    tmp = os.path.join(ROOT, "export-%s.db" % secrets.token_hex(4))
    dst = sqlite3.connect(tmp); dst.row_factory = sqlite3.Row; dst.executescript(SCHEMA); migrate_sqlite(dst)
    c = db()
    for t in TABLES:
        try: rows = c.execute("SELECT * FROM %s ORDER BY %s" % (t, "key" if t == "settings" else "id")).fetchall()
        except Exception: c.rollback(); continue      # старой таблицы в облаке может не быть
        if not rows: continue
        cols = list(rows[0].keys())
        dst.executemany("INSERT INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))),
                        [tuple(r[k] for k in cols) for r in rows])
    dst.commit(); dst.close(); c.close()
    data = open(tmp, "rb").read(); os.remove(tmp)
    return data

def import_sqlite_file(path):
    """Загрузить базу из файла .db (перенос с компьютера в облако и обратно)."""
    src = sqlite3.connect(path); src.row_factory = sqlite3.Row
    try: names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError: src.close(); raise ValueError("Файл повреждён или это не база SQLite")
    if not ({"companies", "shipments"} & names): src.close(); raise ValueError("Это не база этой программы")
    tables = list(TABLES)
    counts = {}
    if IS_PG:
        c = db()
        try:
            existing = {r["table_name"] for r in c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=?", (PG_SCHEMA,))}
            tables = [t for t in tables if t in existing]
            for t in reversed(tables): c.execute("DELETE FROM %s" % t)
            for t in tables:
                cols_src = [r[1] for r in src.execute("PRAGMA table_info(%s)" % t)]
                if not cols_src: continue
                cols_dst = [r["column_name"] for r in c.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?", (PG_SCHEMA, t))]
                cols = [x for x in cols_src if x in cols_dst]
                if not cols: continue
                rows = src.execute("SELECT %s FROM %s" % (",".join(cols), t)).fetchall()
                for r in rows:
                    c.execute("INSERT INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), tuple(r))
                counts[t] = len(rows)
                if "id" in cols:
                    c.execute("SELECT setval(pg_get_serial_sequence(?, 'id'), COALESCE((SELECT MAX(id) FROM %s), 0) + 1, false)" % t,
                              ("%s.%s" % (PG_SCHEMA, t),))
            commit(c)
        except Exception:
            c.rollback(); c.close(); src.close(); raise
        c.close()
    else:
        for t in tables:
            try: counts[t] = src.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            except Exception: counts[t] = 0
        src.close()
        backup_db()
        shutil.copy2(path, DB)
        c = db(); c.executescript(SCHEMA); migrate_sqlite(c)
        commit(c); c.close()
        return counts
    src.close()
    return counts

def make_icon(path, size=180):
    """Иконка для домашнего экрана телефона: градиент + три квадрата (компания → бутики). Чистый Python."""
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            r, g, b = int(0x2F + (0x1B - 0x2F) * t), int(0x6F + (0x4F - 0x6F) * t), int(0xE3 + (0xA6 - 0xE3) * t)
            fx, fy = (x + .5) / size, (y + .5) / size
            if 0.30 <= fx <= 0.70 and 0.30 <= fy <= 0.70 and (abs(fx - 0.5) > 0.03 and abs(fy - 0.5) > 0.03):
                r, g, b = 0xFF, 0xFF, 0xFF
            row += bytes((r, g, b))
        rows.append(bytes(row))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)

def keepalive():
    """Бесплатный Render засыпает через 15 минут тишины — раз в 10 минут дёргаем себя сами."""
    url = (os.environ.get("KN_KEEPALIVE_URL") or "").strip()
    if not url: return
    import urllib.request
    def loop():
        while True:
            time.sleep(600)
            try: urllib.request.urlopen(url, timeout=25).read()
            except Exception: pass
    threading.Thread(target=loop, daemon=True).start()

# ---------------------------------------------------------------- настройки
CURRENCIES = ("USD", "KGS", "KZT", "RUB", "CNY", "EUR")

def r2(x): return round(float(x or 0), 2)

def get_settings(c):
    s = {"currency": "USD"}
    for r in c.execute("SELECT key, value FROM settings"):
        if r["key"] == "currency" and r["value"] in CURRENCIES: s["currency"] = r["value"]
    return s

def set_setting(c, key, value):
    if IS_PG:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, value))
    else:
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))

# ---------------------------------------------------------------- снимок базы (4 запроса вместо сотен — важно для облака)
SNAP = {"snap": None, "t": 0.0, "dirty": True}
SNAP_TTL = 20   # секунд; любая запись помечает снимок устаревшим

class Snap:
    """Все четыре таблицы одним махом + индексы. Дальше расчёты идут в памяти без запросов."""
    def __init__(self, c):
        self.companies = {r["id"]: dict(r) for r in c.execute("SELECT * FROM companies ORDER BY date DESC, id DESC")}
        self.bouts = {r["id"]: dict(r) for r in c.execute("SELECT * FROM boutiques ORDER BY id")}
        self.bouts_by_company = defaultdict(list)
        for b in self.bouts.values(): self.bouts_by_company[b["company_id"]].append(b)
        self.items = defaultdict(list)
        for r in c.execute("SELECT * FROM boutique_items ORDER BY id"): self.items[r["boutique_id"]].append(dict(r))
        self.pays = defaultdict(list)
        for r in c.execute("SELECT * FROM boutique_payments ORDER BY date, id"): self.pays[r["boutique_id"]].append(dict(r))

def get_snap(c):
    if SNAP["dirty"] or SNAP["snap"] is None or time.time() - SNAP["t"] > SNAP_TTL:
        SNAP["snap"] = Snap(c); SNAP["t"] = time.time(); SNAP["dirty"] = False
    return SNAP["snap"]

def commit(c):
    c.commit(); SNAP["dirty"] = True

# ---------------------------------------------------------------- финансовая логика
SUP_FIELDS = ("name", "name_cn", "contact", "goods", "place", "phones", "note")   # поля поставщика справочника
RECEIPT = ("none", "partial", "full")
CATEGORIES = {"men": "Мужская одежда", "women": "Женская одежда", "kids": "Детская одежда"}   # порядок = порядок на экране
TOTAL_MODES = ("items", "manual")

def finance(b, items, pays):
    """Все цифры бутика. Депозит — предоплата: вычитается из стоимости целиком и один раз.
    Платежи с пометкой «deposit» остались от версии 7.0 (когда депозит списывался платежом) — депозит уже
    вычтен, поэтому в расчёт они не входят, иначе одна сумма считалась бы дважды."""
    items_total = r2(sum(i["amount"] or 0 for i in items))
    manual = b["total_mode"] == "manual" and b["manual_total"] is not None
    total = r2(b["manual_total"]) if manual else items_total
    deposit = r2(b["deposit"])
    paid_own = r2(sum(p["amount"] for p in pays if p["source"] != "deposit"))
    paid = r2(deposit + paid_own)
    diff = r2(total - paid)
    qty_items = [i for i in items if i["qty"] not in (None, 0)]
    return {"items_total": items_total, "total": total, "total_mode": "manual" if manual else "items",
            "deposit": deposit, "paid_own": paid_own, "paid": paid,
            "remaining": max(0.0, diff), "overpaid": max(0.0, r2(-diff)),
            "items_count": len(items), "payments_count": len(pays),
            "qty_total": r2(sum(i["qty"] for i in qty_items)) if qty_items else None,
            "received_total": r2(sum(i["received_qty"] or 0 for i in qty_items)) if qty_items else None}

def pack_boutique(sn, b, full=False):
    items, pays = sn.items.get(b["id"], []), sn.pays.get(b["id"], [])
    d = {**b, **finance(b, items, pays)}
    co = sn.companies.get(b["company_id"]) or {}
    d["company_name"] = co.get("name") or ""; d["company_date"] = co.get("date")
    d["category"] = d.get("category") or "men"; d["category_name"] = CATEGORIES.get(d["category"], "")
    if full:
        d["items"] = [dict(i) for i in items]
        d["payments"] = sorted((dict(p) for p in pays), key=lambda p: (p["date"], p["id"]), reverse=True)
    return d

def pack_company(sn, co, with_boutiques=False):
    bouts = [pack_boutique(sn, b) for b in sn.bouts_by_company.get(co["id"], [])]
    d = dict(co)
    d.update(boutiques_count=len(bouts),
             total=r2(sum(b["total"] for b in bouts)), paid=r2(sum(b["paid"] for b in bouts)),
             paid_own=r2(sum(b["paid_own"] for b in bouts)), deposit=r2(sum(b["deposit"] for b in bouts)),
             remaining=r2(sum(b["remaining"] for b in bouts)), overpaid=r2(sum(b["overpaid"] for b in bouts)),
             items_count=sum(b["items_count"] for b in bouts))
    if with_boutiques:
        d["boutiques"] = sorted(bouts, key=lambda b: ((b["city"] or "").lower(), (b["name"] or "").lower(), b["id"]))
        d["categories"] = []
        for k, title in CATEGORIES.items():
            mine = [b for b in bouts if b["category"] == k]
            d["categories"].append({"key": k, "name": title, "boutiques_count": len(mine),
                                    "total": r2(sum(b["total"] for b in mine)), "paid": r2(sum(b["paid"] for b in mine)),
                                    "paid_own": r2(sum(b["paid_own"] for b in mine)), "deposit": r2(sum(b["deposit"] for b in mine)),
                                    "remaining": r2(sum(b["remaining"] for b in mine)), "overpaid": r2(sum(b["overpaid"] for b in mine))})
    return d

def num(v, name, allow_none=True):
    """Число из формы: пусто → None (если можно), иначе ValueError с понятным текстом."""
    if v in (None, ""):
        if allow_none: return None
        raise ValueError("Не указано: " + name)
    try: return round(float(str(v).replace(",", ".").replace(" ", "")), 2)
    except Exception: raise ValueError("%s: нужно число" % name)

def valid_date(v, name, required=True):
    if not v:
        if required: raise ValueError("Не указана " + name)
        return None
    try: return date.fromisoformat(str(v)[:10]).isoformat()
    except Exception: raise ValueError("%s: неверная дата" % name)

# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "Boutiques/" + VERSION
    def log_message(self, fmt, *a): pass

    # -- helpers
    def _send(self, code, data, ctype="application/json; charset=utf-8", headers=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg): self._send(code, {"error": msg})

    def _db(self):
        """Соединение на время запроса; route() закрывает его в конце, даже после ошибки."""
        self.c = db(); return self.c

    def _body(self, limit=40_000_000):
        n = int(self.headers.get("Content-Length") or 0)
        if not n: return {}
        if n > limit: return {}
        try: return json.loads(self.rfile.read(n).decode())
        except Exception: return {}

    def tg_hook(self):
        """Сюда Telegram присылает сообщения. Отвечаем сразу, разбираем голос в фоне."""
        if not (tgbot and tgbot.enabled()): return self._err(404, "Бот выключен")
        if tgbot.SECRET and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != tgbot.SECRET:
            return self._err(403, "Чужой запрос")
        try: tgbot.enqueue(self._body())
        except Exception as e: print("вебхук Telegram:", e)
        return self._send(200, {"ok": True})

    # -- маршрутизация
    def route(self, method):
        # http.server декодирует строку запроса как latin-1 — возвращаем UTF-8
        try: raw = self.path.encode("latin-1").decode("utf-8")
        except Exception: raw = self.path
        p = urlparse(raw)
        path, q = p.path.rstrip("/") or "/", parse_qs(p.query)
        self.c = None
        try:
            if path == "/" and method == "GET": return self.page()
            if path.startswith("/static/") and method == "GET": return self.static(path)
            if path == "/api/ping" and method == "GET":
                return self._send(200, {"ok": True, "version": VERSION, "cloud": IS_PG, "db": "postgres" if IS_PG else "sqlite"})
            if path == "/api/tg/hook" and method == "POST": return self.tg_hook()
            if path == "/api/settings":
                if method == "GET": return self.settings_get()
                if method == "PATCH": return self.settings_save(self._body())
            if path == "/api/summary" and method == "GET": return self.summary()

            m_id = re.match(r"^/api/(companies|boutiques|items|payments|suppliers|catalog-items)/(\d+)$", path)
            kind, oid = (m_id.group(1), int(m_id.group(2))) if m_id else (None, None)
            try:
                if path == "/api/companies":
                    if method == "GET": return self.companies_list()
                    if method == "POST": return self.company_save(self._body())
                if kind == "companies":
                    if method == "GET": return self.company_one(oid)
                    if method == "PATCH": return self.company_save(self._body(), oid)
                    if method == "DELETE": return self.company_delete(oid)
                if path == "/api/boutiques":
                    if method == "GET": return self.boutiques_list(q)
                    if method == "POST": return self.boutique_save(self._body())
                if kind == "boutiques":
                    if method == "GET": return self.boutique_one(oid)
                    if method == "PATCH": return self.boutique_save(self._body(), oid)
                    if method == "DELETE": return self.boutique_delete(oid)
                if path == "/api/items" and method == "POST": return self.item_save(self._body())
                if kind == "items":
                    if method == "GET": return self.item_one(oid)
                    if method == "PATCH": return self.item_save(self._body(), oid)
                    if method == "DELETE": return self.item_delete(oid)
                if path == "/api/payments" and method == "POST": return self.payment_save(self._body())
                if kind == "payments":
                    if method == "GET": return self.payment_one(oid)
                    if method == "PATCH": return self.payment_save(self._body(), oid)
                    if method == "DELETE": return self.payment_delete(oid)
                # справочник поставщиков и товаров
                if path == "/api/catalog" and method == "GET": return self.catalog(q)
                if path == "/api/catalog/import" and method == "POST": return self.catalog_import(self._body())
                if path == "/api/suppliers" and method == "POST": return self.supplier_save(self._body())
                if kind == "suppliers":
                    if method == "GET": return self.supplier_one(oid)
                    if method == "PATCH": return self.supplier_save(self._body(), oid)
                    if method == "DELETE": return self.supplier_delete(oid)
                if path == "/api/catalog-items" and method == "POST": return self.citem_save(self._body())
                if kind == "catalog-items":
                    if method == "GET": return self.citem_one(oid)
                    if method == "PATCH": return self.citem_save(self._body(), oid)
                    if method == "DELETE": return self.citem_delete(oid)
            except ValueError as e:
                return self._err(400, str(e))
            if path == "/api/backup" and method == "POST":
                dst = backup_db()
                return self._send(200, {"ok": True, "file": os.path.basename(dst) if dst else "в облаке копии хранит Supabase — скачайте .db"})
            if path == "/api/backup.db" and method == "GET":
                return self._send(200, export_sqlite_bytes(), "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename=butiki-uchet-%s.db" % today()})
            if path == "/api/restore" and method == "POST": return self.restore(self._body())
            return self._err(404, "Нет такого адреса")
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._err(500, "Ошибка сервера: %s" % e)
        finally:
            if self.c is not None:
                try: self.c.close()
                except Exception: pass
                self.c = None

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PATCH(self): self.route("PATCH")
    def do_DELETE(self): self.route("DELETE")

    # -- страница и статика
    def page(self):
        try: html = open(os.path.join(WEB, "index.html"), "rb").read().decode("utf-8")
        except Exception: return self._err(500, "Нет web/index.html")
        self._send(200, html.replace("{{v}}", VERSION).encode("utf-8"), "text/html; charset=utf-8")

    def static(self, path):
        name = os.path.basename(path)
        types = {"css": "text/css; charset=utf-8", "js": "application/javascript; charset=utf-8",
                 "svg": "image/svg+xml", "png": "image/png", "json": "application/json; charset=utf-8",
                 "webmanifest": "application/manifest+json"}
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if name == "manifest.webmanifest":
            data = json.dumps({"name": "Бутики · учёт", "short_name": "Бутики", "display": "standalone",
                               "background_color": "#F5F6F8", "theme_color": "#2F6FE3",
                               "icons": [{"src": "/static/icon.png", "sizes": "180x180", "type": "image/png"}]}, ensure_ascii=False)
            return self._send(200, data.encode(), types["webmanifest"])
        fp = os.path.join(WEB, name)
        if ext not in types or not os.path.isfile(fp): return self._err(404, "Нет файла")
        self._send(200, open(fp, "rb").read(), types[ext])

    # -- настройки
    def settings_get(self):
        c = self._db(); s = get_settings(c); c.close(); self._send(200, s)

    def settings_save(self, b):
        c = self._db()
        if "currency" in b and b["currency"] in CURRENCIES: set_setting(c, "currency", b["currency"])
        commit(c); s = get_settings(c); c.close(); self._send(200, s)

    def restore(self, b):
        try: raw = base64.b64decode(b.get("db_b64") or "")
        except Exception: raw = b""
        if raw[:16] != b"SQLite format 3\x00": return self._err(400, "Нужен файл базы .db из этой программы")
        tmp = os.path.join(ROOT, "restore-%s.db" % secrets.token_hex(4))
        open(tmp, "wb").write(raw)
        try: counts = import_sqlite_file(tmp)
        except ValueError as e: os.remove(tmp); return self._err(400, str(e))
        except Exception as e: os.remove(tmp); return self._err(500, "Не удалось загрузить базу: %s" % e)
        os.remove(tmp); SNAP["dirty"] = True
        self._send(200, {"ok": True, "counts": counts})

    # -- сводка (для бота и для карточек)
    def summary(self):
        c = self._db(); sn = get_snap(c)
        rows = [pack_company(sn, co) for co in sn.companies.values()]
        c.close()
        keys = ("total", "paid", "paid_own", "deposit", "remaining", "overpaid", "items_count")
        out = {k: r2(sum(r[k] for r in rows)) for k in keys}
        out.update(companies=len(rows), boutiques=sum(r["boutiques_count"] for r in rows), items_count=int(out["items_count"]))
        self._send(200, out)

    # -- компании
    def companies_list(self):
        c = self._db(); sn = get_snap(c)
        rows = [pack_company(sn, co) for co in sn.companies.values()]
        c.close(); self._send(200, {"rows": rows})

    def company_one(self, cid):
        c = self._db(); sn = get_snap(c); co = sn.companies.get(cid)
        if not co: c.close(); return self._err(404, "Сезон не найден")
        out = pack_company(sn, co, with_boutiques=True); c.close(); self._send(200, out)

    def company_save(self, b, cid=None):
        c = self._db()
        if cid and not c.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone():
            c.close(); return self._err(404, "Сезон не найден")
        if ("name" in b or not cid) and not (b.get("name") or "").strip():
            c.close(); return self._err(400, "Укажите время года, например «Зима 2026»")
        if cid:
            sets, args = [], []
            if "date" in b: sets.append("date=?"); args.append(valid_date(b.get("date"), "дата создания"))
            if "name" in b: sets.append("name=?"); args.append((b.get("name") or "").strip())
            if "note" in b: sets.append("note=?"); args.append((b.get("note") or "").strip())
            sets.append("updated_at=?"); args += [now(), cid]
            c.execute("UPDATE companies SET %s WHERE id=?" % ",".join(sets), args)
        else:
            cid = c.execute("INSERT INTO companies(date,name,note,created_at,updated_at) VALUES(?,?,?,?,?)",
                            (valid_date(b.get("date") or today(), "дата создания"), (b.get("name") or "").strip(),
                             (b.get("note") or "").strip(), now(), now())).lastrowid
        commit(c); sn = get_snap(c)
        out = pack_company(sn, sn.companies[cid], with_boutiques=True); c.close()
        self._send(200, {"ok": True, "id": cid, **out})

    def company_delete(self, cid):
        c = self._db()
        if not c.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone(): c.close(); return self._err(404, "Сезон не найден")
        bids = [r["id"] for r in c.execute("SELECT id FROM boutiques WHERE company_id=?", (cid,))]
        for bid in bids:
            c.execute("DELETE FROM boutique_payments WHERE boutique_id=?", (bid,))
            c.execute("DELETE FROM boutique_items WHERE boutique_id=?", (bid,))
        c.execute("DELETE FROM boutiques WHERE company_id=?", (cid,))
        c.execute("DELETE FROM companies WHERE id=?", (cid,))
        commit(c); c.close(); self._send(200, {"ok": True})

    # -- бутики
    def boutiques_list(self, q):
        c = self._db(); sn = get_snap(c); cid = (q.get("company") or [""])[0]; cat = (q.get("category") or [""])[0]
        rows = [pack_boutique(sn, b) for b in sn.bouts.values() if (not cid or str(b["company_id"]) == str(cid))
                and (not cat or (b.get("category") or "men") == cat)]
        c.close(); self._send(200, {"rows": rows})

    def boutique_one(self, bid):
        c = self._db(); sn = get_snap(c); b = sn.bouts.get(bid)
        if not b: c.close(); return self._err(404, "Бутик не найден")
        out = pack_boutique(sn, b, full=True); c.close(); self._send(200, out)

    def boutique_save(self, b, bid=None):
        c = self._db()
        old = c.execute("SELECT * FROM boutiques WHERE id=?", (bid,)).fetchone() if bid else None
        if bid and not old: c.close(); return self._err(404, "Бутик не найден")
        old = dict(old) if old else {}
        cur = {**old, **b}
        vals = {}
        if not bid or "company_id" in b:
            try: cid = int(b.get("company_id") or 0)
            except Exception: cid = 0
            if not c.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone(): c.close(); return self._err(400, "Сезон не найден")
            vals["company_id"] = cid
        if not bid or "category" in b:
            cat = b.get("category") or "men"
            if cat not in CATEGORIES: c.close(); return self._err(400, "Неверный вид одежды: нужен men, women или kids")
            vals["category"] = cat
        if not bid or "city" in b: vals["city"] = (b.get("city") or "").strip()
        if not bid or "name" in b: vals["name"] = (b.get("name") or "").strip()
        if not bid or "note" in b: vals["note"] = (b.get("note") or "").strip()
        if not (vals.get("city") if "city" in vals else old.get("city")): c.close(); return self._err(400, "Укажите город")
        if not (vals.get("name") if "name" in vals else old.get("name")): c.close(); return self._err(400, "Укажите номер или название бутика")
        # стоимость закупки: по товарам или вручную — один явный режим, без двойного учёта
        if "total_mode" in b or "manual_total" in b:
            mode = cur.get("total_mode") or "items"
            if mode not in TOTAL_MODES: c.close(); return self._err(400, "Неверный способ расчёта стоимости")
            mt = num(b.get("manual_total", old.get("manual_total")), "общая стоимость закупки")
            if mode == "manual" and mt is None: c.close(); return self._err(400, "Укажите общую стоимость закупки")
            if mt is not None and mt < 0: c.close(); return self._err(400, "Стоимость не может быть отрицательной")
            vals["total_mode"] = mode; vals["manual_total"] = mt
        # депозит
        if "deposit" in b or "deposit_date" in b or "deposit_note" in b:
            dep = num(b.get("deposit", old.get("deposit")), "депозит") or 0.0
            if dep < 0: c.close(); return self._err(400, "Депозит не может быть отрицательным")
            vals["deposit"] = dep
            vals["deposit_date"] = valid_date(b.get("deposit_date", old.get("deposit_date")), "дата депозита", required=False)
            vals["deposit_note"] = (b.get("deposit_note", old.get("deposit_note")) or "").strip()
        # получение товара
        if "receipt_status" in b or "receipt_date" in b or "receipt_note" in b or "received" in b:
            st = cur.get("receipt_status") or "none"
            if st not in RECEIPT: c.close(); return self._err(400, "Неверный статус получения")
            vals["receipt_status"] = st
            vals["receipt_date"] = valid_date(b.get("receipt_date", old.get("receipt_date")), "дата получения", required=False) if st != "none" else None
            vals["receipt_note"] = (b.get("receipt_note", old.get("receipt_note")) or "").strip()
            if bid:
                items = {r["id"]: dict(r) for r in c.execute("SELECT * FROM boutique_items WHERE boutique_id=?", (bid,))}
                upd = {}
                for r in (b.get("received") or []):
                    try: iid = int(r.get("id"))
                    except Exception: continue
                    if iid in items: upd[iid] = num(r.get("received_qty"), "получено")
                if st == "full":            # получен полностью — всё количество получено
                    for iid, i in items.items():
                        if iid not in upd: upd[iid] = i["qty"]
                elif st == "none":          # не получен — ничего не получено
                    for iid in items: upd[iid] = None
                for iid, v in upd.items():
                    if v is not None and v < 0: c.close(); return self._err(400, "Полученное количество не может быть отрицательным")
                    c.execute("UPDATE boutique_items SET received_qty=? WHERE id=?", (v, iid))
        if bid:
            sets = ["%s=?" % k for k in vals] + ["updated_at=?"]
            c.execute("UPDATE boutiques SET %s WHERE id=?" % ",".join(sets), list(vals.values()) + [now(), bid])
        else:
            vals.setdefault("total_mode", "items"); vals.setdefault("manual_total", None)
            vals.setdefault("deposit", 0.0); vals.setdefault("deposit_date", None); vals.setdefault("deposit_note", "")
            vals.setdefault("receipt_status", "none"); vals.setdefault("receipt_date", None); vals.setdefault("receipt_note", "")
            vals["created_at"] = now(); vals["updated_at"] = now()
            bid = c.execute("INSERT INTO boutiques(%s) VALUES(%s)" % (",".join(vals), ",".join("?" * len(vals))), list(vals.values())).lastrowid
        commit(c); sn = get_snap(c)
        out = pack_boutique(sn, sn.bouts[bid], full=True); c.close()
        self._send(200, {"ok": True, "id": bid, **out})

    def boutique_delete(self, bid):
        c = self._db()
        if not c.execute("SELECT 1 FROM boutiques WHERE id=?", (bid,)).fetchone(): c.close(); return self._err(404, "Бутик не найден")
        c.execute("DELETE FROM boutique_payments WHERE boutique_id=?", (bid,))
        c.execute("DELETE FROM boutique_items WHERE boutique_id=?", (bid,))
        c.execute("DELETE FROM boutiques WHERE id=?", (bid,))
        commit(c); c.close(); self._send(200, {"ok": True})

    # -- товары
    def _bout_of(self, c, bid):
        try: bid = int(bid or 0)
        except Exception: bid = 0
        r = c.execute("SELECT * FROM boutiques WHERE id=?", (bid,)).fetchone()
        if not r: raise ValueError("Бутик не найден")
        return dict(r)

    def _reply_boutique(self, c, bid, extra):
        commit(c); sn = get_snap(c)
        out = pack_boutique(sn, sn.bouts[bid], full=True); c.close()
        self._send(200, {"ok": True, **extra, "boutique": out})

    def item_one(self, iid):
        c = self._db(); r = c.execute("SELECT * FROM boutique_items WHERE id=?", (iid,)).fetchone(); c.close()
        if not r: return self._err(404, "Товар не найден")
        self._send(200, dict(r))

    def item_save(self, b, iid=None):
        c = self._db()
        old = c.execute("SELECT * FROM boutique_items WHERE id=?", (iid,)).fetchone() if iid else None
        if iid and not old: c.close(); return self._err(404, "Товар не найден")
        old = dict(old) if old else {}
        cur = {**old, **b}
        bout = self._bout_of(c, cur.get("boutique_id"))
        product = (cur.get("product") or "").strip()
        if not product: c.close(); return self._err(400, "Укажите название товара")
        qty, price = num(cur.get("qty"), "количество"), num(cur.get("unit_price"), "цена")
        if qty is not None and qty < 0: c.close(); return self._err(400, "Количество не может быть отрицательным")
        if price is not None and price < 0: c.close(); return self._err(400, "Цена не может быть отрицательной")
        amount = num(cur.get("amount"), "стоимость позиции")
        if qty is not None and price is not None and (amount is None or "amount" not in b or b.get("amount") in (None, "")):
            amount = r2(qty * price)       # количество × цена — считается само
        if amount is not None and amount < 0: c.close(); return self._err(400, "Стоимость не может быть отрицательной")
        received = num(cur.get("received_qty"), "получено")
        if received is not None and qty is None: received = None
        vals = (bout["id"], product, qty, price, amount, received, (cur.get("note") or "").strip())
        if iid:
            c.execute("UPDATE boutique_items SET boutique_id=?,product=?,qty=?,unit_price=?,amount=?,received_qty=?,note=? WHERE id=?", vals + (iid,))
        else:
            iid = c.execute("INSERT INTO boutique_items(boutique_id,product,qty,unit_price,amount,received_qty,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                            vals + (now(),)).lastrowid
        c.execute("UPDATE boutiques SET updated_at=? WHERE id=?", (now(), bout["id"]))
        self._reply_boutique(c, bout["id"], {"id": iid})

    def item_delete(self, iid):
        c = self._db(); r = c.execute("SELECT boutique_id FROM boutique_items WHERE id=?", (iid,)).fetchone()
        if not r: c.close(); return self._err(404, "Товар не найден")
        c.execute("DELETE FROM boutique_items WHERE id=?", (iid,))
        self._reply_boutique(c, r["boutique_id"], {})

    # -- платежи Санжара (свои деньги или из депозита)
    def payment_one(self, pid):
        c = self._db(); r = c.execute("SELECT * FROM boutique_payments WHERE id=?", (pid,)).fetchone(); c.close()
        if not r: return self._err(404, "Платёж не найден")
        self._send(200, dict(r))

    def payment_save(self, b, pid=None):
        c = self._db()
        old = c.execute("SELECT * FROM boutique_payments WHERE id=?", (pid,)).fetchone() if pid else None
        if pid and not old: c.close(); return self._err(404, "Платёж не найден")
        old = dict(old) if old else {}
        cur = {**old, **b}
        bout = self._bout_of(c, cur.get("boutique_id"))
        d = valid_date(cur.get("date"), "дата платежа")
        amount = num(cur.get("amount"), "сумма платежа", allow_none=False)
        if amount <= 0: c.close(); return self._err(400, "Сумма платежа должна быть больше нуля")
        # платёж — всегда деньги Санжара. Депозит вычитается из стоимости сам, платежом «из депозита» его не списывают
        if b.get("source") == "deposit":
            c.close(); return self._err(400, "Депозит вычитается из стоимости сам — платёж «из депозита» не нужен. Запишите депозит в блоке «Депозит», а здесь — только деньги Санжара.")
        source = "own" if (not pid or "source" in b) else (old.get("source") or "own")
        vals = (bout["id"], d, amount, source, (cur.get("note") or "").strip())
        if pid:
            c.execute("UPDATE boutique_payments SET boutique_id=?,date=?,amount=?,source=?,note=? WHERE id=?", vals + (pid,))
        else:
            pid = c.execute("INSERT INTO boutique_payments(boutique_id,date,amount,source,note,created_at) VALUES(?,?,?,?,?,?)",
                            vals + (now(),)).lastrowid
        c.execute("UPDATE boutiques SET updated_at=? WHERE id=?", (now(), bout["id"]))
        self._reply_boutique(c, bout["id"], {"id": pid})

    def payment_delete(self, pid):
        c = self._db(); r = c.execute("SELECT boutique_id FROM boutique_payments WHERE id=?", (pid,)).fetchone()
        if not r: c.close(); return self._err(404, "Платёж не найден")
        c.execute("DELETE FROM boutique_payments WHERE id=?", (pid,))
        self._reply_boutique(c, r["boutique_id"], {})

    # -- справочник: поставщики, накладные, товары с ценой прихода (юани)
    def _catalog_data(self, c, supplier_id=None):
        w, a = ("WHERE supplier_id=?", (supplier_id,)) if supplier_id else ("", ())
        sups = {r["id"]: dict(r) for r in c.execute("SELECT * FROM suppliers %s ORDER BY id" % ("WHERE id=?" if supplier_id else ""), a)}
        invs = {r["id"]: dict(r) for r in c.execute("SELECT * FROM supplier_invoices %s ORDER BY date, id" % w, a)}
        items = [dict(r) for r in c.execute("SELECT * FROM catalog_items %s ORDER BY supplier_id, invoice_id, id" % w, a)]
        for i in items:
            i["amount"] = r2((i["qty"] or 0) * (i["price"] or 0)) if i["qty"] is not None and i["price"] is not None else None
            s, v = sups.get(i["supplier_id"]) or {}, invs.get(i["invoice_id"]) or {}
            i["supplier_name"] = s.get("name") or ""; i["supplier_cn"] = s.get("name_cn") or ""
            i["invoice_number"] = v.get("number"); i["invoice_date"] = v.get("date")
        for v in invs.values():
            v["lines_total"] = r2(sum(i["amount"] or 0 for i in items if i["invoice_id"] == v["id"]))
            v["items_count"] = len([i for i in items if i["invoice_id"] == v["id"]])
        for s in sups.values():
            mine = [i for i in items if i["supplier_id"] == s["id"]]
            s["items_count"] = len(mine); s["unsure_count"] = len([i for i in mine if i["unsure"]])
            s["total"] = r2(sum(i["amount"] or 0 for i in mine))
            s["deposit"] = r2(sum(v["deposit"] or 0 for v in invs.values() if v["supplier_id"] == s["id"]))
            s["to_pay"] = r2(s["total"] - s["deposit"])
            s["invoices"] = ", ".join(v["number"] or "без №" for v in invs.values() if v["supplier_id"] == s["id"])
        return sups, invs, items

    def catalog(self, q):
        """Весь справочник одним ответом; ?q= — поиск по артикулу, названию, поставщику (для бота)."""
        c = self._db(); sups, invs, items = self._catalog_data(c); c.close()
        qq = ((q.get("q") or [""])[0] or "").strip().lower()
        if qq:
            nq = re.sub(r"[\s\-_.]", "", qq)
            items = [i for i in items if nq in re.sub(r"[\s\-_.]", "", (i["article"] or "").lower())
                     or qq in " ".join(str(i[k] or "") for k in ("name", "what", "supplier_name", "supplier_cn", "note")).lower()]
        tot = {"suppliers": len(sups), "items": len(items), "total": r2(sum(s["total"] for s in sups.values())),
               "deposit": r2(sum(s["deposit"] for s in sups.values())), "unsure": len([i for i in items if i["unsure"]])}
        tot["to_pay"] = r2(tot["total"] - tot["deposit"])
        self._send(200, {"suppliers": list(sups.values()), "items": items, "totals": tot})

    def supplier_one(self, sid):
        c = self._db(); sups, invs, items = self._catalog_data(c, sid); c.close()
        if sid not in sups: return self._err(404, "Поставщик не найден")
        self._send(200, {**sups[sid], "invoice_list": list(invs.values()), "items": items})

    def supplier_save(self, b, sid=None):
        c = self._db()
        old = c.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone() if sid else None
        if sid and not old: c.close(); return self._err(404, "Поставщик не найден")
        cur = {**(dict(old) if old else {}), **b}
        if not (cur.get("name") or "").strip(): c.close(); return self._err(400, "Укажите название поставщика")
        vals = [(cur.get(k) or "").strip() for k in SUP_FIELDS]
        if sid:
            c.execute("UPDATE suppliers SET %s, updated_at=? WHERE id=?" % ",".join("%s=?" % k for k in SUP_FIELDS), vals + [now(), sid])
        else:
            sid = c.execute("INSERT INTO suppliers(%s,created_at,updated_at) VALUES(%s)" % (",".join(SUP_FIELDS), ",".join("?" * (len(SUP_FIELDS) + 2))),
                            vals + [now(), now()]).lastrowid
        commit(c); c.close(); self._send(200, {"ok": True, "id": sid})

    def supplier_delete(self, sid):
        c = self._db()
        if not c.execute("SELECT 1 FROM suppliers WHERE id=?", (sid,)).fetchone(): c.close(); return self._err(404, "Поставщик не найден")
        c.execute("DELETE FROM catalog_items WHERE supplier_id=?", (sid,))
        c.execute("DELETE FROM supplier_invoices WHERE supplier_id=?", (sid,))
        c.execute("DELETE FROM suppliers WHERE id=?", (sid,))
        commit(c); c.close(); self._send(200, {"ok": True})

    def citem_save(self, b, iid=None):
        c = self._db()
        old = c.execute("SELECT * FROM catalog_items WHERE id=?", (iid,)).fetchone() if iid else None
        if iid and not old: c.close(); return self._err(404, "Товар не найден")
        cur = {**(dict(old) if old else {}), **b}
        try: sid = int(cur.get("supplier_id") or 0)
        except Exception: sid = 0
        if not c.execute("SELECT 1 FROM suppliers WHERE id=?", (sid,)).fetchone(): c.close(); return self._err(400, "Поставщик не найден")
        inv = cur.get("invoice_id") or None
        if inv and not c.execute("SELECT 1 FROM supplier_invoices WHERE id=? AND supplier_id=?", (inv, sid)).fetchone(): inv = None
        article, name = (cur.get("article") or "").strip(), (cur.get("name") or "").strip()
        if not (article or name): c.close(); return self._err(400, "Укажите артикул или название")
        qty, price = num(cur.get("qty"), "количество"), num(cur.get("price"), "цена")
        if (qty is not None and qty < 0) or (price is not None and price < 0): c.close(); return self._err(400, "Количество и цена не могут быть отрицательными")
        vals = (sid, inv, article, name or article, (cur.get("what") or "").strip(), qty, price,
                (cur.get("note") or "").strip(), 1 if cur.get("unsure") in (1, True, "1", "true") else 0)
        if iid:
            c.execute("UPDATE catalog_items SET supplier_id=?,invoice_id=?,article=?,name=?,what=?,qty=?,price=?,note=?,unsure=?,updated_at=? WHERE id=?",
                      vals + (now(), iid))
        else:
            iid = c.execute("INSERT INTO catalog_items(supplier_id,invoice_id,article,name,what,qty,price,note,unsure,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            vals + (now(), now())).lastrowid
        commit(c); c.close(); self._send(200, {"ok": True, "id": iid})

    def citem_one(self, iid):
        c = self._db(); r = c.execute("SELECT * FROM catalog_items WHERE id=?", (iid,)).fetchone(); c.close()
        if not r: return self._err(404, "Товар не найден")
        self._send(200, dict(r))

    def citem_delete(self, iid):
        c = self._db()
        if not c.execute("SELECT 1 FROM catalog_items WHERE id=?", (iid,)).fetchone(): c.close(); return self._err(404, "Товар не найден")
        c.execute("DELETE FROM catalog_items WHERE id=?", (iid,)); commit(c); c.close(); self._send(200, {"ok": True})

    def catalog_import(self, b):
        """Кнопка «Загрузить накладные»: файл .json с расшифровкой."""
        c = self._db()
        res = import_catalog(c, b); commit(c)
        c.close(); self._send(200, {"ok": True, **res})

def import_catalog(c, b):
    """Загрузка расшифрованных накладных файлом .json: {suppliers, invoices, lines}.
    Поставщик узнаётся по названию; уже загруженная накладная пропускается — повторная загрузка ничего не задвоит."""
    sups, invs, lines = b.get("suppliers"), b.get("invoices"), b.get("lines")
    if not (isinstance(sups, list) and isinstance(invs, list) and isinstance(lines, list)):
        raise ValueError("Это не файл накладных: нужны разделы suppliers, invoices, lines")
    res = {"suppliers": 0, "invoices": 0, "items": 0, "skipped_invoices": 0}
    try:
        existing = {}
        for r in c.execute("SELECT id, name, name_cn FROM suppliers"):
            for k in (r["name_cn"], r["name"]):
                if k: existing.setdefault(k.strip().lower(), r["id"])
        sid_of = {}
        for s in sups:
            if not isinstance(s, dict) or not (s.get("name") or "").strip(): continue
            key = s.get("key") or s["name"]
            found = existing.get((s.get("name_cn") or "").strip().lower()) or existing.get(s["name"].strip().lower())
            if not found:
                vals = [(str(s.get(k) or "")).strip() for k in SUP_FIELDS]
                found = c.execute("INSERT INTO suppliers(%s,created_at,updated_at) VALUES(%s)" % (",".join(SUP_FIELDS), ",".join("?" * (len(SUP_FIELDS) + 2))),
                                  vals + [now(), now()]).lastrowid
                res["suppliers"] += 1
            sid_of[key] = found
        inv_of, skip = {}, set()
        for v in invs:
            sid = sid_of.get((v or {}).get("supplier"))
            if not sid: continue
            number, d = str(v.get("number") or "").strip(), valid_date(v.get("date"), "дата накладной", required=False)
            paper = num(v.get("paper_total"), "итог накладной"); dep = num(v.get("deposit"), "залог") or 0.0
            dup = c.execute("SELECT id FROM supplier_invoices WHERE supplier_id=? AND COALESCE(number,'')=? AND COALESCE(date,'')=?",
                            (sid, number, d or "")).fetchone()
            if dup: skip.add((v.get("supplier"), number)); res["skipped_invoices"] += 1; continue
            inv_of[(v.get("supplier"), number)] = c.execute(
                "INSERT INTO supplier_invoices(supplier_id,number,date,paper_total,deposit,note,created_at) VALUES(?,?,?,?,?,?,?)",
                (sid, number, d, paper, dep, str(v.get("note") or "").strip(), now())).lastrowid
            res["invoices"] += 1
        for l in lines:
            if not isinstance(l, dict): continue
            key = (l.get("supplier"), str(l.get("invoice") or "").strip())
            sid = sid_of.get(l.get("supplier"))
            if not sid or key in skip: continue
            article, name = str(l.get("article") or "").strip(), str(l.get("name") or "").strip()
            if not (article or name): continue
            c.execute("INSERT INTO catalog_items(supplier_id,invoice_id,article,name,what,qty,price,note,unsure,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (sid, inv_of.get(key), article, name or article, str(l.get("what") or "").strip(), num(l.get("qty"), "количество"),
                       num(l.get("price"), "цена"), str(l.get("note") or "").strip(), 1 if l.get("unsure") else 0, now(), now()))
            res["items"] += 1
    except Exception:
        c.rollback(); raise
    return res


SEED_DIR = os.path.join(ROOT, "seed")

def seed_catalog():
    """Накладные, положенные в папку seed/, загружаются при запуске — каждый файл ровно один раз.
    Отметка о загрузке хранится в настройках по хэшу файла: если потом что-то удалить или исправить
    в программе, перезапуск сервера это не вернёт."""
    if not os.path.isdir(SEED_DIR): return
    for fn in sorted(os.listdir(SEED_DIR)):
        if not fn.endswith(".json"): continue
        raw = open(os.path.join(SEED_DIR, fn), "rb").read()
        mark = "seed:" + hashlib.sha256(raw).hexdigest()[:16]
        c = db()
        try:
            if c.execute("SELECT 1 FROM settings WHERE key=?", (mark,)).fetchone(): continue
            res = import_catalog(c, json.loads(raw.decode("utf-8")))
            set_setting(c, mark, "%s %s" % (fn, now())); commit(c)
            print("Справочник: загружен %s — поставщиков %d, накладных %d, товаров %d, уже были %d"
                  % (fn, res["suppliers"], res["invoices"], res["items"], res["skipped_invoices"]), flush=True)
        except Exception as e:
            print("Справочник: не удалось загрузить %s: %s" % (fn, e), flush=True)
        finally:
            c.close()

def main():
    init_db()
    seed_catalog()
    b = backup_db()
    if b: print("Резервная копия:", os.path.basename(b))
    icon = os.path.join(WEB, "icon.png")
    if not os.path.exists(icon):
        try: make_icon(icon)
        except Exception as e: print("Иконка не создана:", e)
    keepalive()
    if tgbot:
        threading.Timer(2, lambda: tgbot.start({
            "port": PORT, "web_url": web_url()})).start()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print("Бутики · учёт %s работает: http://%s:%d · база: %s · вход не нужен" % (
        VERSION, "localhost" if HOST == "127.0.0.1" else HOST, PORT, "Postgres/" + PG_SCHEMA if IS_PG else "SQLite"), flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
