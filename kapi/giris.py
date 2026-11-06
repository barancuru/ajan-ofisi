#!/usr/bin/env python3
"""Ajan Ofisi web login (sits behind Caddy's forward_auth). Stdlib only, 127.0.0.1 only.

- GET  /dogrula  Caddy asks on every request: valid session cookie -> 200; otherwise /api -> 401, page -> 302 /giris
- GET  /giris    login form;  POST /giris  check password, set cookie, redirect to target
- GET  /cikis    clear session
Password: ~/.config/ofis-kapi/parola (plain, 600). Session signing key: ~/.config/ofis-kapi/oturum-anahtari.
Changing the password or deleting the key file invalidates all sessions.
"""
import base64
import hashlib
import hmac
import html
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

AYAR = os.path.expanduser(os.environ.get("OFIS_KAPI_AYAR", "~/.config/ofis-kapi"))
PORT = int(os.environ.get("OFIS_GIRIS_PORT", "8799"))
CEREZ = "ofis_oturum"
OTURUM_SN = 30 * 24 * 3600
DENEME_PENCERE_SN, DENEME_SINIR = 15 * 60, 10

_denemeler = {}  # ip -> [timestamp, ...]
_kilit = threading.Lock()


def oku(ad):
    with open(os.path.join(AYAR, ad), encoding="utf-8") as f:
        return f.read().strip()


def anahtar():
    yol = os.path.join(AYAR, "oturum-anahtari")
    if not os.path.exists(yol):
        eski = os.umask(0o077)
        try:
            with open(yol, "w", encoding="utf-8") as f:
                f.write(secrets.token_hex(32))
        finally:
            os.umask(eski)
    # the password is part of the key: when the password changes, old sessions become invalid
    return hashlib.sha256((oku("oturum-anahtari") + "\0" + oku("parola")).encode()).digest()


