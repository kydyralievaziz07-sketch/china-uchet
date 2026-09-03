#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Китай · учёт — программа учёта закупок товаров из Китая.
Этап 1: партии с вложенными товарами, справочники, статусы, авансы.
Этап 2: платежи поставщикам, автоматический аванс по платежам, долги, карточка поставщика.
Этап 3: фильтры по периоду / магазину / поставщику, сортировка, разделение партии, экспорт по фильтру.
Этап 4: инвесторы — вложения, доли, выплаты, прибыль по партии, отчёт инвестору.
Этап 5 (локальная часть): настройки, выгрузка базы, иконка на телефон; вход по паролю — только в облаке (KN_AUTH=1).
Стандартная библиотека Python, база SQLite. Локально: http://localhost:8902
Схема таблиц повторяет ТЗ (Postgres/Supabase) — миграция в облако механическая.
"""
import base64, csv, hashlib, hmac, io, json, os, re, shutil, sqlite3, secrets, struct, sys, time, zlib
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VERSION = "4.0.0"
ROOT = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(ROOT, "china.db")
WEB  = os.path.join(ROOT, "web")
PORT = int(os.environ.get("PORT", "8902"))
SECRET_FILE = os.path.join(ROOT, ".secret")
# Вход по логину и паролю нужен только облачной версии. Локально программа открывается сразу.
AUTH = os.environ.get("KN_AUTH", "0") == "1"

# ---------------------------------------------------------------- база
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

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    # LOWER() в SQLite не понимает кириллицу — своя функция
    c.create_function("plower", 1, lambda s: (s or "").lower())
    return c

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def today(): return date.today().isoformat()

def migrate(c):
    """Добавляем колонки, которых нет в старых базах (без потери данных)."""
    def cols(t): return [r["name"] for r in c.execute("PRAGMA table_info(%s)" % t)]
    if "created_at" not in cols("payments"): c.execute("ALTER TABLE payments ADD COLUMN created_at TEXT")
    if "end_date" not in cols("investments"): c.execute("ALTER TABLE investments ADD COLUMN end_date TEXT")
    if "created_at" not in cols("investments"): c.execute("ALTER TABLE investments ADD COLUMN created_at TEXT")
    if "created_at" not in cols("investor_payouts"): c.execute("ALTER TABLE investor_payouts ADD COLUMN created_at TEXT")

def init_db():
    c = db()
    c.executescript(SCHEMA)
    migrate(c)
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", b"china2026", bytes.fromhex(salt), 200_000).hex()
        c.execute("INSERT INTO users(login,pw_hash,salt,role,name,created_at) VALUES(?,?,?,?,?,?)",
                  ("admin", h, salt, "owner", "Владелец", now()))
    c.commit(); c.close()

def backup_db(keep=30):
    bdir = os.path.join(ROOT, "backups"); os.makedirs(bdir, exist_ok=True)
    if os.path.exists(DB):
        dst = os.path.join(bdir, "china-%s.db" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(DB, dst)
        old = sorted(f for f in os.listdir(bdir) if f.startswith("china-"))
        for f in old[:-keep]: os.remove(os.path.join(bdir, f))
        return dst
    return None

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

# ---------------------------------------------------------------- сессии
def get_secret():
    if not os.path.exists(SECRET_FILE):
        open(SECRET_FILE, "w").write(secrets.token_hex(32))
    return open(SECRET_FILE).read().strip()

SECRET = None
def sign(msg): return hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def make_token(login, days=30):
    exp = str(int(time.time()) + days*86400)
    raw = "%s|%s" % (login, exp)
    return base64.urlsafe_b64encode(("%s|%s" % (raw, sign(raw))).encode()).decode()

def check_token(tok):
    try:
        raw = base64.urlsafe_b64decode(tok.encode()).decode()
        login, exp, sig = raw.rsplit("|", 2)
        if not hmac.compare_digest(sig, sign("%s|%s" % (login, exp))): return None
        if int(exp) < time.time(): return None
        c = db(); u = c.execute("SELECT id,login,role,name FROM users WHERE login=?", (login,)).fetchone(); c.close()
        return dict(u) if u else None
    except Exception:
        return None

def check_password(login, password):
    c = db(); u = c.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone(); c.close()
    if not u: return None
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(u["salt"]), 200_000).hex()
    return dict(u) if hmac.compare_digest(h, u["pw_hash"]) else None

def owner_user():
    c = db(); u = c.execute("SELECT id,login,role,name FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone(); c.close()
    return dict(u) if u else None

# ---------------------------------------------------------------- бизнес-логика
VALID_STATUS = ("new", "shipping", "arrived", "cancelled")
VALID_KIND   = ("prepay", "final", "refund")
VALID_TERMS  = ("share", "fixed")
VALID_PAYOUT = ("profit", "principal")

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

def payments_of_shipment(c, sid):
    return [dict(r) for r in c.execute(
        "SELECT * FROM payments WHERE shipment_id=? ORDER BY date, id", (sid,))]

def months_between(a, b):
    """Полных месяцев от даты a до даты b."""
    if b < a: return 0
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day: m -= 1
    return max(0, m)

def pool_total(c):
    return float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM investments WHERE shipment_id IS NULL").fetchone()["s"])

def pool_profit_since(c, since):
    """Прибыль закрытых партий без адресных вложений, закрытых начиная с даты since."""
    r = c.execute("""SELECT COALESCE(SUM(profit),0) s FROM shipments s
                     WHERE s.deleted=0 AND s.profit IS NOT NULL AND COALESCE(s.closed_at, s.date) >= ?
                       AND NOT EXISTS(SELECT 1 FROM investments x WHERE x.shipment_id=s.id)""", (since,)).fetchone()
    return float(r["s"] or 0)

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
    invs = [dict(r) for r in c.execute(INV_SQL + " WHERE v.investor_id=? ORDER BY v.date DESC, v.id DESC", (iid,))]
    pt = pool_total(c)
    for v in invs:
        v["accrued"], v["accrual_note"] = accrual_of(c, v, pt)
    pays = [dict(r) for r in c.execute(PO_SQL + " WHERE o.investor_id=? ORDER BY o.date DESC, o.id DESC", (iid,))]
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
    out = []
    direct = [dict(r) for r in c.execute(INV_SQL + " WHERE v.shipment_id=?", (s["id"],))]
    for v in direct:
        acc, note = accrual_of(c, v)
        out.append({"name": v["investor_name"], "investor_id": v["investor_id"], "kind": "direct", "amount": v["amount"],
                    "terms": v["terms"], "terms_value": v["terms_value"], "accrued": acc, "note": note})
    if not direct:
        pt = pool_total(c)
        if pt:
            since = s.get("closed_at") or s["date"]
            for v in c.execute(INV_SQL + " WHERE v.shipment_id IS NULL AND v.terms='share' AND v.date<=? ORDER BY v.date", (since,)):
                v = dict(v); frac = float(v["amount"]) / pt
                out.append({"name": v["investor_name"], "investor_id": v["investor_id"], "kind": "pool", "amount": v["amount"],
                            "terms": "share", "terms_value": v["terms_value"], "accrued": r2(float(s["profit"]) * frac * float(v["terms_value"] or 0) / 100),
                            "note": "доля пула %.1f%% × %g%%" % (frac * 100, float(v["terms_value"] or 0))})
    return out

def pack_shipment(c, row):
    d = dict(row)
    items = [dict(i) for i in c.execute(
        """SELECT i.*, s.number store_number, s.name store_name
           FROM shipment_items i JOIN stores s ON s.id=i.store_id
           WHERE i.shipment_id=? ORDER BY i.id""", (d["id"],))]
    d["items"] = items
    d["amount"] = r2(sum(i["amount"] or 0 for i in items))
    # деньги: если по партии есть платежи — аванс считается по ним, иначе ручное поле
    pays = payments_of_shipment(c, d["id"])
    d["payments"] = pays
    d["paid_by_payments"] = r2(sum(signed(p) for p in pays))
    d["pay_mode"] = "auto" if pays else "manual"
    d["paid"] = d["paid_by_payments"] if pays else r2(d["prepaid"])
    d["balance"] = r2(d["amount"] - d["paid"])
    sup = c.execute("SELECT name, city FROM partners WHERE id=?", (d["supplier_id"],)).fetchone()
    d["supplier_name"] = sup["name"] if sup else "?"
    d["supplier_city"] = (sup["city"] or "") if sup else ""
    d["stores"] = sorted({i["store_number"] for i in items})
    if d["status"] == "shipping" and d["sent_date"]:
        d["days_transit"] = max(0, (date.today() - date.fromisoformat(d["sent_date"])).days)
    else:
        d["days_transit"] = None
    d["investors"] = [dict(r) for r in c.execute(
        "SELECT v.id, v.investor_id, p.name, v.amount, v.terms, v.terms_value FROM investments v JOIN partners p ON p.id=v.investor_id WHERE v.shipment_id=?", (d["id"],))]
    d["shares"] = shipment_shares(c, d)
    return d

def paid_for_debt(s):
    """Сколько денег реально ушло поставщику по партии (для долга).
    Платежи считаются всегда; ручной аванс — только по живым партиям."""
    if s["pay_mode"] == "auto": return s["paid_by_payments"]
    return s["paid"] if s["status"] != "cancelled" else 0.0

def unlinked_payments(c, pid):
    """Платежи поставщику без партии (или по удалённой партии)."""
    r = c.execute("""SELECT COALESCE(SUM(CASE WHEN y.kind='refund' THEN -y.amount ELSE y.amount END),0) s, COUNT(*) n
                     FROM payments y LEFT JOIN shipments s ON s.id=y.shipment_id
                     WHERE y.supplier_id=? AND (y.shipment_id IS NULL OR s.deleted=1)""", (pid,)).fetchone()
    return r2(r["s"]), r["n"]

def supplier_finance(c, pid, ships=None):
    if ships is None:
        ships = [pack_shipment(c, r) for r in
                 c.execute("SELECT * FROM shipments WHERE supplier_id=? AND deleted=0", (pid,))]
    live = [s for s in ships if s["status"] != "cancelled"]
    total = r2(sum(s["amount"] for s in live))
    linked = sum(paid_for_debt(s) for s in ships)
    unl, unl_n = unlinked_payments(c, pid)
    paid = r2(linked + unl)
    npay = c.execute("SELECT COUNT(*) n FROM payments WHERE supplier_id=?", (pid,)).fetchone()["n"]
    return {"shipments": len(ships), "total": total, "paid": paid, "debt": r2(total - paid),
            "transit": r2(sum(s["amount"] for s in ships if s["status"] == "shipping")),
            "unlinked": unl, "payments": npay}

def validate_shipment(body, c):
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
        if i.get("amount") in (None, "", 0): errs.append("Товар №%d: не указана сумма" % n)
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

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n: return {}
        try: return json.loads(self.rfile.read(n).decode())
        except Exception: return {}

    def _user(self):
        cookie = self.headers.get("Cookie") or ""
        m = re.search(r"kn_session=([^;]+)", cookie)
        u = check_token(m.group(1)) if m else None
        if u or AUTH: return u
        return owner_user()   # локальный режим: вход не нужен

    # -- маршрутизация
    def route(self, method):
        # http.server декодирует строку запроса как latin-1 — возвращаем UTF-8
        try: raw = self.path.encode("latin-1").decode("utf-8")
        except Exception: raw = self.path
        p = urlparse(raw)
        path, q = p.path.rstrip("/") or "/", parse_qs(p.query)
        try:
            if path == "/" and method == "GET": return self.page()
            if path.startswith("/static/") and method == "GET": return self.static(path)
            if path == "/api/login" and method == "POST": return self.api_login()
            user = self._user()
            if path.startswith("/api/") and not user: return self._err(401, "Нужен вход")
            if path == "/api/logout" and method == "POST":
                return self._send(200, {"ok": True}, headers={"Set-Cookie": "kn_session=; Max-Age=0; Path=/"})
            if path == "/api/me" and method == "GET": return self._send(200, {**user, "version": VERSION, "auth": AUTH})
            if path == "/api/settings":
                if method == "GET": return self.settings_get()
                if method == "PATCH": return self.settings_save(self._body())

            m_id = re.match(r"^/api/(stores|partners|shipments|payments|investments|payouts|investors)/(\d+)(/[a-z]+)?$", path)
            sub = m_id.group(3) if m_id else None
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
                dst = backup_db(); return self._send(200, {"ok": True, "file": os.path.basename(dst or "")})
            if path == "/api/backup.db" and method == "GET":
                backup_db()
                return self._send(200, open(DB, "rb").read(), "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename=china-uchet-%s.db" % today()})
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
            data = json.dumps({"name": "Китай · учёт", "short_name": "Китай", "start_url": "/", "display": "standalone",
                               "background_color": "#06070C", "theme_color": "#06070C",
                               "icons": [{"src": "/static/icon.png", "sizes": "180x180", "type": "image/png"}]}, ensure_ascii=False)
            return self._send(200, data.encode(), types["webmanifest"])
        fp = os.path.join(WEB, name)
        if ext not in types or not os.path.isfile(fp): return self._err(404, "Нет файла")
        self._send(200, open(fp, "rb").read(), types[ext])

    # -- вход (только облачный режим)
    def api_login(self):
        b = self._body()
        u = check_password((b.get("login") or "").strip().lower(), b.get("password") or "")
        if not u: return self._err(403, "Неверный логин или пароль")
        tok = make_token(u["login"])
        self._send(200, {"ok": True, "user": {"login": u["login"], "role": u["role"], "name": u["name"], "version": VERSION, "auth": AUTH}},
                   headers={"Set-Cookie": "kn_session=%s; Max-Age=%d; Path=/; HttpOnly; SameSite=Lax" % (tok, 30*86400)})

    # -- настройки
    def settings_get(self):
        c = db(); s = get_settings(c); c.close(); self._send(200, s)

    def settings_save(self, b):
        c = db()
        if "currency" in b and b["currency"] in ("USD", "CNY", "KGS"):
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('currency',?)", (b["currency"],))
        if "rate" in b:
            try: v = str(float(b["rate"])) if b["rate"] not in (None, "") else ""
            except Exception: v = ""
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('rate',?)", (v,))
        c.commit(); s = get_settings(c); c.close(); self._send(200, s)

    # -- магазины
    def stores_list(self, q):
        c = db()
        rows = [dict(r) for r in c.execute("SELECT * FROM stores ORDER BY active DESC, number")]
        for r in rows:
            st = c.execute("""SELECT COUNT(DISTINCT i.shipment_id) sh, COUNT(*) it, COALESCE(SUM(i.amount),0) s
                              FROM shipment_items i JOIN shipments p ON p.id=i.shipment_id
                              WHERE i.store_id=? AND p.deleted=0 AND p.status!='cancelled'""", (r["id"],)).fetchone()
            tr = c.execute("""SELECT COALESCE(SUM(i.amount),0) s FROM shipment_items i
                              JOIN shipments p ON p.id=i.shipment_id
                              WHERE i.store_id=? AND p.deleted=0 AND p.status='shipping'""", (r["id"],)).fetchone()
            r.update(shipments=st["sh"], items=st["it"], total=r2(st["s"]), transit=r2(tr["s"]))
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
        c.commit(); c.close(); self._send(200, {"ok": True, "id": sid})

    def store_delete(self, sid):
        c = db()
        used = c.execute("SELECT 1 FROM shipment_items WHERE store_id=? LIMIT 1", (sid,)).fetchone()
        if used:
            c.execute("UPDATE stores SET active=0 WHERE id=?", (sid,)); c.commit(); c.close()
            return self._send(200, {"ok": True, "hidden": True,
                                    "msg": "Магазин участвует в партиях — скрыт, история сохранена"})
        c.execute("DELETE FROM stores WHERE id=?", (sid,)); c.commit(); c.close()
        self._send(200, {"ok": True})

    # -- контрагенты
    def partners_list(self, q):
        c = db()
        rows = [dict(r) for r in c.execute("SELECT * FROM partners ORDER BY active DESC, name")]
        for r in rows:
            r.update(supplier_finance(c, r["id"]))
            if r["is_investor"]:
                ic = investor_calc(c, r["id"], with_lists=False)
                r.update(inv_invested=ic["invested"], inv_due=ic["due"], inv_accrued=ic["accrued"])
        c.close(); self._send(200, rows)

    def partner_one(self, pid):
        c = db()
        p = c.execute("SELECT * FROM partners WHERE id=?", (pid,)).fetchone()
        if not p: c.close(); return self._err(404, "Контрагент не найден")
        ships = [pack_shipment(c, r) for r in c.execute(
            "SELECT * FROM shipments WHERE supplier_id=? AND deleted=0 ORDER BY date DESC, id DESC", (pid,))]
        fin = supplier_finance(c, pid, ships)
        pays = [dict(r) for r in c.execute(
            """SELECT y.*, s.date ship_date, s.status ship_status, s.deleted ship_deleted,
                      (SELECT COALESCE(SUM(amount),0) FROM shipment_items WHERE shipment_id=s.id) ship_amount
               FROM payments y LEFT JOIN shipments s ON s.id=y.shipment_id
               WHERE y.supplier_id=? ORDER BY y.date DESC, y.id DESC""", (pid,))]
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
        c.commit(); c.close(); self._send(200, {"ok": True, "id": pid})

    def partner_delete(self, pid):
        c = db()
        used = (c.execute("SELECT 1 FROM shipments WHERE supplier_id=? AND deleted=0 LIMIT 1", (pid,)).fetchone()
                or c.execute("SELECT 1 FROM payments WHERE supplier_id=? LIMIT 1", (pid,)).fetchone()
                or c.execute("SELECT 1 FROM investments WHERE investor_id=? LIMIT 1", (pid,)).fetchone()
                or c.execute("SELECT 1 FROM investor_payouts WHERE investor_id=? LIMIT 1", (pid,)).fetchone())
        if used:
            c.execute("UPDATE partners SET active=0 WHERE id=?", (pid,)); c.commit(); c.close()
            return self._send(200, {"ok": True, "hidden": True,
                                    "msg": "У контрагента есть партии, платежи или вложения — скрыт, история сохранена"})
        c.execute("DELETE FROM partners WHERE id=?", (pid,)); c.commit(); c.close()
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
             "amount_desc": (lambda s: s["amount"], True), "balance_desc": (lambda s: s["balance"], True),
             "supplier": (lambda s: (s["supplier_name"].lower(), s["date"]), False)}

    def shipments_list(self, q):
        c = db()
        where, args = self._ship_where(q)
        rows = c.execute("SELECT p.* FROM shipments p WHERE %s ORDER BY p.date DESC, p.id DESC" % where, args).fetchall()
        out = [pack_shipment(c, r) for r in rows]
        key, rev = self.SORTS.get((q.get("sort") or ["date_desc"])[0], self.SORTS["date_desc"])
        out.sort(key=key, reverse=rev)
        live = [s for s in out if s["status"] != "cancelled"]
        tot = {"count": len(out),
               "items": sum(len(s["items"]) for s in out),
               "amount": r2(sum(s["amount"] for s in live)),
               "paid": r2(sum(s["paid"] for s in live)),
               "profit": r2(sum(s["profit"] or 0 for s in live if s["profit"] is not None)),
               "closed": len([s for s in live if s["profit"] is not None])}
        tot["balance"] = r2(tot["amount"] - tot["paid"])
        c.close(); self._send(200, {"rows": out, "totals": tot})

    def shipment_one(self, sid):
        c = db()
        r = c.execute("SELECT * FROM shipments WHERE id=? AND deleted=0", (sid,)).fetchone()
        if not r: c.close(); return self._err(404, "Партия не найдена")
        out = pack_shipment(c, r); c.close(); self._send(200, out)

    def shipment_save(self, b, sid=None):
        c = db()
        old = None
        if sid:
            old = c.execute("SELECT * FROM shipments WHERE id=? AND deleted=0", (sid,)).fetchone()
            if not old: c.close(); return self._err(404, "Партия не найдена")
        # частичное обновление (смена статуса, прибыль и т.п.) — без items
        partial = sid and "items" not in b
        if not partial:
            errs = validate_shipment({**(dict(old) if old else {}), **b}, c)
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
            c.execute("DELETE FROM shipment_items WHERE shipment_id=?", (sid,))
            for i in b["items"]:
                amount = i.get("amount")
                if amount in (None, "") and i.get("qty") and i.get("unit_price"):
                    amount = round(float(i["qty"]) * float(i["unit_price"]), 2)
                c.execute("""INSERT INTO shipment_items(shipment_id,store_id,product,qty,unit,unit_price,amount,note)
                             VALUES(?,?,?,?,?,?,?,?)""",
                          (sid, i.get("store_id"), (i.get("product") or "").strip(), i.get("qty"),
                           i.get("unit") or "шт", i.get("unit_price"), float(amount or 0), i.get("note") or ""))
        c.commit()
        out = pack_shipment(c, c.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone())
        c.close(); self._send(200, out)

    def shipment_delete(self, sid):
        c = db()
        c.execute("UPDATE shipments SET deleted=1, updated_at=? WHERE id=?", (now(), sid))
        c.commit(); c.close(); self._send(200, {"ok": True})

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
            if b.get("prepaid_new") not in (None, ""):
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
        else:
            try: pids = [int(x) for x in (b.get("payment_ids") or [])]
            except Exception: pids = []
            if pids:
                c.execute("UPDATE payments SET shipment_id=? WHERE shipment_id=? AND id IN (%s)" % ",".join("?" * len(pids)),
                          [new_id, sid] + pids)
        c.execute("UPDATE shipments SET updated_at=? WHERE id=?", (now(), sid))
        c.commit()
        out = {"ok": True, "old": pack_shipment(c, c.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()),
               "new": pack_shipment(c, c.execute("SELECT * FROM shipments WHERE id=?", (new_id,)).fetchone())}
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
        where, args = self._pay_where(q)
        rows = [dict(r) for r in c.execute(self.PAY_SQL + " WHERE %s ORDER BY y.date DESC, y.id DESC" % where, args)]
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
        c.commit()
        row = dict(c.execute(self.PAY_SQL + " WHERE y.id=?", (yid,)).fetchone())
        row["converted"] = converted
        c.close(); self._send(200, row)

    def payment_delete(self, yid):
        c = db()
        if not c.execute("SELECT 1 FROM payments WHERE id=?", (yid,)).fetchone():
            c.close(); return self._err(404, "Платёж не найден")
        c.execute("DELETE FROM payments WHERE id=?", (yid,)); c.commit(); c.close()
        self._send(200, {"ok": True})

    # -- инвесторы (этап 4)
    def investors_list(self):
        c = db()
        rows = [dict(r) for r in c.execute("""SELECT * FROM partners WHERE is_investor=1
                    OR id IN (SELECT investor_id FROM investments) OR id IN (SELECT investor_id FROM investor_payouts)
                    ORDER BY active DESC, name""")]
        pt = pool_total(c)
        for r in rows:
            r.update(investor_calc(c, r["id"], with_lists=False))
            terms = c.execute("""SELECT terms, terms_value, COUNT(*) n FROM investments WHERE investor_id=?
                                 GROUP BY terms, terms_value ORDER BY n DESC LIMIT 1""", (r["id"],)).fetchone()
            r["terms"] = terms["terms"] if terms else None
            r["terms_value"] = terms["terms_value"] if terms else None
            r["pool_share"] = r2(c.execute("SELECT COALESCE(SUM(amount),0) s FROM investments WHERE investor_id=? AND shipment_id IS NULL", (r["id"],)).fetchone()["s"] / pt * 100) if pt else 0
        tot = {"invested": r2(sum(r["invested"] for r in rows)), "accrued": r2(sum(r["accrued"] for r in rows)),
               "paid_profit": r2(sum(r["paid_profit"] for r in rows)), "paid_principal": r2(sum(r["paid_principal"] for r in rows)),
               "due": r2(sum(r["due"] for r in rows)), "principal_out": r2(sum(r["principal_out"] for r in rows)),
               "pool_total": r2(pt),
               "closed_profit": r2(c.execute("SELECT COALESCE(SUM(profit),0) s FROM shipments WHERE deleted=0 AND profit IS NOT NULL").fetchone()["s"]),
               "closed_count": c.execute("SELECT COUNT(*) n FROM shipments WHERE deleted=0 AND profit IS NOT NULL").fetchone()["n"]}
        c.close(); self._send(200, {"rows": rows, "totals": tot})

    def investor_one(self, iid):
        c = db()
        p = c.execute("SELECT * FROM partners WHERE id=?", (iid,)).fetchone()
        if not p: c.close(); return self._err(404, "Инвестор не найден")
        out = {**dict(p), **investor_calc(c, iid), "pool_total": r2(pool_total(c))}
        c.close(); self._send(200, out)

    def investments_list(self, q):
        c = db()
        w, args = ["1=1"], []
        if q.get("investor"): w.append("v.investor_id=?"); args.append(q["investor"][0])
        if q.get("shipment"): w.append("v.shipment_id=?"); args.append(q["shipment"][0])
        rows = [dict(r) for r in c.execute(INV_SQL + " WHERE %s ORDER BY v.date DESC, v.id DESC" % " AND ".join(w), args)]
        pt = pool_total(c)
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
        c.commit()
        row = dict(c.execute(INV_SQL + " WHERE v.id=?", (vid,)).fetchone())
        row["accrued"], row["accrual_note"] = accrual_of(c, row)
        c.close(); self._send(200, row)

    def investment_delete(self, vid):
        c = db()
        if not c.execute("SELECT 1 FROM investments WHERE id=?", (vid,)).fetchone(): c.close(); return self._err(404, "Вложение не найдено")
        c.execute("DELETE FROM investments WHERE id=?", (vid,)); c.commit(); c.close(); self._send(200, {"ok": True})

    def payouts_list(self, q):
        c = db()
        w, args = ["1=1"], []
        if q.get("investor"): w.append("o.investor_id=?"); args.append(q["investor"][0])
        rows = [dict(r) for r in c.execute(PO_SQL + " WHERE %s ORDER BY o.date DESC, o.id DESC" % " AND ".join(w), args)]
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
        c.commit()
        row = dict(c.execute(PO_SQL + " WHERE o.id=?", (oid,)).fetchone())
        c.close(); self._send(200, row)

    def payout_delete(self, oid):
        c = db()
        if not c.execute("SELECT 1 FROM investor_payouts WHERE id=?", (oid,)).fetchone(): c.close(); return self._err(404, "Выплата не найдена")
        c.execute("DELETE FROM investor_payouts WHERE id=?", (oid,)); c.commit(); c.close(); self._send(200, {"ok": True})

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
        c = db()
        rows = [pack_shipment(c, r) for r in c.execute("SELECT p.* FROM shipments p WHERE p.deleted=0")]
        live = [s for s in rows if s["status"] != "cancelled"]
        transit = [s for s in rows if s["status"] == "shipping"]
        frm, to = (q.get("from") or [""])[0], (q.get("to") or [""])[0]
        inp = lambda d: (not frm or (d or "") >= frm) and (not to or (d or "") <= to)
        live_p = [s for s in live if inp(s["date"])]; rows_p = [s for s in rows if inp(s["date"])]
        sups = c.execute("SELECT id, name FROM partners WHERE is_supplier=1 OR id IN (SELECT DISTINCT supplier_id FROM shipments)").fetchall()
        by_sup = {s["id"]: s["name"] for s in sups}
        fin = {}
        for pid in by_sup:
            fin[pid] = supplier_finance(c, pid, [s for s in rows if s["supplier_id"] == pid])
        pays = [dict(r) for r in c.execute("SELECT * FROM payments")]
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
        recent = [dict(r) for r in c.execute(self.PAY_SQL + " ORDER BY y.date DESC, y.id DESC LIMIT 6")]
        this_month = today()[:7]
        month_paid = r2(sum(signed(y) for y in pays if (y["date"] or "")[:7] == this_month))
        arriving = sorted(transit, key=lambda s: s["eta_date"] or s["sent_date"] or "9999")
        # инвесторы одной строкой + топ для правой колонки
        inv_rows = [dict(r) for r in c.execute("SELECT id, name FROM partners WHERE is_investor=1 OR id IN (SELECT investor_id FROM investments)")]
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
        where, args = self._ship_where(q)
        rows = [pack_shipment(c, r) for r in
                c.execute("SELECT p.* FROM shipments p WHERE %s ORDER BY p.date DESC" % where, args)]
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
        where, args = self._pay_where(q)
        rows = [dict(r) for r in c.execute(self.PAY_SQL + " WHERE %s ORDER BY y.date DESC, y.id DESC" % where, args)]
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
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print("Китай · учёт %s работает: http://localhost:%d%s" % (VERSION, PORT, "" if AUTH else " (вход не нужен)"))
    srv.serve_forever()

if __name__ == "__main__":
    main()
