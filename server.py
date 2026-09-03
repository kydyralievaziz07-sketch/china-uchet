#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Китай · учёт — программа учёта закупок товаров из Китая.
Этап 1: партии с вложенными товарами, справочники, статусы, авансы.
Этап 2: платежи поставщикам, автоматический аванс по платежам, долги,
        карточка поставщика, серии по месяцам для мини-графиков.
Стандартная библиотека Python, база SQLite. Локально: http://localhost:8902
Схема таблиц повторяет ТЗ (Postgres/Supabase) — миграция в облако механическая.
"""
import base64, csv, hashlib, hmac, io, json, os, re, shutil, sqlite3, secrets, sys, time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VERSION = "2.0.0"
ROOT = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(ROOT, "china.db")
WEB  = os.path.join(ROOT, "web")
PORT = int(os.environ.get("PORT", "8902"))
SECRET_FILE = os.path.join(ROOT, ".secret")

# ---------------------------------------------------------------- база
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'owner',           -- owner | helper
  name TEXT, created_at TEXT
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
  profit REAL, closed_at TEXT,
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
  shipment_id INTEGER REFERENCES shipments(id),
  amount REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  terms TEXT NOT NULL DEFAULT 'share', terms_value REAL,
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
    cols = [r["name"] for r in c.execute("PRAGMA table_info(payments)")]
    if "created_at" not in cols:
        c.execute("ALTER TABLE payments ADD COLUMN created_at TEXT")

def init_db():
    c = db()
    c.executescript(SCHEMA)
    migrate(c)
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", b"china2026", bytes.fromhex(salt), 200_000).hex()
        c.execute("INSERT INTO users(login,pw_hash,salt,role,name,created_at) VALUES(?,?,?,?,?,?)",
                  ("admin", h, salt, "owner", "Владелец", now()))
        print("Создан пользователь: admin / china2026")
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

# ---------------------------------------------------------------- бизнес-логика
VALID_STATUS = ("new", "shipping", "arrived", "cancelled")
VALID_KIND   = ("prepay", "final", "refund")

def signed(p):
    """Платёж со знаком: возврат уменьшает отданное."""
    a = float(p["amount"] or 0)
    return -a if p["kind"] == "refund" else a

def r2(x): return round(float(x or 0), 2)

def payments_of_shipment(c, sid):
    return [dict(r) for r in c.execute(
        "SELECT * FROM payments WHERE shipment_id=? ORDER BY date, id", (sid,))]

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
        return check_token(m.group(1)) if m else None

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
            if path == "/api/me" and method == "GET": return self._send(200, {**user, "version": VERSION})

            m_id = re.match(r"^/api/(stores|partners|shipments|payments)/(\d+)$", path)
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
            if path == "/api/summary" and method == "GET": return self.summary(q)
            if path == "/api/export.csv" and method == "GET": return self.export_csv(q)
            if path == "/api/payments.csv" and method == "GET": return self.export_payments_csv(q)
            if path == "/api/backup" and method == "POST":
                dst = backup_db(); return self._send(200, {"ok": True, "file": os.path.basename(dst or "")})
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
                 "svg": "image/svg+xml", "png": "image/png", "json": "application/json; charset=utf-8"}
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        fp = os.path.join(WEB, name)
        if ext not in types or not os.path.isfile(fp): return self._err(404, "Нет файла")
        self._send(200, open(fp, "rb").read(), types[ext])

    # -- вход
    def api_login(self):
        b = self._body()
        u = check_password((b.get("login") or "").strip().lower(), b.get("password") or "")
        if not u: return self._err(403, "Неверный логин или пароль")
        tok = make_token(u["login"])
        self._send(200, {"ok": True, "user": {"login": u["login"], "role": u["role"], "name": u["name"], "version": VERSION}},
                   headers={"Set-Cookie": "kn_session=%s; Max-Age=%d; Path=/; HttpOnly; SameSite=Lax" % (tok, 30*86400)})

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
        used = c.execute("SELECT 1 FROM shipments WHERE supplier_id=? AND deleted=0 LIMIT 1", (pid,)).fetchone() \
            or c.execute("SELECT 1 FROM payments WHERE supplier_id=? LIMIT 1", (pid,)).fetchone()
        if used:
            c.execute("UPDATE partners SET active=0 WHERE id=?", (pid,)); c.commit(); c.close()
            return self._send(200, {"ok": True, "hidden": True,
                                    "msg": "У контрагента есть партии или платежи — скрыт, история сохранена"})
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

    def shipments_list(self, q):
        c = db()
        where, args = self._ship_where(q)
        rows = c.execute("SELECT p.* FROM shipments p WHERE %s ORDER BY p.date DESC, p.id DESC" % where, args).fetchall()
        out = [pack_shipment(c, r) for r in rows]
        live = [s for s in out if s["status"] != "cancelled"]
        tot = {"count": len(out),
               "items": sum(len(s["items"]) for s in out),
               "amount": r2(sum(s["amount"] for s in live)),
               "paid": r2(sum(s["paid"] for s in live))}
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
        # частичное обновление (смена статуса и т.п.) — без items
        partial = sid and "items" not in b
        if not partial:
            errs = validate_shipment({**(dict(old) if old else {}), **b}, c)
            if errs: c.close(); return self._err(400, "; ".join(errs))
        b = apply_status_dates(b, old)
        fields = ["date","supplier_id","currency","rate","prepaid","status","sent_date",
                  "arrived_date","eta_date","track","default_store_id","note"]
        if sid:
            sets, args = [], []
            for f in fields:
                if f in b: sets.append("%s=?" % f); args.append(b[f])
            sets.append("updated_at=?"); args.append(now()); args.append(sid)
            c.execute("UPDATE shipments SET %s WHERE id=?" % ",".join(sets), args)
        else:
            sid = c.execute("""INSERT INTO shipments(date,supplier_id,currency,rate,prepaid,status,sent_date,
                               arrived_date,eta_date,track,default_store_id,note,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (b.get("date"), b.get("supplier_id"), b.get("currency") or "USD", b.get("rate"),
                             b.get("prepaid") or 0, b.get("status") or "new", b.get("sent_date"),
                             b.get("arrived_date"), b.get("eta_date"), b.get("track") or "",
                             b.get("default_store_id"), b.get("note") or "", now(), now())).lastrowid
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

    # -- сводка
    def summary(self, q):
        c = db()
        rows = [pack_shipment(c, r) for r in c.execute("SELECT p.* FROM shipments p WHERE p.deleted=0")]
        live = [s for s in rows if s["status"] != "cancelled"]
        transit = [s for s in rows if s["status"] == "shipping"]
        sups = c.execute("SELECT id, name FROM partners WHERE is_supplier=1 OR id IN (SELECT DISTINCT supplier_id FROM shipments)").fetchall()
        by_sup = {s["id"]: s["name"] for s in sups}
        fin = {}
        for pid in by_sup:
            fin[pid] = supplier_finance(c, pid, [s for s in rows if s["supplier_id"] == pid])
        ordered = r2(sum(s["amount"] for s in live))
        paid = r2(sum(f["paid"] for f in fin.values()))
        debts = sorted(((by_sup[p], f["debt"]) for p, f in fin.items() if f["debt"] > 0.004), key=lambda x: -x[1])
        overpaid = sorted(((by_sup[p], -f["debt"]) for p, f in fin.items() if f["debt"] < -0.004), key=lambda x: -x[1])
        tiles = {
            "ordered": ordered, "ordered_items": sum(len(s["items"]) for s in live), "ordered_count": len(live),
            "paid": paid, "balance": r2(ordered - paid),
            "debt_suppliers": len(debts), "debt_total": r2(sum(v for _, v in debts)),
            "transit": r2(sum(s["amount"] for s in transit)), "transit_count": len(transit),
            "transit_max_days": max([s["days_transit"] or 0 for s in transit], default=0),
        }
        # серии по месяцам (7 последних) — для мини-графиков и столбиков
        keys = month_keys(7)
        pays = [dict(r) for r in c.execute("SELECT * FROM payments")]
        series = {"ordered": [], "paid": [], "balance": [], "sent": []}
        months = []
        for ym in keys:
            o = r2(sum(s["amount"] for s in live if s["date"][:7] == ym))
            p = r2(sum(signed(y) for y in pays if (y["date"] or "")[:7] == ym)
                   + sum(s["paid"] for s in live if s["pay_mode"] == "manual" and s["date"][:7] == ym))
            snt = r2(sum(s["amount"] for s in live if (s["sent_date"] or "")[:7] == ym))
            # остаток к оплате — накопительно на конец месяца (как менялся долг), а не «за месяц»
            cum_o = sum(s["amount"] for s in live if s["date"][:7] <= ym)
            cum_p = (sum(signed(y) for y in pays if (y["date"] or "")[:7] <= ym)
                     + sum(s["paid"] for s in live if s["pay_mode"] == "manual" and s["date"][:7] <= ym))
            series["ordered"].append(o); series["paid"].append(p)
            series["balance"].append(r2(max(0, cum_o - cum_p))); series["sent"].append(snt)
            months.append({"ym": ym, "total": o, "paid": p})
        by_status = {st: {"count": len([s for s in rows if s["status"] == st]),
                          "amount": r2(sum(s["amount"] for s in rows if s["status"] == st))} for st in VALID_STATUS}
        top_sup = sorted(((by_sup[p], f["total"], f["debt"]) for p, f in fin.items() if f["total"] > 0),
                         key=lambda x: -x[1])[:6]
        by_store = {}
        for s in live:
            for i in s["items"]:
                k = "№" + i["store_number"] + (" · " + i["store_name"] if i["store_name"] else "")
                by_store[k] = r2(by_store.get(k, 0) + (i["amount"] or 0))
        by_store = sorted(by_store.items(), key=lambda x: -x[1])
        recent = [dict(r) for r in c.execute(self.PAY_SQL + " ORDER BY y.date DESC, y.id DESC LIMIT 6")]
        this_month = today()[:7]
        month_paid = r2(sum(signed(y) for y in pays if (y["date"] or "")[:7] == this_month))
        arriving = sorted(transit, key=lambda s: s["eta_date"] or s["sent_date"] or "9999")
        c.close()
        self._send(200, {"tiles": tiles, "series": series, "months": months, "by_status": by_status,
                         "top_suppliers": top_sup, "by_store": by_store, "recent_payments": recent,
                         "month_paid": month_paid, "payments_count": len(pays),
                         "debts": debts, "overpaid": overpaid,
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
                    "Валюта","Оплачено по партии","Остаток по партии","Сумма партии","Комментарий"])
        for s in rows:
            for i in s["items"]:
                w.writerow([s["date"], s["supplier_name"], st_ru.get(s["status"], s["status"]), s["track"] or "",
                            "№" + i["store_number"], i["product"], i["qty"] or "", i["unit"] or "",
                            i["unit_price"] or "", i["amount"], s["currency"], s["paid"], s["balance"],
                            s["amount"], (i["note"] or s["note"] or "")])
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
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print("Китай · учёт %s работает: http://localhost:%d" % (VERSION, PORT))
    srv.serve_forever()

if __name__ == "__main__":
    main()
