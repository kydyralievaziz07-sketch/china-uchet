#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Китай · учёт — программа учёта закупок товаров из Китая.
Этап 1: партии с вложенными товарами, справочники, статусы, авансы.
Этап 2: платежи поставщикам, автоматический аванс по платежам, долги, карточка поставщика.
Этап 3: фильтры по периоду / магазину / поставщику, сортировка, разделение партии, экспорт по фильтру.
Этап 4: инвесторы — вложения, доли, выплаты, прибыль по партии, отчёт инвестору.
Этап 5: облако — та же программа на Render + Postgres (Supabase), вход по паролю (KN_AUTH=1),
        роль «помощник» без денег, пользователи, перенос базы файлом .db, поддержание сервиса бодрым.
Стандартная библиотека Python + SQLite локально; в облаке — pg8000 и Postgres (DATABASE_URL).
"""
import base64, csv, hashlib, hmac, io, json, os, re, shutil, sqlite3, secrets, struct, sys, threading, time, zlib
from collections import defaultdict
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

VERSION = "5.2.0"
ROOT = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(ROOT, "china.db")
WEB  = os.path.join(ROOT, "web")
PORT = int(os.environ.get("PORT", "8902"))
HOST = "0.0.0.0" if (os.environ.get("RENDER") or os.environ.get("KN_HOST") == "0.0.0.0") else "127.0.0.1"
SECRET_FILE = os.path.join(ROOT, ".secret")
# Вход по логину и паролю нужен только облачной версии. Локально программа открывается сразу.
AUTH = os.environ.get("KN_AUTH", "0") == "1"
# Личная ссылка вместо пароля: открыл https://…/?k=КЛЮЧ один раз — устройство помнит вход год.
OPEN_KEY = (os.environ.get("KN_OPEN_KEY") or "").strip()
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
PG_SCHEMA = re.sub(r"[^a-z0-9_]", "", (os.environ.get("KN_PG_SCHEMA") or "china").lower()) or "china"

# ---------------------------------------------------------------- база: схема
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'owner',           -- owner | helper
  name TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS partners(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  is_supplier INTEGER NOT NULL DEFAULT 1,
  is_investor INTEGER NOT NULL DEFAULT 0,
  contact TEXT, city TEXT,
  currency TEXT NOT NULL DEFAULT 'USD',
  note TEXT, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS stores(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT NOT NULL, name TEXT, note TEXT,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS shipments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,                            -- YYYY-MM-DD
  supplier_id INTEGER NOT NULL REFERENCES partners(id),
  currency TEXT NOT NULL DEFAULT 'USD',
  rate REAL,
  prepaid REAL NOT NULL DEFAULT 0,               -- ручной аванс (пока нет платежей)
  status TEXT NOT NULL DEFAULT 'new',            -- new|shipping|arrived|cancelled
  sent_date TEXT, arrived_date TEXT, eta_date TEXT,
  track TEXT, default_store_id INTEGER REFERENCES stores(id),
  profit REAL, closed_at TEXT,                   -- прибыль по партии вводится вручную при закрытии
  note TEXT, deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS shipment_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  store_id INTEGER NOT NULL REFERENCES stores(id),
  product TEXT NOT NULL,
  qty REAL, unit TEXT DEFAULT 'шт',
  unit_price REAL,
  amount REAL NOT NULL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS payments(               -- этап 2
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  supplier_id INTEGER NOT NULL REFERENCES partners(id),
  shipment_id INTEGER REFERENCES shipments(id),
  amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  kind TEXT NOT NULL DEFAULT 'prepay',             -- prepay|final|refund
  method TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS investments(            -- этап 4
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  investor_id INTEGER NOT NULL REFERENCES partners(id),
  shipment_id INTEGER REFERENCES shipments(id),    -- NULL = общий пул
  amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  terms TEXT NOT NULL DEFAULT 'share', terms_value REAL,   -- share: % от прибыли | fixed: % в месяц
  note TEXT
);
CREATE TABLE IF NOT EXISTS investor_payouts(       -- этап 4
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  investor_id INTEGER NOT NULL REFERENCES partners(id),
  amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  kind TEXT NOT NULL DEFAULT 'profit',             -- profit|principal
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_sh_date ON shipments(date);
CREATE INDEX IF NOT EXISTS idx_sh_supplier ON shipments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_sh_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_it_shipment ON shipment_items(shipment_id);
CREATE INDEX IF NOT EXISTS idx_it_store ON shipment_items(store_id);
CREATE INDEX IF NOT EXISTS idx_pay_supplier ON payments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_pay_shipment ON payments(shipment_id);
CREATE INDEX IF NOT EXISTS idx_pay_date ON payments(date);
CREATE INDEX IF NOT EXISTS idx_inv_investor ON investments(investor_id);
CREATE INDEX IF NOT EXISTS idx_po_investor ON investor_payouts(investor_id);
"""
# Та же схема для Postgres: SERIAL вместо AUTOINCREMENT, DOUBLE PRECISION вместо REAL, даты остаются текстом.
PG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY, login TEXT NOT NULL UNIQUE, pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'owner', name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS partners(id SERIAL PRIMARY KEY, name TEXT NOT NULL, is_supplier INTEGER NOT NULL DEFAULT 1,
  is_investor INTEGER NOT NULL DEFAULT 0, contact TEXT, city TEXT, currency TEXT NOT NULL DEFAULT 'USD', note TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS stores(id SERIAL PRIMARY KEY, number TEXT NOT NULL, name TEXT, note TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS shipments(id SERIAL PRIMARY KEY, date TEXT NOT NULL, supplier_id INTEGER NOT NULL REFERENCES partners(id),
  currency TEXT NOT NULL DEFAULT 'USD', rate DOUBLE PRECISION, prepaid DOUBLE PRECISION NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'new', sent_date TEXT, arrived_date TEXT, eta_date TEXT, track TEXT,
  default_store_id INTEGER REFERENCES stores(id), profit DOUBLE PRECISION, closed_at TEXT, note TEXT,
  deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS shipment_items(id SERIAL PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  store_id INTEGER NOT NULL REFERENCES stores(id), product TEXT NOT NULL, qty DOUBLE PRECISION, unit TEXT DEFAULT 'шт',
  unit_price DOUBLE PRECISION, amount DOUBLE PRECISION NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS payments(id SERIAL PRIMARY KEY, date TEXT NOT NULL, supplier_id INTEGER NOT NULL REFERENCES partners(id),
  shipment_id INTEGER REFERENCES shipments(id), amount DOUBLE PRECISION NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  kind TEXT NOT NULL DEFAULT 'prepay', method TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS investments(id SERIAL PRIMARY KEY, date TEXT NOT NULL, investor_id INTEGER NOT NULL REFERENCES partners(id),
  shipment_id INTEGER REFERENCES shipments(id), amount DOUBLE PRECISION NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  terms TEXT NOT NULL DEFAULT 'share', terms_value DOUBLE PRECISION, note TEXT, end_date TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS investor_payouts(id SERIAL PRIMARY KEY, date TEXT NOT NULL, investor_id INTEGER NOT NULL REFERENCES partners(id),
  amount DOUBLE PRECISION NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', kind TEXT NOT NULL DEFAULT 'profit', note TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_sh_date ON shipments(date);
CREATE INDEX IF NOT EXISTS idx_sh_supplier ON shipments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_sh_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_it_shipment ON shipment_items(shipment_id);
CREATE INDEX IF NOT EXISTS idx_it_store ON shipment_items(store_id);
CREATE INDEX IF NOT EXISTS idx_pay_supplier ON payments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_pay_shipment ON payments(shipment_id);
CREATE INDEX IF NOT EXISTS idx_inv_investor ON investments(investor_id);
CREATE INDEX IF NOT EXISTS idx_po_investor ON investor_payouts(investor_id);
CREATE OR REPLACE FUNCTION plower(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT lower(coalesce(t, '')) $$
"""
TABLES = ["users", "settings", "partners", "stores", "shipments", "shipment_items", "payments", "investments", "investor_payouts"]

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
        def __init__(self, raw): self.raw = raw; self.broken = False
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
        # LOWER() в SQLite не понимает кириллицу — своя функция
        c.create_function("plower", 1, lambda s: (s or "").lower())
        return c

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def today(): return date.today().isoformat()

def migrate_sqlite(c):
    """Добавляем колонки, которых нет в старых базах SQLite (без потери данных)."""
    def cols(t): return [r["name"] for r in c.execute("PRAGMA table_info(%s)" % t)]
    if "created_at" not in cols("payments"): c.execute("ALTER TABLE payments ADD COLUMN created_at TEXT")
    if "end_date" not in cols("investments"): c.execute("ALTER TABLE investments ADD COLUMN end_date TEXT")
    if "created_at" not in cols("investments"): c.execute("ALTER TABLE investments ADD COLUMN created_at TEXT")
    if "created_at" not in cols("investor_payouts"): c.execute("ALTER TABLE investor_payouts ADD COLUMN created_at TEXT")

def pw_hash(password, salt): return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()

def init_db():
    c = db()
    if IS_PG:
        c.execute("CREATE SCHEMA IF NOT EXISTS %s" % PG_SCHEMA)
        c.executescript(PG_SCHEMA_SQL)
    else:
        c.executescript(SCHEMA); migrate_sqlite(c)
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        salt = secrets.token_hex(16)
        c.execute("INSERT INTO users(login,pw_hash,salt,role,name,created_at) VALUES(?,?,?,?,?,?)",
                  ("admin", pw_hash("china2026", salt), salt, "owner", "Владелец", now()))
    commit(c)
    # пароль владельца из окружения (облако): применяется, если отличается от текущего
    env_pw = os.environ.get("KN_ADMIN_PASSWORD")
    if env_pw:
        u = c.execute("SELECT * FROM users WHERE login='admin'").fetchone()
        if u and not hmac.compare_digest(pw_hash(env_pw, u["salt"]), u["pw_hash"]):
            salt = secrets.token_hex(16)
            c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (pw_hash(env_pw, salt), salt, u["id"]))
            commit(c); print("Пароль владельца обновлён из KN_ADMIN_PASSWORD")
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
        rows = c.execute("SELECT * FROM %s ORDER BY %s" % (t, "key" if t == "settings" else "id")).fetchall()
        if not rows: continue
        cols = list(rows[0].keys())
        dst.executemany("INSERT INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))),
                        [tuple(r[k] for k in cols) for r in rows])
    dst.commit(); dst.close(); c.close()
    data = open(tmp, "rb").read(); os.remove(tmp)
    return data

def import_sqlite_file(path):
    """Загрузить базу из файла .db (перенос с компьютера в облако и обратно). Пользователи не трогаются."""
    src = sqlite3.connect(path); src.row_factory = sqlite3.Row
    try: src.execute("SELECT 1 FROM shipments LIMIT 1")
    except Exception: src.close(); raise ValueError("Это не база «Китай · учёт»")
    tables = [t for t in TABLES if t != "users"]
    counts = {}
    if IS_PG:
        c = db()
        try:
            for t in reversed(tables): c.execute("DELETE FROM %s" % t)
            for t in tables:
                cols_src = [r[1] for r in src.execute("PRAGMA table_info(%s)" % t)]
                if not cols_src: continue
                cols_dst = [r["column_name"] for r in c.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?", (PG_SCHEMA, t))]
                cols = [x for x in cols_src if x in cols_dst]
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
        # пользователей берём из текущей базы, остальное — из файла
        cur = sqlite3.connect(DB); cur.row_factory = sqlite3.Row
        users = [dict(r) for r in cur.execute("SELECT * FROM users")]
        cur.close()
        shutil.copy2(path, DB)
        c = db(); migrate_sqlite(c)
        c.execute("DELETE FROM users")
        for u in users:
            c.execute("INSERT INTO users(id,login,pw_hash,salt,role,name,created_at) VALUES(?,?,?,?,?,?,?)",
                      (u["id"], u["login"], u["pw_hash"], u["salt"], u["role"], u["name"], u["created_at"]))
        commit(c); c.close()
        return counts
    src.close()
    return counts

def make_icon(path, size=180):
    """Иконка для домашнего экрана телефона: градиент + мотив маршрута. Чистый Python, без библиотек."""
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    pts = [(0.24, 0.52), (0.5, 0.52), (0.76, 0.52)]
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            r, g, b = int(0x6C + (0x3E - 0x6C) * t), int(0x8C + (0xD8 - 0x8C) * t), int(0xFF + (0xD0 - 0xFF) * t)
            fx, fy = (x + .5) / size, (y + .5) / size
            dark = False
            if pts[0][0] <= fx <= pts[2][0] and abs(fy - 0.52) < 0.022: dark = True
            for px, py in pts:
                if (fx - px) ** 2 + (fy - py) ** 2 < 0.07 ** 2: dark = True
            if dark: r, g, b = 0x06, 0x07, 0x0C
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

# ---------------------------------------------------------------- сессии
def get_secret():
    env = os.environ.get("KN_SECRET")
    if env: return env
    if not os.path.exists(SECRET_FILE):
        open(SECRET_FILE, "w").write(secrets.token_hex(32))
    return open(SECRET_FILE).read().strip()

SECRET = None
def sign(msg): return hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def make_token(login, days=30):
    exp = str(int(time.time()) + days*86400)
    raw = "%s|%s" % (login, exp)
    return base64.urlsafe_b64encode(("%s|%s" % (raw, sign(raw))).encode()).decode()

TOK_CACHE = {}   # токен → (пользователь, время); чтобы не ходить в базу за каждым запросом
def check_token(tok):
    hit = TOK_CACHE.get(tok)
    if hit and time.time() - hit[1] < 120: return dict(hit[0])
    try:
        raw = base64.urlsafe_b64decode(tok.encode()).decode()
        login, exp, sig = raw.rsplit("|", 2)
        if not hmac.compare_digest(sig, sign("%s|%s" % (login, exp))): return None
        if int(exp) < time.time(): return None
        c = db(); u = c.execute("SELECT id,login,role,name FROM users WHERE login=?", (login,)).fetchone(); c.close()
        if u: TOK_CACHE[tok] = (dict(u), time.time())
        return dict(u) if u else None
    except Exception as e:
        print("check_token:", repr(e), file=sys.stderr, flush=True)
        return None

def check_password(login, password):
    c = db(); u = c.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone(); c.close()
    if not u: return None
    return dict(u) if hmac.compare_digest(pw_hash(password, u["salt"]), u["pw_hash"]) else None

def owner_user():
    c = db(); u = c.execute("SELECT id,login,role,name FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone(); c.close()
    return dict(u) if u else None

# ---------------------------------------------------------------- бизнес-логика
VALID_STATUS = ("new", "shipping", "arrived", "cancelled")
VALID_KIND   = ("prepay", "final", "refund")
VALID_TERMS  = ("share", "fixed")
VALID_PAYOUT = ("profit", "principal")
MONEY_SHIP = ("prepaid", "paid", "paid_by_payments", "balance", "rate", "profit", "closed_at", "payments", "shares", "investors", "amount", "pay_mode")

def signed(p):
    """Платёж со знаком: возврат уменьшает отданное."""
    a = float(p["amount"] or 0)
    return -a if p["kind"] == "refund" else a

def r2(x): return round(float(x or 0), 2)

def get_settings(c):
    s = {"currency": "USD", "rate": None}
    for r in c.execute("SELECT key, value FROM settings"):
        if r["key"] == "currency" and r["value"] in ("USD", "CNY", "KGS"): s["currency"] = r["value"]
        if r["key"] == "rate":
            try: s["rate"] = float(r["value"]) if r["value"] not in (None, "") else None
            except Exception: pass
    return s

def set_setting(c, key, value):
    if IS_PG:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, value))
    else:
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))

# ---------------------------------------------------------------- снимок базы (7 запросов вместо сотен — важно для облака)
SNAP = {"snap": None, "t": 0.0, "dirty": True}
SNAP_TTL = 20   # секунд; любая запись помечает снимок устаревшим

class Snap:
    """Все таблицы одним махом + индексы. Дальше расчёты идут в памяти без запросов."""
    def __init__(self, c):
        self.partners = {r["id"]: dict(r) for r in c.execute("SELECT * FROM partners")}
        self.stores = {r["id"]: dict(r) for r in c.execute("SELECT * FROM stores")}
        self.ships = {r["id"]: dict(r) for r in c.execute("SELECT * FROM shipments")}
        self.items = defaultdict(list)
        for r in c.execute("SELECT * FROM shipment_items ORDER BY id"):
            d = dict(r); st = self.stores.get(d["store_id"]) or {}
            d["store_number"] = st.get("number") or "?"; d["store_name"] = st.get("name") or ""
            self.items[d["shipment_id"]].append(d)
        self.pays = [dict(r) for r in c.execute("SELECT * FROM payments ORDER BY date, id")]
        self.pays_by_ship = defaultdict(list); self.pays_by_sup = defaultdict(list)
        for p in self.pays:
            if p["shipment_id"]: self.pays_by_ship[p["shipment_id"]].append(p)
            self.pays_by_sup[p["supplier_id"]].append(p)
        self.invs = [dict(r) for r in c.execute("SELECT * FROM investments ORDER BY date DESC, id DESC")]
        self.invs_by_ship = defaultdict(list); self.invs_by_investor = defaultdict(list)
        for v in self.invs:
            self.enrich_inv(v)
            if v["shipment_id"]: self.invs_by_ship[v["shipment_id"]].append(v)
            self.invs_by_investor[v["investor_id"]].append(v)
        self.payouts = [dict(r) for r in c.execute("SELECT * FROM investor_payouts ORDER BY date DESC, id DESC")]
        self.payouts_by_investor = defaultdict(list)
        for o in self.payouts:
            o["investor_name"] = (self.partners.get(o["investor_id"]) or {}).get("name", "?")
            self.payouts_by_investor[o["investor_id"]].append(o)
        self.pool_total = float(sum(v["amount"] or 0 for v in self.invs if not v["shipment_id"]))
    def ship_amount(self, sid): return r2(sum(i["amount"] or 0 for i in self.items.get(sid, [])))
    def enrich_inv(self, v):
        v["investor_name"] = (self.partners.get(v["investor_id"]) or {}).get("name", "?")
        s = self.ships.get(v["shipment_id"]) if v["shipment_id"] else None
        v["ship_date"] = s["date"] if s else None; v["ship_status"] = s["status"] if s else None
        v["ship_profit"] = s["profit"] if s else None; v["ship_closed"] = s["closed_at"] if s else None
        v["ship_deleted"] = (s["deleted"] if s else (1 if v["shipment_id"] else 0))
        v["ship_amount"] = self.ship_amount(v["shipment_id"]) if s else 0
        v["ship_supplier"] = (self.partners.get(s["supplier_id"]) or {}).get("name") if s else None
        return v
    def enrich_pay(self, p):
        p = dict(p); s = self.ships.get(p["shipment_id"]) if p["shipment_id"] else None
        p["supplier_name"] = (self.partners.get(p["supplier_id"]) or {}).get("name", "?")
        p["ship_date"] = s["date"] if s else None; p["ship_status"] = s["status"] if s else None
        p["ship_deleted"] = (s["deleted"] if s else (1 if p["shipment_id"] else 0))
        p["ship_amount"] = self.ship_amount(p["shipment_id"]) if s else 0
        return p

def get_snap(c):
    if SNAP["dirty"] or SNAP["snap"] is None or time.time() - SNAP["t"] > SNAP_TTL:
        SNAP["snap"] = Snap(c); SNAP["t"] = time.time(); SNAP["dirty"] = False
    return SNAP["snap"]

def commit(c):
    c.commit(); SNAP["dirty"] = True

def payments_of_shipment(c, sid):
    return [dict(p) for p in get_snap(c).pays_by_ship.get(sid, [])]

def months_between(a, b):
    """Полных месяцев от даты a до даты b."""
    if b < a: return 0
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day: m -= 1
    return max(0, m)

def pool_total(c): return get_snap(c).pool_total

def pool_profit_since(c, since):
    """Прибыль закрытых партий без адресных вложений, закрытых начиная с даты since."""
    sn = get_snap(c)
    return float(sum(s["profit"] or 0 for s in sn.ships.values()
                     if not s["deleted"] and s["profit"] is not None and (s["closed_at"] or s["date"]) >= since
                     and not sn.invs_by_ship.get(s["id"])))

def accrual_of(c, v, ptotal=None):
    """Сколько начислено инвестору по одному вложению + пояснение."""
    val = float(v["terms_value"] or 0)
    if v["terms"] == "fixed":
        end = date.fromisoformat(v["end_date"]) if v.get("end_date") else date.today()
        m = months_between(date.fromisoformat(v["date"]), end)
        return r2(float(v["amount"]) * val / 100 * m), "%d полн. мес. × %g%% в месяц" % (m, val)
    if v.get("shipment_id"):
        if v.get("ship_deleted"): return 0.0, "партия удалена"
        if v.get("ship_profit") is None: return 0.0, "партия ещё не закрыта"
        return r2(float(v["ship_profit"]) * val / 100), "%g%% от прибыли %s" % (val, r2(v["ship_profit"]))
    pt = pool_total(c) if ptotal is None else ptotal
    if not pt: return 0.0, "общий пул пуст"
    frac = float(v["amount"]) / pt
    prof = pool_profit_since(c, v["date"])
    return r2(prof * frac * val / 100), "доля пула %.1f%% × %g%% от прибыли %s" % (frac * 100, val, r2(prof))

INV_SQL = """SELECT v.*, p.name investor_name, s.date ship_date, s.status ship_status, s.profit ship_profit,
                    s.closed_at ship_closed, s.deleted ship_deleted,
                    (SELECT COALESCE(SUM(amount),0) FROM shipment_items WHERE shipment_id=s.id) ship_amount,
                    (SELECT name FROM partners WHERE id=s.supplier_id) ship_supplier
             FROM investments v JOIN partners p ON p.id=v.investor_id
             LEFT JOIN shipments s ON s.id=v.shipment_id"""
PO_SQL = "SELECT o.*, p.name investor_name FROM investor_payouts o JOIN partners p ON p.id=o.investor_id"

def investor_calc(c, iid, with_lists=True):
    sn = get_snap(c)
    invs = [dict(v) for v in sn.invs_by_investor.get(iid, [])]
    for v in invs:
        v["accrued"], v["accrual_note"] = accrual_of(c, v, sn.pool_total)
    pays = [dict(o) for o in sn.payouts_by_investor.get(iid, [])]
    invested = r2(sum(v["amount"] for v in invs))
    accrued = r2(sum(v["accrued"] for v in invs))
    paid_profit = r2(sum(p["amount"] for p in pays if p["kind"] == "profit"))
    paid_principal = r2(sum(p["amount"] for p in pays if p["kind"] == "principal"))
    out = {"invested": invested, "accrued": accrued, "paid_profit": paid_profit, "paid_principal": paid_principal,
           "due": r2(accrued - paid_profit), "principal_out": r2(invested - paid_principal),
           "investments_count": len(invs), "payouts_count": len(pays),
           "open_count": len([v for v in invs if v["terms"] == "share" and v.get("shipment_id")
                              and v.get("ship_profit") is None and not v.get("ship_deleted")])}
    if with_lists: out["investments"], out["payouts"] = invs, pays
    return out

def shipment_shares(c, s):
    """Распределение прибыли закрытой партии по инвесторам (для карточки партии)."""
    if s.get("profit") is None: return []
    sn = get_snap(c); out = []
    direct = sn.invs_by_ship.get(s["id"], [])
    for v in direct:
        acc, note = accrual_of(c, v, sn.pool_total)
        out.append({"name": v["investor_name"], "investor_id": v["investor_id"], "kind": "direct", "amount": v["amount"],
                    "terms": v["terms"], "terms_value": v["terms_value"], "accrued": acc, "note": note})
    if not direct and sn.pool_total:
        since = s.get("closed_at") or s["date"]
        for v in sorted((v for v in sn.invs if not v["shipment_id"] and v["terms"] == "share" and v["date"] <= since), key=lambda v: v["date"]):
            frac = float(v["amount"]) / sn.pool_total
            out.append({"name": v["investor_name"], "investor_id": v["investor_id"], "kind": "pool", "amount": v["amount"],
                        "terms": "share", "terms_value": v["terms_value"], "accrued": r2(float(s["profit"]) * frac * float(v["terms_value"] or 0) / 100),
                        "note": "доля пула %.1f%% × %g%%" % (frac * 100, float(v["terms_value"] or 0))})
    return out

def pack_shipment(c, row):
    sn = get_snap(c)
    d = dict(row)
    items = [dict(i) for i in sn.items.get(d["id"], [])]
    d["items"] = items
    d["amount"] = r2(sum(i["amount"] or 0 for i in items))
    # деньги: если по партии есть платежи — аванс считается по ним, иначе ручное поле
    pays = [dict(p) for p in sn.pays_by_ship.get(d["id"], [])]
    d["payments"] = pays
    d["paid_by_payments"] = r2(sum(signed(p) for p in pays))
    d["pay_mode"] = "auto" if pays else "manual"
    d["paid"] = d["paid_by_payments"] if pays else r2(d["prepaid"])
    d["balance"] = r2(d["amount"] - d["paid"])
    sup = sn.partners.get(d["supplier_id"])
    d["supplier_name"] = sup["name"] if sup else "?"
    d["supplier_city"] = (sup["city"] or "") if sup else ""
    d["stores"] = sorted({i["store_number"] for i in items})
    if d["status"] == "shipping" and d["sent_date"]:
        d["days_transit"] = max(0, (date.today() - date.fromisoformat(d["sent_date"])).days)
    else:
        d["days_transit"] = None
    d["investors"] = [{"id": v["id"], "investor_id": v["investor_id"], "name": v["investor_name"], "amount": v["amount"],
                       "terms": v["terms"], "terms_value": v["terms_value"]} for v in sn.invs_by_ship.get(d["id"], [])]
    d["shares"] = shipment_shares(c, d)
    return d

def strip_money(d):
    """Помощник не видит денег: убираем денежные поля партии и товаров."""
    for k in MONEY_SHIP: d.pop(k, None)
    for i in d.get("items", []): i.pop("unit_price", None); i.pop("amount", None)
    return d

def paid_for_debt(s):
    """Сколько денег реально ушло поставщику по партии (для долга).
    Платежи считаются всегда; ручной аванс — только по живым партиям."""
    if s["pay_mode"] == "auto": return s["paid_by_payments"]
    return s["paid"] if s["status"] != "cancelled" else 0.0

def unlinked_payments(c, pid):
    """Платежи поставщику без партии (или по удалённой партии)."""
    sn = get_snap(c); tot, n = 0.0, 0
    for p in sn.pays_by_sup.get(pid, []):
        s = sn.ships.get(p["shipment_id"]) if p["shipment_id"] else None
        if not p["shipment_id"] or not s or s["deleted"]:
            tot += signed(p); n += 1
    return r2(tot), n

def supplier_finance(c, pid, ships=None):
    sn = get_snap(c)
    if ships is None:
        ships = [pack_shipment(c, s) for s in sn.ships.values() if s["supplier_id"] == pid and not s["deleted"]]
    live = [s for s in ships if s["status"] != "cancelled"]
    total = r2(sum(s["amount"] for s in live))
    linked = sum(paid_for_debt(s) for s in ships)
    unl, unl_n = unlinked_payments(c, pid)
    paid = r2(linked + unl)
    npay = len(sn.pays_by_sup.get(pid, []))
    return {"shipments": len(ships), "total": total, "paid": paid, "debt": r2(total - paid),
            "transit": r2(sum(s["amount"] for s in ships if s["status"] == "shipping")),
            "unlinked": unl, "payments": npay}

def ship_filter(sn, q):
    """Фильтр партий по параметрам запроса — в памяти, без SQL."""
    st, sup, frm, to = (q.get("status") or [""])[0], (q.get("supplier") or [""])[0], (q.get("from") or [""])[0], (q.get("to") or [""])[0]
    store, qq = (q.get("store") or [""])[0], ((q.get("q") or [""])[0] or "").lower().strip()
    out = []
    for s in sn.ships.values():
        if s["deleted"]: continue
        if st and s["status"] != st: continue
        if sup and str(s["supplier_id"]) != str(sup): continue
        if frm and s["date"] < frm: continue
        if to and s["date"] > to: continue
        items = sn.items.get(s["id"], [])
        if store and not any(str(i["store_id"]) == str(store) for i in items): continue
        if qq:
            sup_name = ((sn.partners.get(s["supplier_id"]) or {}).get("name") or "").lower()
            if not (qq in (s["track"] or "").lower() or qq in (s["note"] or "").lower() or qq in sup_name
                    or any(qq in (i["product"] or "").lower() for i in items)): continue
        out.append(s)
    return sorted(out, key=lambda s: (s["date"], s["id"]), reverse=True)

def pay_filter(sn, q):
    sup, ship, kind = (q.get("supplier") or [""])[0], (q.get("shipment") or [""])[0], (q.get("kind") or [""])[0]
    frm, to, qq = (q.get("from") or [""])[0], (q.get("to") or [""])[0], ((q.get("q") or [""])[0] or "").lower().strip()
    out = []
    for p in sn.pays:
        if sup and str(p["supplier_id"]) != str(sup): continue
        if ship and str(p["shipment_id"]) != str(ship): continue
        if kind and p["kind"] != kind: continue
        if frm and p["date"] < frm: continue
        if to and p["date"] > to: continue
        e = sn.enrich_pay(p)
        if qq and not (qq in (p["note"] or "").lower() or qq in (p["method"] or "").lower() or qq in e["supplier_name"].lower()): continue
        out.append(e)
    return sorted(out, key=lambda p: (p["date"], p["id"]), reverse=True)

def validate_shipment(body, c, helper=False):
    errs = []
    if not body.get("date"): errs.append("Не указана дата партии")
    if not body.get("supplier_id"): errs.append("Не выбран поставщик")
    elif not c.execute("SELECT 1 FROM partners WHERE id=?", (body["supplier_id"],)).fetchone():
        errs.append("Такого поставщика нет")
    items = body.get("items") or []
    if not items: errs.append("В партии нет ни одного товара")
    for n, i in enumerate(items, 1):
        if not i.get("product"): errs.append("Товар №%d: нет наименования" % n)
        if not i.get("store_id"): errs.append("Товар №%d: не выбран магазин" % n)
        if not helper and i.get("amount") in (None, "", 0): errs.append("Товар №%d: не указана сумма" % n)
    if body.get("status") and body["status"] not in VALID_STATUS: errs.append("Неверный статус")
    return errs

def apply_status_dates(body, old=None):
    st = body.get("status")
    if st == "shipping" and not (body.get("sent_date") or (old and old["sent_date"])):
        body["sent_date"] = today()
    if st == "arrived" and not (body.get("arrived_date") or (old and old["arrived_date"])):
        body["arrived_date"] = today()
    return body

def month_keys(n=7):
    cur = date.today().replace(day=1)
    out = []
    for k in range(n - 1, -1, -1):
        m = (cur.month - k - 1) % 12 + 1
        y = cur.year + (cur.month - k - 1) // 12
        out.append("%04d-%02d" % (y, m))
    return out

def esc(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def fmt_money(v, cur="USD"):
    n = float(v or 0)
    s = "{:,.2f}".format(abs(n)).replace(",", " ").rstrip("0").rstrip(".")
    sym = {"USD": "$", "CNY": "¥", "KGS": ""}.get(cur, "")
    body = (s + " с") if cur == "KGS" else sym + s
    return ("−" if n < -0.004 else "") + body

def fmt_date(d):
    if not d: return ""
    y, m, dd = d.split("-"); return "%s.%s.%s" % (dd, m, y)

# ---------------------------------------------------------------- HTTP
HELPER_DENY = ("/api/payments", "/api/investors", "/api/investments", "/api/payouts", "/api/summary",
               "/api/export", "/api/backup", "/api/restore", "/api/users")

class H(BaseHTTPRequestHandler):
    server_version = "ChinaUchet/" + VERSION
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

    def _body(self, limit=40_000_000):
        n = int(self.headers.get("Content-Length") or 0)
        if not n: return {}
        if n > limit: return {}
        try: return json.loads(self.rfile.read(n).decode())
        except Exception: return {}

    def _user(self):
        cookie = self.headers.get("Cookie") or ""
        m = re.search(r"kn_session=([^;]+)", cookie)
        u = check_token(m.group(1)) if m else None
        if u or AUTH: return u
        return owner_user()   # локальный режим: вход не нужен

    @property
    def helper(self): return bool(self.user) and self.user.get("role") == "helper"

    def _cookie(self, tok, max_age):
        secure = "; Secure" if (self.headers.get("X-Forwarded-Proto") == "https") else ""
        return "kn_session=%s; Max-Age=%d; Path=/; HttpOnly; SameSite=Lax%s" % (tok, max_age, secure)

    def _link(self, user):
        """Владельцу отдаём его личную ссылку входа — показать в настройках и открыть на телефоне."""
        return {"link": "/?k=" + OPEN_KEY} if (OPEN_KEY and (user or {}).get("role") == "owner") else {}

    def _key_login(self, path, q):
        """Вход по ссылке: ставим cookie на год и убираем ключ из адреса."""
        if not (OPEN_KEY and q.get("k")) or path.startswith("/api/"): return False
        try: ok = hmac.compare_digest(q["k"][0].encode("utf-8"), OPEN_KEY.encode("utf-8"))
        except Exception: ok = False
        if not ok: return False
        u = owner_user()
        if not u: return False
        self._send(302, b"", "text/html; charset=utf-8",
                   {"Location": path if path.startswith("/") else "/",
                    "Set-Cookie": self._cookie(make_token(u["login"], 365), 365*86400)})
        return True

    # -- маршрутизация
    def route(self, method):
        # http.server декодирует строку запроса как latin-1 — возвращаем UTF-8
        try: raw = self.path.encode("latin-1").decode("utf-8")
        except Exception: raw = self.path
        p = urlparse(raw)
        path, q = p.path.rstrip("/") or "/", parse_qs(p.query)
        self.user = None
        try:
            if method == "GET" and self._key_login(p.path or "/", q): return
            if path == "/" and method == "GET": return self.page()
            if path.startswith("/static/") and method == "GET": return self.static(path)
            if path == "/api/ping" and method == "GET":
                return self._send(200, {"ok": True, "version": VERSION, "db": "postgres" if IS_PG else "sqlite", "auth": AUTH})
            if path == "/api/login" and method == "POST": return self.api_login()
            user = self._user(); self.user = user
            if path.startswith("/api/") and not user: return self._err(401, "Нужен вход")
            if path == "/api/logout" and method == "POST":
                return self._send(200, {"ok": True}, headers={"Set-Cookie": self._cookie("", 0)})
            if path == "/api/me" and method == "GET":
                return self._send(200, {**user, "version": VERSION, "auth": AUTH, "cloud": IS_PG, **self._link(user)})
            if path == "/api/password" and method == "POST": return self.password_change(self._body())
            if self.helper and (method == "DELETE" or any(path.startswith(x) for x in HELPER_DENY)
                                or (path == "/api/settings" and method != "GET")
                                or (path.startswith("/api/partners/") and method == "GET")):
                return self._err(403, "Помощнику это недоступно")
            if path == "/api/settings":
                if method == "GET": return self.settings_get()
                if method == "PATCH": return self.settings_save(self._body())
            if path == "/api/users":
                if method == "GET": return self.users_list()
                if method == "POST": return self.user_save(self._body())

            m_id = re.match(r"^/api/(stores|partners|shipments|payments|investments|payouts|investors|users)/(\d+)(/[a-z]+)?$", path)
            sub = m_id.group(3) if m_id else None
            if m_id and m_id.group(1) == "users":
                uid = int(m_id.group(2))
                if method == "PATCH": return self.user_save(self._body(), uid)
                if method == "DELETE": return self.user_delete(uid)
            if path == "/api/stores":
                if method == "GET": return self.stores_list(q)
                if method == "POST": return self.store_save(self._body())
            if m_id and m_id.group(1) == "stores":
                if method == "PATCH": return self.store_save(self._body(), int(m_id.group(2)))
                if method == "DELETE": return self.store_delete(int(m_id.group(2)))
            if path == "/api/partners":
                if method == "GET": return self.partners_list(q)
                if method == "POST": return self.partner_save(self._body())
            if m_id and m_id.group(1) == "partners":
                pid = int(m_id.group(2))
                if method == "GET": return self.partner_one(pid)
                if method == "PATCH": return self.partner_save(self._body(), pid)
                if method == "DELETE": return self.partner_delete(pid)
            if path == "/api/shipments":
                if method == "GET": return self.shipments_list(q)
                if method == "POST": return self.shipment_save(self._body())
            if m_id and m_id.group(1) == "shipments":
                sid = int(m_id.group(2))
                if sub == "/split" and method == "POST": return self.shipment_split(sid, self._body())
                if method == "GET": return self.shipment_one(sid)
                if method == "PATCH": return self.shipment_save(self._body(), sid)
                if method == "DELETE": return self.shipment_delete(sid)
            if path == "/api/payments":
                if method == "GET": return self.payments_list(q)
                if method == "POST": return self.payment_save(self._body())
            if m_id and m_id.group(1) == "payments":
                yid = int(m_id.group(2))
                if method == "PATCH": return self.payment_save(self._body(), yid)
                if method == "DELETE": return self.payment_delete(yid)
            if path == "/api/investments":
                if method == "GET": return self.investments_list(q)
                if method == "POST": return self.investment_save(self._body())
            if m_id and m_id.group(1) == "investments":
                vid = int(m_id.group(2))
                if method == "PATCH": return self.investment_save(self._body(), vid)
                if method == "DELETE": return self.investment_delete(vid)
            if path == "/api/payouts":
                if method == "GET": return self.payouts_list(q)
                if method == "POST": return self.payout_save(self._body())
            if m_id and m_id.group(1) == "payouts":
                oid = int(m_id.group(2))
                if method == "PATCH": return self.payout_save(self._body(), oid)
                if method == "DELETE": return self.payout_delete(oid)
            if path == "/api/investors" and method == "GET": return self.investors_list()
            if m_id and m_id.group(1) == "investors":
                iid = int(m_id.group(2))
                if sub == "/report" and method == "GET": return self.investor_report(iid)
                if method == "GET": return self.investor_one(iid)
            if path == "/api/summary" and method == "GET": return self.summary(q)
            if path == "/api/export.csv" and method == "GET": return self.export_csv(q)
            if path == "/api/payments.csv" and method == "GET": return self.export_payments_csv(q)
            if path == "/api/backup" and method == "POST":
                dst = backup_db()
                return self._send(200, {"ok": True, "file": os.path.basename(dst) if dst else "в облаке копии хранит Supabase — скачайте .db"})
            if path == "/api/backup.db" and method == "GET":
                return self._send(200, export_sqlite_bytes(), "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename=china-uchet-%s.db" % today()})
            if path == "/api/restore" and method == "POST": return self.restore(self._body())
            return self._err(404, "Нет такого адреса")
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._err(500, "Ошибка сервера: %s" % e)

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
            # start_url намеренно не указан: тогда иконка на домашнем экране запоминает тот адрес,
            # с которого её добавили — вместе с ключом входа, и приложение открывается сразу.
            data = json.dumps({"name": "Китай · учёт", "short_name": "Китай", "display": "standalone",
                               "background_color": "#06070C", "theme_color": "#06070C",
                               "icons": [{"src": "/static/icon.png", "sizes": "180x180", "type": "image/png"}]}, ensure_ascii=False)
            return self._send(200, data.encode(), types["webmanifest"])
        fp = os.path.join(WEB, name)
        if ext not in types or not os.path.isfile(fp): return self._err(404, "Нет файла")
        self._send(200, open(fp, "rb").read(), types[ext])

    # -- вход и пользователи
    def api_login(self):
        b = self._body()
        u = check_password((b.get("login") or "").strip().lower(), b.get("password") or "")
        if not u: time.sleep(0.6); return self._err(403, "Неверный логин или пароль")
        tok = make_token(u["login"])
        self._send(200, {"ok": True, "user": {"id": u["id"], "login": u["login"], "role": u["role"], "name": u["name"],
                                              "version": VERSION, "auth": AUTH, "cloud": IS_PG, **self._link(u)}},
                   headers={"Set-Cookie": self._cookie(tok, 30*86400)})

    def password_change(self, b):
        old, new = b.get("old") or "", b.get("new") or ""
        if len(new) < 6: return self._err(400, "Новый пароль — не короче 6 символов")
        if not check_password(self.user["login"], old): return self._err(403, "Старый пароль неверный")
        salt = secrets.token_hex(16)
        c = db(); c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (pw_hash(new, salt), salt, self.user["id"]))
        commit(c); c.close(); TOK_CACHE.clear(); self._send(200, {"ok": True})

    def users_list(self):
        c = db(); rows = [dict(r) for r in c.execute("SELECT id,login,role,name,created_at FROM users ORDER BY id")]; c.close()
        self._send(200, rows)

    def user_save(self, b, uid=None):
        c = db()
        if uid:
            u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not u: c.close(); return self._err(404, "Пользователь не найден")
            if b.get("name") is not None: c.execute("UPDATE users SET name=? WHERE id=?", ((b.get("name") or "").strip(), uid))
            if b.get("password"):
                if len(b["password"]) < 6: c.close(); return self._err(400, "Пароль — не короче 6 символов")
                salt = secrets.token_hex(16)
                c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (pw_hash(b["password"], salt), salt, uid))
            commit(c); c.close(); return self._send(200, {"ok": True, "id": uid})
        login = (b.get("login") or "").strip().lower()
        if not re.match(r"^[a-z0-9_.-]{2,32}$", login): c.close(); return self._err(400, "Логин — латиница, цифры, точка, дефис, 2–32 символа")
        if c.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone(): c.close(); return self._err(400, "Такой логин уже есть")
        pw = b.get("password") or ""
        if len(pw) < 6: c.close(); return self._err(400, "Пароль — не короче 6 символов")
        role = b.get("role") or "helper"
        if role not in ("owner", "helper"): c.close(); return self._err(400, "Неверная роль")
        salt = secrets.token_hex(16)
        uid = c.execute("INSERT INTO users(login,pw_hash,salt,role,name,created_at) VALUES(?,?,?,?,?,?)",
                        (login, pw_hash(pw, salt), salt, role, (b.get("name") or "").strip() or login, now())).lastrowid
        commit(c); c.close(); self._send(200, {"ok": True, "id": uid})

    def user_delete(self, uid):
        if uid == self.user["id"]: return self._err(400, "Нельзя удалить самого себя")
        c = db()
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u: c.close(); return self._err(404, "Пользователь не найден")
        if u["role"] == "owner" and c.execute("SELECT COUNT(*) n FROM users WHERE role='owner'").fetchone()["n"] <= 1:
            c.close(); return self._err(400, "Должен остаться хотя бы один владелец")
        c.execute("DELETE FROM users WHERE id=?", (uid,)); commit(c); c.close(); TOK_CACHE.clear(); self._send(200, {"ok": True})

    # -- настройки
    def settings_get(self):
        c = db(); s = get_settings(c); c.close(); self._send(200, s)

    def settings_save(self, b):
        c = db()
        if "currency" in b and b["currency"] in ("USD", "CNY", "KGS"): set_setting(c, "currency", b["currency"])
        if "rate" in b:
            try: v = str(float(b["rate"])) if b["rate"] not in (None, "") else ""
            except Exception: v = ""
            set_setting(c, "rate", v)
        commit(c); s = get_settings(c); c.close(); self._send(200, s)

    def restore(self, b):
        try: raw = base64.b64decode(b.get("db_b64") or "")
        except Exception: raw = b""
        if raw[:16] != b"SQLite format 3\x00": return self._err(400, "Нужен файл базы .db из «Китай · учёт»")
        tmp = os.path.join(ROOT, "restore-%s.db" % secrets.token_hex(4))
        open(tmp, "wb").write(raw)
        try: counts = import_sqlite_file(tmp)
        except ValueError as e: os.remove(tmp); return self._err(400, str(e))
        except Exception as e: os.remove(tmp); return self._err(500, "Не удалось загрузить базу: %s" % e)
        os.remove(tmp)
        self._send(200, {"ok": True, "counts": counts})

    # -- магазины
    def stores_list(self, q):
        c = db(); sn = get_snap(c)
        rows = sorted((dict(r) for r in sn.stores.values()), key=lambda r: (-r["active"], str(r["number"])))
        for r in rows:
            sh, it, tot, tr = set(), 0, 0.0, 0.0
            for sid, items in sn.items.items():
                s = sn.ships.get(sid)
                if not s or s["deleted"]: continue
                for i in items:
                    if i["store_id"] != r["id"]: continue
                    if s["status"] != "cancelled": sh.add(sid); it += 1; tot += i["amount"] or 0
                    if s["status"] == "shipping": tr += i["amount"] or 0
            r.update(shipments=len(sh), items=it, total=r2(tot), transit=r2(tr))
            if self.helper: r.pop("total", None); r.pop("transit", None)
        c.close(); self._send(200, rows)

    def store_save(self, b, sid=None):
        if not (b.get("number") or "").strip(): return self._err(400, "Не указан номер магазина")
        c = db()
        if sid:
            c.execute("UPDATE stores SET number=?, name=?, note=?, active=? WHERE id=?",
                      (b["number"].strip(), b.get("name") or "", b.get("note") or "", 1 if b.get("active",1) else 0, sid))
        else:
            sid = c.execute("INSERT INTO stores(number,name,note,active) VALUES(?,?,?,1)",
                            (b["number"].strip(), b.get("name") or "", b.get("note") or "")).lastrowid
        commit(c); c.close(); self._send(200, {"ok": True, "id": sid})

    def store_delete(self, sid):
        c = db()
        used = c.execute("SELECT 1 FROM shipment_items WHERE store_id=? LIMIT 1", (sid,)).fetchone()
        if used:
            c.execute("UPDATE stores SET active=0 WHERE id=?", (sid,)); commit(c); c.close()
            return self._send(200, {"ok": True, "hidden": True,
                                    "msg": "Магазин участвует в партиях — скрыт, история сохранена"})
        c.execute("DELETE FROM stores WHERE id=?", (sid,)); commit(c); c.close()
        self._send(200, {"ok": True})

    # -- контрагенты
    def partners_list(self, q):
        c = db(); sn = get_snap(c)
        rows = sorted((dict(r) for r in sn.partners.values()), key=lambda r: (-r["active"], (r["name"] or "").lower()))
        for r in rows:
            if self.helper:
                r["shipments"] = len([s for s in sn.ships.values() if s["supplier_id"] == r["id"] and not s["deleted"]])
                continue
            r.update(supplier_finance(c, r["id"]))
            if r["is_investor"]:
                ic = investor_calc(c, r["id"], with_lists=False)
                r.update(inv_invested=ic["invested"], inv_due=ic["due"], inv_accrued=ic["accrued"])
        c.close(); self._send(200, rows)

    def partner_one(self, pid):
        c = db()
        p = c.execute("SELECT * FROM partners WHERE id=?", (pid,)).fetchone()
        if not p: c.close(); return self._err(404, "Контрагент не найден")
        sn = get_snap(c)
        ships = [pack_shipment(c, s) for s in sorted((s for s in sn.ships.values() if s["supplier_id"] == pid and not s["deleted"]),
                                                     key=lambda s: (s["date"], s["id"]), reverse=True)]
        fin = supplier_finance(c, pid, ships)
        pays = sorted((sn.enrich_pay(p) for p in sn.pays_by_sup.get(pid, [])), key=lambda p: (p["date"], p["id"]), reverse=True)
        c.close()
        self._send(200, {**dict(p), **fin, "shipments": ships, "payments_list": pays})

    def partner_save(self, b, pid=None):
        if not (b.get("name") or "").strip(): return self._err(400, "Не указано название")
        vals = (b["name"].strip(), 1 if b.get("is_supplier",1) else 0, 1 if b.get("is_investor") else 0,
                b.get("contact") or "", b.get("city") or "", b.get("currency") or "USD",
                b.get("note") or "", 1 if b.get("active",1) else 0)
        c = db()
        if pid:
            c.execute("""UPDATE partners SET name=?,is_supplier=?,is_investor=?,contact=?,city=?,currency=?,note=?,active=?
                         WHERE id=?""", vals + (pid,))
        else:
            pid = c.execute("""INSERT INTO partners(name,is_supplier,is_investor,contact,city,currency,note,active,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""", vals + (now(),)).lastrowid
        commit(c); c.close(); self._send(200, {"ok": True, "id": pid})

    def partner_delete(self, pid):
        c = db()
        used = (c.execute("SELECT 1 FROM shipments WHERE supplier_id=? AND deleted=0 LIMIT 1", (pid,)).fetchone()
                or c.execute("SELECT 1 FROM payments WHERE supplier_id=? LIMIT 1", (pid,)).fetchone()
                or c.execute("SELECT 1 FROM investments WHERE investor_id=? LIMIT 1", (pid,)).fetchone()
                or c.execute("SELECT 1 FROM investor_payouts WHERE investor_id=? LIMIT 1", (pid,)).fetchone())
        if used:
            c.execute("UPDATE partners SET active=0 WHERE id=?", (pid,)); commit(c); c.close()
            return self._send(200, {"ok": True, "hidden": True,
                                    "msg": "У контрагента есть партии, платежи или вложения — скрыт, история сохранена"})
        c.execute("DELETE FROM partners WHERE id=?", (pid,)); commit(c); c.close()
        self._send(200, {"ok": True})

    # -- партии
    def _ship_where(self, q):
        w, args = ["p.deleted=0"], []
        if q.get("status"): w.append("p.status=?"); args.append(q["status"][0])
        if q.get("supplier"): w.append("p.supplier_id=?"); args.append(q["supplier"][0])
        if q.get("from"): w.append("p.date>=?"); args.append(q["from"][0])
        if q.get("to"): w.append("p.date<=?"); args.append(q["to"][0])
        if q.get("store"):
            w.append("EXISTS(SELECT 1 FROM shipment_items x WHERE x.shipment_id=p.id AND x.store_id=?)")
            args.append(q["store"][0])
        if q.get("q"):
            like = "%" + q["q"][0].lower() + "%"
            w.append("""(plower(COALESCE(p.track,'')) LIKE ? OR plower(COALESCE(p.note,'')) LIKE ?
                     OR EXISTS(SELECT 1 FROM shipment_items x WHERE x.shipment_id=p.id AND plower(x.product) LIKE ?)
                     OR EXISTS(SELECT 1 FROM partners pa WHERE pa.id=p.supplier_id AND plower(pa.name) LIKE ?))""")
            args += [like, like, like, like]
        return " AND ".join(w), args

    SORTS = {"date_desc": (lambda s: (s["date"], s["id"]), True), "date_asc": (lambda s: (s["date"], s["id"]), False),
             "amount_desc": (lambda s: s.get("amount", 0), True), "balance_desc": (lambda s: s.get("balance", 0), True),
             "supplier": (lambda s: (s["supplier_name"].lower(), s["date"]), False)}

    def shipments_list(self, q):
        c = db()
        out = [pack_shipment(c, r) for r in ship_filter(get_snap(c), q)]
        key, rev = self.SORTS.get((q.get("sort") or ["date_desc"])[0], self.SORTS["date_desc"])
        out.sort(key=key, reverse=rev)
        live = [s for s in out if s["status"] != "cancelled"]
        tot = {"count": len(out), "items": sum(len(s["items"]) for s in out)}
        if not self.helper:
            tot.update(amount=r2(sum(s["amount"] for s in live)), paid=r2(sum(s["paid"] for s in live)),
                       profit=r2(sum(s["profit"] or 0 for s in live if s["profit"] is not None)),
                       closed=len([s for s in live if s["profit"] is not None]))
            tot["balance"] = r2(tot["amount"] - tot["paid"])
        else:
            out = [strip_money(s) for s in out]
        c.close(); self._send(200, {"rows": out, "totals": tot})

    def shipment_one(self, sid):
        c = db(); r = get_snap(c).ships.get(sid)
        if not r or r["deleted"]: c.close(); return self._err(404, "Партия не найдена")
        out = pack_shipment(c, r); c.close()
        self._send(200, strip_money(out) if self.helper else out)

    def shipment_save(self, b, sid=None):
        c = db()
        old = None
        if sid:
            old = c.execute("SELECT * FROM shipments WHERE id=? AND deleted=0", (sid,)).fetchone()
            if not old: c.close(); return self._err(404, "Партия не найдена")
        helper = self.helper
        if helper:
            for k in ("prepaid", "rate", "profit", "closed_at", "currency"): b.pop(k, None)
        # частичное обновление (смена статуса, прибыль и т.п.) — без items
        partial = sid and "items" not in b
        if not partial:
            errs = validate_shipment({**(dict(old) if old else {}), **b}, c, helper)
            if errs: c.close(); return self._err(400, "; ".join(errs))
        if "profit" in b:
            if b["profit"] in (None, ""): b["profit"] = None; b["closed_at"] = None
            else:
                try: b["profit"] = float(b["profit"])
                except Exception: c.close(); return self._err(400, "Прибыль должна быть числом")
                if not b.get("closed_at") and not (old and old["closed_at"]): b["closed_at"] = today()
        b = apply_status_dates(b, old)
        fields = ["date","supplier_id","currency","rate","prepaid","status","sent_date",
                  "arrived_date","eta_date","track","default_store_id","note","profit","closed_at"]
        if sid:
            sets, args = [], []
            for f in fields:
                if f in b: sets.append("%s=?" % f); args.append(b[f])
            sets.append("updated_at=?"); args.append(now()); args.append(sid)
            c.execute("UPDATE shipments SET %s WHERE id=?" % ",".join(sets), args)
        else:
            sid = c.execute("""INSERT INTO shipments(date,supplier_id,currency,rate,prepaid,status,sent_date,
                               arrived_date,eta_date,track,default_store_id,note,profit,closed_at,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (b.get("date"), b.get("supplier_id"), b.get("currency") or "USD", b.get("rate"),
                             b.get("prepaid") or 0, b.get("status") or "new", b.get("sent_date"),
                             b.get("arrived_date"), b.get("eta_date"), b.get("track") or "",
                             b.get("default_store_id"), b.get("note") or "", b.get("profit"), b.get("closed_at"), now(), now())).lastrowid
        if "items" in b:
            old_items = {i["id"]: dict(i) for i in c.execute("SELECT * FROM shipment_items WHERE shipment_id=?", (sid,))}
            c.execute("DELETE FROM shipment_items WHERE shipment_id=?", (sid,))
            for i in b["items"]:
                amount, price = i.get("amount"), i.get("unit_price")
                if helper:   # помощник не трогает деньги: цены берём из прежней строки, новые — без цены
                    try: prev = old_items.get(int(i.get("id") or 0))
                    except Exception: prev = None
                    price = prev["unit_price"] if prev else None
                    amount = prev["amount"] if prev else 0
                if amount in (None, "") and i.get("qty") and price:
                    amount = round(float(i["qty"]) * float(price), 2)
                c.execute("""INSERT INTO shipment_items(shipment_id,store_id,product,qty,unit,unit_price,amount,note)
                             VALUES(?,?,?,?,?,?,?,?)""",
                          (sid, i.get("store_id"), (i.get("product") or "").strip(), i.get("qty"),
                           i.get("unit") or "шт", price, float(amount or 0), i.get("note") or ""))
        commit(c)
        out = pack_shipment(c, c.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone())
        c.close(); self._send(200, strip_money(out) if helper else out)

    def shipment_delete(self, sid):
        c = db()
        c.execute("UPDATE shipments SET deleted=1, updated_at=? WHERE id=?", (now(), sid))
        commit(c); c.close(); self._send(200, {"ok": True})

    def shipment_split(self, sid, b):
        """Разделить партию: отмеченные товары уходят в новую партию с тем же поставщиком и датой."""
        c = db()
        old = c.execute("SELECT * FROM shipments WHERE id=? AND deleted=0", (sid,)).fetchone()
        if not old: c.close(); return self._err(404, "Партия не найдена")
        try: ids = {int(x) for x in (b.get("item_ids") or [])}
        except Exception: ids = set()
        items = [dict(r) for r in c.execute("SELECT * FROM shipment_items WHERE shipment_id=?", (sid,))]
        move = [i for i in items if i["id"] in ids]; stay = [i for i in items if i["id"] not in ids]
        if not move: c.close(); return self._err(400, "Не отмечен ни один товар для переноса")
        if not stay: c.close(); return self._err(400, "Нельзя перенести все товары — тогда это та же партия")
        status = b.get("status") or old["status"]
        if status not in VALID_STATUS: c.close(); return self._err(400, "Неверный статус новой партии")
        total = sum(i["amount"] or 0 for i in items); msum = sum(i["amount"] or 0 for i in move)
        pays = payments_of_shipment(c, sid)
        prepaid_new, prepaid_old = 0.0, float(old["prepaid"] or 0)
        if not pays:
            if b.get("prepaid_new") not in (None, "") and not self.helper:
                try: prepaid_new = float(b["prepaid_new"])
                except Exception: c.close(); return self._err(400, "Аванс новой партии должен быть числом")
            else:
                prepaid_new = round(prepaid_old * msum / total, 2) if total else 0
            prepaid_new = max(0.0, min(prepaid_new, prepaid_old))
            prepaid_old = r2(prepaid_old - prepaid_new)
        nb = {"status": status, "sent_date": old["sent_date"] if status in ("shipping", "arrived") else None,
              "arrived_date": old["arrived_date"] if status == "arrived" else None}
        nb = apply_status_dates(nb)
        new_id = c.execute("""INSERT INTO shipments(date,supplier_id,currency,rate,prepaid,status,sent_date,arrived_date,eta_date,
                              track,default_store_id,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (old["date"], old["supplier_id"], old["currency"], old["rate"], r2(prepaid_new), status,
                            nb.get("sent_date"), nb.get("arrived_date"), old["eta_date"] if status == "shipping" else None,
                            old["track"] or "", old["default_store_id"],
                            ((old["note"] or "") + " · " if old["note"] else "") + "выделена из партии от %s" % fmt_date(old["date"]),
                            now(), now())).lastrowid
        c.execute("UPDATE shipment_items SET shipment_id=? WHERE id IN (%s)" % ",".join("?" * len(move)),
                  [new_id] + [i["id"] for i in move])
        if not pays:
            c.execute("UPDATE shipments SET prepaid=?, updated_at=? WHERE id=?", (prepaid_old, now(), sid))
        elif not self.helper:
            try: pids = [int(x) for x in (b.get("payment_ids") or [])]
            except Exception: pids = []
            if pids:
                c.execute("UPDATE payments SET shipment_id=? WHERE shipment_id=? AND id IN (%s)" % ",".join("?" * len(pids)),
                          [new_id, sid] + pids)
        c.execute("UPDATE shipments SET updated_at=? WHERE id=?", (now(), sid))
        commit(c)
        out = {"ok": True, "old": pack_shipment(c, c.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()),
               "new": pack_shipment(c, c.execute("SELECT * FROM shipments WHERE id=?", (new_id,)).fetchone())}
        if self.helper: out["old"], out["new"] = strip_money(out["old"]), strip_money(out["new"])
        c.close(); self._send(200, out)

    # -- платежи (этап 2)
    def _pay_where(self, q):
        w, args = ["1=1"], []
        if q.get("supplier"): w.append("y.supplier_id=?"); args.append(q["supplier"][0])
        if q.get("shipment"): w.append("y.shipment_id=?"); args.append(q["shipment"][0])
        if q.get("kind"): w.append("y.kind=?"); args.append(q["kind"][0])
        if q.get("from"): w.append("y.date>=?"); args.append(q["from"][0])
        if q.get("to"): w.append("y.date<=?"); args.append(q["to"][0])
        if q.get("q"):
            like = "%" + q["q"][0].lower() + "%"
            w.append("""(plower(COALESCE(y.note,'')) LIKE ? OR plower(COALESCE(y.method,'')) LIKE ?
                         OR plower(pa.name) LIKE ?)""")
            args += [like, like, like]
        return " AND ".join(w), args

    PAY_SQL = """SELECT y.*, pa.name supplier_name, s.date ship_date, s.status ship_status, s.deleted ship_deleted,
                        (SELECT COALESCE(SUM(amount),0) FROM shipment_items WHERE shipment_id=s.id) ship_amount
                 FROM payments y JOIN partners pa ON pa.id=y.supplier_id
                 LEFT JOIN shipments s ON s.id=y.shipment_id"""

    def payments_list(self, q):
        c = db()
        rows = pay_filter(get_snap(c), q)
        given = r2(sum(p["amount"] for p in rows if p["kind"] != "refund"))
        refund = r2(sum(p["amount"] for p in rows if p["kind"] == "refund"))
        by_kind = {k: r2(sum(p["amount"] for p in rows if p["kind"] == k)) for k in VALID_KIND}
        c.close()
        self._send(200, {"rows": rows, "totals": {"count": len(rows), "given": given, "refund": refund,
                                                  "net": r2(given - refund), "by_kind": by_kind}})

    def payment_save(self, b, yid=None):
        c = db()
        errs = []
        if not b.get("date"): errs.append("Не указана дата платежа")
        sup = b.get("supplier_id")
        if not sup: errs.append("Не выбран поставщик")
        elif not c.execute("SELECT 1 FROM partners WHERE id=?", (sup,)).fetchone(): errs.append("Такого поставщика нет")
        try: amount = float(b.get("amount") or 0)
        except Exception: amount = 0
        if amount <= 0: errs.append("Сумма должна быть больше нуля")
        kind = b.get("kind") or "prepay"
        if kind not in VALID_KIND: errs.append("Неверный тип платежа")
        ship = b.get("shipment_id") or None
        if ship:
            s = c.execute("SELECT supplier_id, deleted FROM shipments WHERE id=?", (ship,)).fetchone()
            if not s or s["deleted"]: errs.append("Партия не найдена")
            elif str(s["supplier_id"]) != str(sup): errs.append("Партия принадлежит другому поставщику")
        if errs: c.close(); return self._err(400, "; ".join(errs))
        vals = (b["date"], int(sup), int(ship) if ship else None, round(amount, 2), b.get("currency") or "USD",
                kind, (b.get("method") or "").strip(), (b.get("note") or "").strip())
        # первый платёж по партии с ручным авансом: переносим аванс в платежи, чтобы ничего не потерялось
        converted = 0
        if ship and not yid:
            s = c.execute("SELECT prepaid, date, currency FROM shipments WHERE id=?", (ship,)).fetchone()
            has = c.execute("SELECT 1 FROM payments WHERE shipment_id=? LIMIT 1", (ship,)).fetchone()
            if not has and float(s["prepaid"] or 0) > 0:
                converted = r2(s["prepaid"])
                c.execute("""INSERT INTO payments(date,supplier_id,shipment_id,amount,currency,kind,method,note,created_at)
                             VALUES(?,?,?,?,?,?,?,?,?)""",
                          (s["date"], int(sup), int(ship), converted, s["currency"] or "USD", "prepay", "",
                           "Аванс из карточки партии (перенесён автоматически)", now()))
                c.execute("UPDATE shipments SET prepaid=0, updated_at=? WHERE id=?", (now(), ship))
        if yid:
            if not c.execute("SELECT 1 FROM payments WHERE id=?", (yid,)).fetchone():
                c.close(); return self._err(404, "Платёж не найден")
            c.execute("""UPDATE payments SET date=?,supplier_id=?,shipment_id=?,amount=?,currency=?,kind=?,method=?,note=?
                         WHERE id=?""", vals + (yid,))
        else:
            yid = c.execute("""INSERT INTO payments(date,supplier_id,shipment_id,amount,currency,kind,method,note,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""", vals + (now(),)).lastrowid
        commit(c)
        row = dict(c.execute(self.PAY_SQL + " WHERE y.id=?", (yid,)).fetchone())
        row["converted"] = converted
        c.close(); self._send(200, row)

    def payment_delete(self, yid):
        c = db()
        if not c.execute("SELECT 1 FROM payments WHERE id=?", (yid,)).fetchone():
            c.close(); return self._err(404, "Платёж не найден")
        c.execute("DELETE FROM payments WHERE id=?", (yid,)); commit(c); c.close()
        self._send(200, {"ok": True})

    # -- инвесторы (этап 4)
    def investors_list(self):
        c = db(); sn = get_snap(c)
        ids = {p["id"] for p in sn.partners.values() if p["is_investor"]} | set(sn.invs_by_investor) | set(sn.payouts_by_investor)
        rows = sorted((dict(sn.partners[i]) for i in ids if i in sn.partners), key=lambda r: (-r["active"], (r["name"] or "").lower()))
        pt = sn.pool_total
        for r in rows:
            r.update(investor_calc(c, r["id"], with_lists=False))
            cnt = defaultdict(int)
            for v in sn.invs_by_investor.get(r["id"], []): cnt[(v["terms"], v["terms_value"])] += 1
            best = max(cnt.items(), key=lambda x: x[1])[0] if cnt else (None, None)
            r["terms"], r["terms_value"] = best
            mine = sum(v["amount"] or 0 for v in sn.invs_by_investor.get(r["id"], []) if not v["shipment_id"])
            r["pool_share"] = r2(mine / pt * 100) if pt else 0
        closed = [s for s in sn.ships.values() if not s["deleted"] and s["profit"] is not None]
        tot = {"invested": r2(sum(r["invested"] for r in rows)), "accrued": r2(sum(r["accrued"] for r in rows)),
               "paid_profit": r2(sum(r["paid_profit"] for r in rows)), "paid_principal": r2(sum(r["paid_principal"] for r in rows)),
               "due": r2(sum(r["due"] for r in rows)), "principal_out": r2(sum(r["principal_out"] for r in rows)),
               "pool_total": r2(pt), "closed_profit": r2(sum(s["profit"] for s in closed)), "closed_count": len(closed)}
        c.close(); self._send(200, {"rows": rows, "totals": tot})

    def investor_one(self, iid):
        c = db()
        p = c.execute("SELECT * FROM partners WHERE id=?", (iid,)).fetchone()
        if not p: c.close(); return self._err(404, "Инвестор не найден")
        out = {**dict(p), **investor_calc(c, iid), "pool_total": r2(pool_total(c))}
        c.close(); self._send(200, out)

    def investments_list(self, q):
        c = db(); sn = get_snap(c)
        inv, ship = (q.get("investor") or [""])[0], (q.get("shipment") or [""])[0]
        rows = [dict(v) for v in sn.invs if (not inv or str(v["investor_id"]) == str(inv)) and (not ship or str(v["shipment_id"]) == str(ship))]
        pt = sn.pool_total
        for v in rows: v["accrued"], v["accrual_note"] = accrual_of(c, v, pt)
        c.close(); self._send(200, {"rows": rows})

    def investment_save(self, b, vid=None):
        c = db(); errs = []
        if not b.get("date"): errs.append("Не указана дата")
        inv = b.get("investor_id")
        if not inv: errs.append("Не выбран инвестор")
        elif not c.execute("SELECT 1 FROM partners WHERE id=?", (inv,)).fetchone(): errs.append("Такого контрагента нет")
        try: amount = float(b.get("amount") or 0)
        except Exception: amount = 0
        if amount <= 0: errs.append("Сумма должна быть больше нуля")
        terms = b.get("terms") or "share"
        if terms not in VALID_TERMS: errs.append("Неверное условие")
        try: tv = float(b.get("terms_value") or 0)
        except Exception: tv = -1
        if tv < 0 or tv > 100: errs.append("Процент должен быть от 0 до 100")
        ship = b.get("shipment_id") or None
        if ship and not c.execute("SELECT 1 FROM shipments WHERE id=? AND deleted=0", (ship,)).fetchone(): errs.append("Партия не найдена")
        if errs: c.close(); return self._err(400, "; ".join(errs))
        vals = (b["date"], int(inv), int(ship) if ship else None, round(amount, 2), b.get("currency") or "USD", terms, tv,
                (b.get("note") or "").strip(), b.get("end_date") or None)
        if vid:
            if not c.execute("SELECT 1 FROM investments WHERE id=?", (vid,)).fetchone(): c.close(); return self._err(404, "Вложение не найдено")
            c.execute("""UPDATE investments SET date=?,investor_id=?,shipment_id=?,amount=?,currency=?,terms=?,terms_value=?,note=?,end_date=?
                         WHERE id=?""", vals + (vid,))
        else:
            vid = c.execute("""INSERT INTO investments(date,investor_id,shipment_id,amount,currency,terms,terms_value,note,end_date,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""", vals + (now(),)).lastrowid
            c.execute("UPDATE partners SET is_investor=1 WHERE id=?", (int(inv),))
        commit(c)
        row = dict(c.execute(INV_SQL + " WHERE v.id=?", (vid,)).fetchone())
        row["accrued"], row["accrual_note"] = accrual_of(c, row)
        c.close(); self._send(200, row)

    def investment_delete(self, vid):
        c = db()
        if not c.execute("SELECT 1 FROM investments WHERE id=?", (vid,)).fetchone(): c.close(); return self._err(404, "Вложение не найдено")
        c.execute("DELETE FROM investments WHERE id=?", (vid,)); commit(c); c.close(); self._send(200, {"ok": True})

    def payouts_list(self, q):
        c = db(); sn = get_snap(c); inv = (q.get("investor") or [""])[0]
        rows = [dict(o) for o in sn.payouts if not inv or str(o["investor_id"]) == str(inv)]
        c.close(); self._send(200, {"rows": rows})

    def payout_save(self, b, oid=None):
        c = db(); errs = []
        if not b.get("date"): errs.append("Не указана дата")
        inv = b.get("investor_id")
        if not inv: errs.append("Не выбран инвестор")
        elif not c.execute("SELECT 1 FROM partners WHERE id=?", (inv,)).fetchone(): errs.append("Такого контрагента нет")
        try: amount = float(b.get("amount") or 0)
        except Exception: amount = 0
        if amount <= 0: errs.append("Сумма должна быть больше нуля")
        kind = b.get("kind") or "profit"
        if kind not in VALID_PAYOUT: errs.append("Неверный тип выплаты")
        if errs: c.close(); return self._err(400, "; ".join(errs))
        vals = (b["date"], int(inv), round(amount, 2), b.get("currency") or "USD", kind, (b.get("note") or "").strip())
        if oid:
            if not c.execute("SELECT 1 FROM investor_payouts WHERE id=?", (oid,)).fetchone(): c.close(); return self._err(404, "Выплата не найдена")
            c.execute("UPDATE investor_payouts SET date=?,investor_id=?,amount=?,currency=?,kind=?,note=? WHERE id=?", vals + (oid,))
        else:
            oid = c.execute("INSERT INTO investor_payouts(date,investor_id,amount,currency,kind,note,created_at) VALUES(?,?,?,?,?,?,?)",
                            vals + (now(),)).lastrowid
        commit(c)
        row = dict(c.execute(PO_SQL + " WHERE o.id=?", (oid,)).fetchone())
        c.close(); self._send(200, row)

    def payout_delete(self, oid):
        c = db()
        if not c.execute("SELECT 1 FROM investor_payouts WHERE id=?", (oid,)).fetchone(): c.close(); return self._err(404, "Выплата не найдена")
        c.execute("DELETE FROM investor_payouts WHERE id=?", (oid,)); commit(c); c.close(); self._send(200, {"ok": True})

    def investor_report(self, iid):
        """Отчёт инвестору одной страницей — печать / сохранить в PDF из браузера."""
        c = db()
        p = c.execute("SELECT * FROM partners WHERE id=?", (iid,)).fetchone()
        if not p: c.close(); return self._err(404, "Инвестор не найден")
        d = investor_calc(c, iid); c.close()
        cur = p["currency"] or "USD"
        terms_ru = lambda v: ("%g%% от прибыли" % float(v["terms_value"] or 0)) if v["terms"] == "share" else ("%g%% в месяц" % float(v["terms_value"] or 0))
        target = lambda v: ("партия от %s · %s" % (fmt_date(v["ship_date"]), v["ship_supplier"] or "")) if v["shipment_id"] else "общий пул"
        inv_rows = "".join("<tr><td>%s</td><td>%s</td><td class=num>%s</td><td>%s</td><td class=num>%s</td><td class=note>%s</td></tr>" % (
            fmt_date(v["date"]), esc(target(v)), fmt_money(v["amount"], v["currency"]), terms_ru(v), fmt_money(v["accrued"], v["currency"]), esc(v["accrual_note"]))
            for v in d["investments"]) or "<tr><td colspan=6 class=note>Вложений нет</td></tr>"
        po_rows = "".join("<tr><td>%s</td><td>%s</td><td class=num>%s</td><td class=note>%s</td></tr>" % (
            fmt_date(o["date"]), "Доля прибыли" if o["kind"] == "profit" else "Возврат вложения", fmt_money(o["amount"], o["currency"]), esc(o["note"]))
            for o in d["payouts"]) or "<tr><td colspan=4 class=note>Выплат ещё не было</td></tr>"
        html = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Отчёт инвестору — %(name)s</title>
<style>
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,system-ui,sans-serif;color:#14171F;background:#fff;max-width:860px;margin:0 auto;padding:36px 28px}
h1{font-size:24px;letter-spacing:-.5px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px;color:#333}
.sub{color:#6B7280;margin-bottom:22px}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 6px}
.tile{border:1px solid #E3E6EC;border-radius:12px;padding:12px 14px}.tile span{display:block;font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.4px}
.tile b{display:block;font-size:20px;letter-spacing:-.5px;margin-top:4px}.tile.due b{color:#B45309}
table{width:100%%;border-collapse:collapse;margin-top:6px}th,td{padding:8px 10px;border-bottom:1px solid #E9ECF1;text-align:left;vertical-align:top}
th{font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.4px;font-weight:600}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}.note{color:#6B7280;font-size:12.5px}
.foot{margin-top:28px;color:#6B7280;font-size:12px;line-height:1.5}
.bar{display:flex;gap:10px;margin-bottom:18px}.bar button{font:inherit;padding:8px 14px;border-radius:9px;border:1px solid #D5D9E0;background:#F6F7F9;cursor:pointer}
@media print{.bar{display:none}body{padding:0}}
@media(max-width:640px){.tiles{grid-template-columns:1fr 1fr}}
</style></head><body>
<div class="bar"><button onclick="print()">Печать / сохранить в PDF</button><button onclick="history.back()">← Назад</button></div>
<h1>Отчёт инвестору: %(name)s</h1>
<div class="sub">по состоянию на %(today)s%(contact)s</div>
<div class="tiles">
<div class="tile"><span>Вложено</span><b>%(invested)s</b></div>
<div class="tile"><span>Начислено</span><b>%(accrued)s</b></div>
<div class="tile"><span>Выплачено долей</span><b>%(paid_profit)s</b></div>
<div class="tile due"><span>Остаток к выплате</span><b>%(due)s</b></div>
</div>
<div class="note">Тело вложения: возвращено %(paid_principal)s, остаётся у нас %(principal_out)s.</div>
<h2>Вложения</h2>
<table><tr><th>Дата</th><th>Куда</th><th class=num>Сумма</th><th>Условие</th><th class=num>Начислено</th><th>Как посчитано</th></tr>%(inv_rows)s</table>
<h2>Выплаты</h2>
<table><tr><th>Дата</th><th>Тип</th><th class=num>Сумма</th><th>Комментарий</th></tr>%(po_rows)s</table>
<div class="foot">Доля от прибыли начисляется после закрытия партии (прибыль вводится владельцем по факту продаж). Вложение в общий пул получает долю от прибыли всех закрытых партий без адресных вложений, пропорционально своей части пула. Фиксированный процент начисляется за каждый полный месяц с даты вложения.<br>Сформировано программой «Китай · учёт» %(ver)s.</div>
</body></html>""" % {
            "name": esc(p["name"]), "today": fmt_date(today()),
            "contact": (" · " + esc(p["contact"])) if p["contact"] else "",
            "invested": fmt_money(d["invested"], cur), "accrued": fmt_money(d["accrued"], cur),
            "paid_profit": fmt_money(d["paid_profit"], cur), "due": fmt_money(d["due"], cur),
            "paid_principal": fmt_money(d["paid_principal"], cur), "principal_out": fmt_money(d["principal_out"], cur),
            "inv_rows": inv_rows, "po_rows": po_rows, "ver": VERSION}
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    # -- сводка
    def summary(self, q):
        c = db(); sn = get_snap(c)
        rows = [pack_shipment(c, r) for r in sn.ships.values() if not r["deleted"]]
        live = [s for s in rows if s["status"] != "cancelled"]
        transit = [s for s in rows if s["status"] == "shipping"]
        frm, to = (q.get("from") or [""])[0], (q.get("to") or [""])[0]
        inp = lambda d: (not frm or (d or "") >= frm) and (not to or (d or "") <= to)
        live_p = [s for s in live if inp(s["date"])]; rows_p = [s for s in rows if inp(s["date"])]
        used = {s["supplier_id"] for s in sn.ships.values()}
        by_sup = {p["id"]: p["name"] for p in sn.partners.values() if p["is_supplier"] or p["id"] in used}
        fin = {}
        for pid in by_sup:
            fin[pid] = supplier_finance(c, pid, [s for s in rows if s["supplier_id"] == pid])
        pays = sn.pays
        ordered = r2(sum(s["amount"] for s in live_p))
        paid_p = r2(sum(signed(y) for y in pays if inp(y["date"]))
                    + sum(s["paid"] for s in live_p if s["pay_mode"] == "manual"))
        paid_all = r2(sum(f["paid"] for f in fin.values()))
        debts = sorted(((by_sup[p], f["debt"]) for p, f in fin.items() if f["debt"] > 0.004), key=lambda x: -x[1])
        overpaid = sorted(((by_sup[p], -f["debt"]) for p, f in fin.items() if f["debt"] < -0.004), key=lambda x: -x[1])
        tiles = {
            "ordered": ordered, "ordered_items": sum(len(s["items"]) for s in live_p), "ordered_count": len(live_p),
            "paid": paid_p if (frm or to) else paid_all, "balance": r2(ordered - paid_p),
            "debt_suppliers": len(debts), "debt_total": r2(sum(v for _, v in debts)),
            "transit": r2(sum(s["amount"] for s in transit)), "transit_count": len(transit),
            "transit_max_days": max([s["days_transit"] or 0 for s in transit], default=0),
            "profit": r2(sum(s["profit"] or 0 for s in live_p if s["profit"] is not None)),
            "closed_count": len([s for s in live_p if s["profit"] is not None]),
        }
        # серии по месяцам (7 последних) — для мини-графиков и столбиков
        keys = month_keys(7)
        sup_ids = {s["supplier_id"] for s in live} | {y["supplier_id"] for y in pays}
        series = {"ordered": [], "paid": [], "balance": [], "sent": []}
        months = []
        for ym in keys:
            o = r2(sum(s["amount"] for s in live if s["date"][:7] == ym))
            p = r2(sum(signed(y) for y in pays if (y["date"] or "")[:7] == ym)
                   + sum(s["paid"] for s in live if s["pay_mode"] == "manual" and s["date"][:7] == ym))
            snt = r2(sum(s["amount"] for s in live if (s["sent_date"] or "")[:7] == ym))
            # остаток к оплате — накопительный долг на конец месяца, по каждому поставщику отдельно
            bal = 0.0
            for pid in sup_ids:
                co = sum(s["amount"] for s in live if s["supplier_id"] == pid and s["date"][:7] <= ym)
                cp = (sum(signed(y) for y in pays if y["supplier_id"] == pid and (y["date"] or "")[:7] <= ym)
                      + sum(s["paid"] for s in live if s["supplier_id"] == pid and s["pay_mode"] == "manual" and s["date"][:7] <= ym))
                bal += max(0.0, co - cp)
            series["ordered"].append(o); series["paid"].append(p)
            series["balance"].append(r2(bal)); series["sent"].append(snt)
            months.append({"ym": ym, "total": o, "paid": p})
        by_status = {st: {"count": len([s for s in rows_p if s["status"] == st]),
                          "amount": r2(sum(s["amount"] for s in rows_p if s["status"] == st))} for st in VALID_STATUS}
        sup_p = {}
        for s in live_p: sup_p[s["supplier_id"]] = r2(sup_p.get(s["supplier_id"], 0) + s["amount"])
        top_sup = sorted(((by_sup.get(p, "?"), v, fin[p]["debt"] if p in fin else 0) for p, v in sup_p.items() if v > 0),
                         key=lambda x: -x[1])[:6]
        by_store = {}
        for s in live_p:
            for i in s["items"]:
                k = "№" + i["store_number"] + (" · " + i["store_name"] if i["store_name"] else "")
                by_store[k] = r2(by_store.get(k, 0) + (i["amount"] or 0))
        by_store = sorted(by_store.items(), key=lambda x: -x[1])
        recent = [sn.enrich_pay(p) for p in sorted(sn.pays, key=lambda p: (p["date"], p["id"]), reverse=True)[:6]]
        this_month = today()[:7]
        month_paid = r2(sum(signed(y) for y in pays if (y["date"] or "")[:7] == this_month))
        arriving = sorted(transit, key=lambda s: s["eta_date"] or s["sent_date"] or "9999")
        # инвесторы одной строкой + топ для правой колонки
        inv_rows = [p for p in sn.partners.values() if p["is_investor"] or sn.invs_by_investor.get(p["id"])]
        inv_top = []
        for r in inv_rows:
            ic = investor_calc(c, r["id"], with_lists=False)
            inv_top.append({"id": r["id"], "name": r["name"], **ic})
        inv_top.sort(key=lambda x: -x["due"])
        investors = {"count": len(inv_top), "invested": r2(sum(x["invested"] for x in inv_top)),
                     "accrued": r2(sum(x["accrued"] for x in inv_top)), "due": r2(sum(x["due"] for x in inv_top)),
                     "paid_profit": r2(sum(x["paid_profit"] for x in inv_top)), "top": inv_top[:4]}
        c.close()
        self._send(200, {"tiles": tiles, "series": series, "months": months, "by_status": by_status,
                         "top_suppliers": top_sup, "by_store": by_store, "recent_payments": recent,
                         "month_paid": month_paid, "payments_count": len(pays),
                         "debts": debts, "overpaid": overpaid, "investors": investors,
                         "period": {"from": frm, "to": to},
                         "arriving": [{"id": s["id"], "supplier": s["supplier_name"], "eta": s["eta_date"],
                                       "days": s["days_transit"], "amount": s["amount"], "sent": s["sent_date"]}
                                      for s in arriving]})

    # -- экспорт
    def export_csv(self, q):
        c = db()
        rows = [pack_shipment(c, r) for r in ship_filter(get_snap(c), q)]
        c.close()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        st_ru = {"new": "Не отправлен", "shipping": "В пути", "arrived": "Прибыл", "cancelled": "Отменён"}
        w.writerow(["Дата","Поставщик","Статус","Трек","Магазин","Товар","Кол-во","Ед.","Цена","Сумма",
                    "Валюта","Оплачено по партии","Остаток по партии","Сумма партии","Прибыль партии","Комментарий"])
        for s in rows:
            for i in s["items"]:
                w.writerow([s["date"], s["supplier_name"], st_ru.get(s["status"], s["status"]), s["track"] or "",
                            "№" + i["store_number"], i["product"], i["qty"] or "", i["unit"] or "",
                            i["unit_price"] or "", i["amount"], s["currency"], s["paid"], s["balance"],
                            s["amount"], s["profit"] if s["profit"] is not None else "", (i["note"] or s["note"] or "")])
        data = "﻿" + buf.getvalue()
        self._send(200, data.encode("utf-8"), "text/csv; charset=utf-8",
                   {"Content-Disposition": "attachment; filename=china-uchet.csv"})

    def export_payments_csv(self, q):
        c = db()
        rows = pay_filter(get_snap(c), q)
        c.close()
        buf = io.StringIO(); w = csv.writer(buf, delimiter=";")
        kind_ru = {"prepay": "Аванс", "final": "Доплата", "refund": "Возврат"}
        w.writerow(["Дата","Поставщик","Тип","Сумма","Валюта","Партия от","Сумма партии","Способ","Комментарий"])
        for p in rows:
            w.writerow([p["date"], p["supplier_name"], kind_ru.get(p["kind"], p["kind"]),
                        -p["amount"] if p["kind"] == "refund" else p["amount"], p["currency"],
                        p["ship_date"] or "", p["ship_amount"] if p["ship_date"] else "", p["method"] or "", p["note"] or ""])
        data = "﻿" + buf.getvalue()
        self._send(200, data.encode("utf-8"), "text/csv; charset=utf-8",
                   {"Content-Disposition": "attachment; filename=china-platezhi.csv"})

def main():
    global SECRET
    init_db()
    SECRET = get_secret()
    b = backup_db()
    if b: print("Резервная копия:", os.path.basename(b))
    icon = os.path.join(WEB, "icon.png")
    if not os.path.exists(icon):
        try: make_icon(icon)
        except Exception as e: print("Иконка не создана:", e)
    keepalive()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print("Китай · учёт %s работает: http://%s:%d · база: %s · вход: %s" % (
        VERSION, "localhost" if HOST == "127.0.0.1" else HOST, PORT, "Postgres/" + PG_SCHEMA if IS_PG else "SQLite",
        "по паролю" if AUTH else "не нужен"), flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