def imzala(govde):
    return base64.urlsafe_b64encode(hmac.new(anahtar(), govde.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def oturum_uret():
    govde = f"{int(time.time()) + OTURUM_SN}.{secrets.token_urlsafe(9)}"
    return f"{govde}.{imzala(govde)}"


def oturum_gecerli(deger):
    try:
        bitis, nonce, imza = deger.split(".", 2)
        return hmac.compare_digest(imza, imzala(f"{bitis}.{nonce}")) and int(bitis) > time.time()
    except (ValueError, OSError):
        return False


def cerez_al(baslik):
    for parca in (baslik or "").split(";"):
        ad, _, deger = parca.strip().partition("=")
        if ad == CEREZ:
            return deger
    return ""


def guvenli_hedef(hedef):
    hedef = hedef or "/"
    if not hedef.startswith("/") or hedef.startswith("//") or "\\" in hedef or hedef.startswith("/giris"):
        return "/"
    return hedef


def cok_deneme(ip):
    simdi = time.time()
    with _kilit:
        liste = [t for t in _denemeler.get(ip, []) if simdi - t < DENEME_PENCERE_SN]
        _denemeler[ip] = liste
        return len(liste) >= DENEME_SINIR


def deneme_yaz(ip):
    with _kilit:
        _denemeler.setdefault(ip, []).append(time.time())


SAYFA = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#efe7da">
<title>Ajan Ofisi · Giriş</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E%3Crect width=%2232%22 height=%2232%22 rx=%228%22 fill=%22%23ff7a59%22/%3E%3Crect x=%229%22 y=%2211%22 width=%2214%22 height=%2210%22 rx=%223%22 fill=%22%23fff7f2%22/%3E%3C/svg%3E">
<style>
:root{--krem:#efe7da;--murekkep:#3b342c;--soluk:#8a7f72;--mercan:#ff7a59;--kart:rgba(255,250,243,.86)}
@media (prefers-color-scheme:dark){:root{--krem:#1f1b17;--murekkep:#f3ebdf;--soluk:#a89c8e;--kart:rgba(43,38,33,.9)}}
*{box-sizing:border-box;margin:0}
body{min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--krem);color:var(--murekkep);
  font-family:Inter,system-ui,sans-serif;background-image:radial-gradient(ellipse at 30% 20%,rgba(255,122,89,.16),transparent 60%)}
form{width:min(380px,100%);background:var(--kart);border:1px solid rgba(255,255,255,.18);border-radius:20px;padding:28px 24px;
  box-shadow:0 20px 60px rgba(59,52,44,.18);display:flex;flex-direction:column;gap:14px}
.logo{width:44px;height:44px;border-radius:12px;background:var(--mercan);display:grid;place-items:center}
.logo i{width:20px;height:14px;border-radius:4px;background:#fff7f2}
h1{font-size:24px;letter-spacing:-.02em}
p{font-size:14px;color:var(--soluk);line-height:1.45}
label{font-size:13px;font-weight:600}
input{font:inherit;font-size:16px;padding:12px 14px;border-radius:12px;border:1px solid rgba(138,127,114,.4);background:transparent;color:inherit}
input:focus{outline:2px solid var(--mercan);outline-offset:1px}
button{font:inherit;font-weight:600;font-size:15px;padding:12px;border:0;border-radius:12px;background:var(--mercan);color:#fff;cursor:pointer}
.hata{font-size:13.5px;color:#d0554a;font-weight:500}
</style></head><body>
<form method="post" action="/giris">
  <div class="logo"><i></i></div>
  <h1>Ajan Ofisi</h1>
  <p>Devam etmek için ofis şifresini gir. Bu cihazda 30 gün açık kalır.</p>
  {hata}
  <label for="parola">Şifre</label>
  <input id="parola" name="parola" type="password" autocomplete="current-password" autofocus required>
  <input type="hidden" name="sonra" value="{sonra}">
  <button type="submit">Giriş yap</button>
</form>
</body></html>"""


class Isleyici(BaseHTTPRequestHandler):
    server_version = "ofis-giris"
    sys_version = ""
    timeout = 10

    def log_message(self, fmt, *args):
        pass  # don't write passwords or cookies to the log

    def _ip(self):
        # İstemci başlığa kendi değerini ekleyebilir; güvenilir vekillerin eklediği son öğelere bakılır.
        try:
            vekil = int(os.environ.get("OFIS_GUVENILIR_VEKIL", "1"))
        except ValueError:
            vekil = 1
        parcalar = [p.strip() for p in (self.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
        if vekil < 1 or len(parcalar) < vekil:
            return self.client_address[0]
        return parcalar[-vekil]

    def _yaz(self, kod, govde=b"", tur="text/plain; charset=utf-8", basliklar=()):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for ad, deger in basliklar:
            self.send_header(ad, deger)
        self.end_headers()
        self.wfile.write(govde)

    def _sayfa(self, kod=200, hata="", sonra="/"):
        kutu = f'<p class="hata" role="alert">{html.escape(hata)}</p>' if hata else ""
        govde = SAYFA.replace("{hata}", kutu).replace("{sonra}", html.escape(sonra, quote=True)).encode()
        self._yaz(kod, govde, "text/html; charset=utf-8")

    def do_GET(self):
        yol = urlparse(self.path)
        if yol.path == "/dogrula":
            if oturum_gecerli(cerez_al(self.headers.get("Cookie"))):
                return self._yaz(200)
            hedef = self.headers.get("X-Forwarded-Uri") or "/"
            if hedef.startswith("/api/") or "text/html" not in (self.headers.get("Accept") or ""):
                return self._yaz(401, b'{"hata":"oturum gerekli"}', "application/json; charset=utf-8")
            return self._yaz(302, basliklar=[("Location", "/giris?sonra=" + quote(guvenli_hedef(hedef)))])
        if yol.path == "/giris":
            if oturum_gecerli(cerez_al(self.headers.get("Cookie"))):
                return self._yaz(303, basliklar=[("Location", "/")])
            return self._sayfa(sonra=guvenli_hedef(parse_qs(yol.query).get("sonra", ["/"])[0]))
        if yol.path == "/cikis":
            return self._yaz(303, basliklar=[
                ("Set-Cookie", f"{CEREZ}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"), ("Location", "/giris")])
        return self._yaz(404)

    def do_POST(self):
        if urlparse(self.path).path != "/giris":
            return self._yaz(404)
        ip = self._ip()
        if cok_deneme(ip):
            return self._sayfa(429, "Çok fazla hatalı deneme. 15 dakika sonra tekrar dene.")
        try:
            uzunluk = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._sayfa(400, "Geçersiz istek.")
        if uzunluk < 0:
            return self._sayfa(400, "Geçersiz istek.")
        if uzunluk > 4096:
            self.close_connection = True
            return self._sayfa(413, "İstek çok büyük.")
        try:
            ham = self.rfile.read(uzunluk)
        except OSError:  # TimeoutError dahil: yarım gövde
            self.close_connection = True
            return self._sayfa(408, "İstek zaman aşımına uğradı.")
        alanlar = parse_qs(ham.decode("utf-8", "replace"))
        parola = alanlar.get("parola", [""])[0]
        sonra = guvenli_hedef(alanlar.get("sonra", ["/"])[0])
        if not hmac.compare_digest(parola.encode(), oku("parola").encode()):
            deneme_yaz(ip)
            time.sleep(1)
            return self._sayfa(401, "Şifre hatalı.", sonra)
        self._yaz(303, basliklar=[
            ("Set-Cookie", f"{CEREZ}={oturum_uret()}; Max-Age={OTURUM_SN}; Path=/; HttpOnly; Secure; SameSite=Lax"),
            ("Location", sonra)])


if __name__ == "__main__":
    anahtar()
    ThreadingHTTPServer(("127.0.0.1", PORT), Isleyici).serve_forever()
