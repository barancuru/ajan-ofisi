/* Model kullanımı: bugün / 7 / 30 gün ve tüm zamanlar; model ve laboratuvar payı.
   Veri: GET /api/model-kullanim (model_kullanim.py). Ofis sekmesi (index.html) ve tam sayfa (modeller.html) ortak. */
(function () {
  'use strict';
  const MK_RENK = { 'claude-opus-5-5':'#c2482a', 'claude-fable-5-2':'#8a5cc7', 'claude-sonnet-5-5':'#ecbc4a', 'claude-haiku-5-5':'#7fb3dd' };
  const MK_YEDEK = ['#4f9a78', '#3f6f95', '#b8865a', '#9a8f80'];
  const LAB_RENK = { Anthropic:'#c2482a', OpenAI:'#3f6f95', Google:'#4f9a78', Moonshot:'#8a5cc7' };
  const DONEMLER = [['bugun', 'Bugün'], ['7', '7 gün'], ['30', '30 gün'], ['tum', 'Tümü']];
  const KAYNAK_AD = { terminal:'terminal ve hat', ofis:'ofis ajanları', codex:'Codex', antigravity:'Antigravity' };
  let secili = '30';

  function el(tag, cls, txt) { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
  async function getJSON(yol) {
    const r = await fetch(yol, { cache:'no-store' });
    if (!r.ok) throw new Error(yol + ' ' + r.status);
    return r.json();
  }
  function sayi(n) {
    n = Math.max(0, Math.round(n || 0));
    const f = (x, ek) => x.toLocaleString('tr-TR', { maximumFractionDigits:1 }) + ' ' + ek;
    if (n >= 1e9) return f(n / 1e9, 'mlr');
    if (n >= 1e6) return f(n / 1e6, 'mn');
    if (n >= 1e3) return f(n / 1e3, 'bin');
    return String(n);
  }
  const dolar = v => v == null ? '—' : '$' + Math.round(v).toLocaleString('tr-TR');
  const tarihYaz = (t, yil) => new Date(t + 'T12:00').toLocaleDateString('tr-TR', yil ? { day:'numeric', month:'long', year:'numeric' } : { day:'numeric', month:'short' });

  async function sayfa(sec) {
    sec = sec || {};
    let v;
    try { v = await getJSON('/api/model-kullanim'); }
    catch (e) { return [el('h2', null, 'Model kullanımı'), el('p', 'alt', 'Veri alınamadı: ' + e.message)]; }
    const renk = {}; let y = 0;
    const renkAl = m => renk[m] || (renk[m] = MK_RENK[m] || MK_YEDEK[y++ % MK_YEDEK.length]);
    const d30 = v.donemler['30'], tum = v.donemler.tum || d30;
    tum.modeller.forEach(m => renkAl(m.model));

    const baslik = el('div', 'mk-baslik'); baslik.append(el('h2', null, 'Model kullanımı'));
    if (sec.tamSayfaDugmesi) {
      const a = el('a', 'mk-tam', 'Tam sayfa ↗'); a.href = 'modeller.html'; a.target = '_blank'; a.rel = 'noopener';
      a.title = 'Model kullanımını ayrı bir sekmede tam sayfa aç'; baslik.append(a);
    }
    const ust = el('div', 'mk-ust');
    if (v.su_an) ust.append(el('span', null, 'Şu an'), el('b', null, v.su_an.ad));
    ust.append(el('span', null, '· son güncelleme ' + String(v.guncelleme || '').replace('T', ' ')));

    const ozet = el('div', 'ozet-sayilar mk-ozet');
    const kutu = (b, s, cls) => { const d = el('div', cls); d.append(el('b', null, b), el('span', null, s)); ozet.append(d); };
    kutu(sayi(v.donemler.bugun.token), 'Bugün · token');
    kutu(sayi(v.donemler['7'].token), '7 gün · token');
    kutu(sayi(d30.token), '30 gün · token');
    kutu(dolar(d30.usd) + (d30.eksik_fiyat.length ? '+' : ''), '30 günün API karşılığı');
    kutu(sayi(tum.token) + ' · ' + dolar(tum.usd) + (tum.eksik_fiyat.length ? '+' : ''),
      'Toplam' + (v.ilk_gun ? ' · ' + tarihYaz(v.ilk_gun, true) + '’den beri' : ''), 'toplam');

    // 30 günlük yığılmış sütun grafiği (inline SVG)
    const NS = 'http://www.w3.org/2000/svg', W = 720, ENS = innerWidth < 600 ? 26 : 11, ALT = ENS + 8, H = 200 + ALT - 18, seri = v.seri;
    const enb = Math.max(1, ...seri.map(g => Object.values(g.modeller).reduce((a, b) => a + b, 0)));
    const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Son 30 gün, günlük token, modele göre');
    const sw = W / seri.length;
    seri.forEach((g, i) => {
      let yy = H - ALT;
      const top = Object.values(g.modeller).reduce((a, b) => a + b, 0);
      tum.modeller.forEach(m => {
        const t = g.modeller[m.model] || 0; if (!t) return;
        const h = Math.max(1, t / enb * (H - ALT - 6)); yy -= h;
        const r = document.createElementNS(NS, 'rect');
        r.setAttribute('x', (i * sw + sw * .15).toFixed(1)); r.setAttribute('width', (sw * .7).toFixed(1));
        r.setAttribute('y', yy.toFixed(1)); r.setAttribute('height', h.toFixed(1)); r.setAttribute('fill', renkAl(m.model));
        const tt = document.createElementNS(NS, 'title'); tt.textContent = g.tarih + ' · ' + m.ad + ': ' + sayi(t) + ' (gün ' + sayi(top) + ')';
        r.append(tt); svg.append(r);
      });
    });
    [[0, 'start'], [seri.length - 1, 'end']].forEach(([i, a]) => {
      const t = document.createElementNS(NS, 'text'); t.setAttribute('class', 'eksen'); t.setAttribute('font-size', ENS); t.setAttribute('text-anchor', a);
      t.setAttribute('x', a === 'start' ? 2 : W - 2); t.setAttribute('y', H - 3); t.textContent = tarihYaz(seri[i].tarih); svg.append(t); });
    const graf = el('div', 'mk-grafik'); const lej = el('div', 'mk-lejant');
    d30.modeller.forEach(m => { const s = el('span'); const i = el('i'); i.style.background = renkAl(m.model); s.append(i, m.ad); lej.append(s); });
    graf.append(el('h3', 'kucuk', 'Son 30 gün'), svg, lej);

    // dönem seçmeli model tablosu
    const tabloKap = el('div');
    const ciz = () => {
      const d = v.donemler[secili] || d30;
      const t = el('table'); const bas = el('tr');
      [['Model'], ['Pay', 1], ['Token', 1], ['USD', 1]].forEach(([x, s]) => bas.append(el('th', s ? 'sayi' : '', x))); t.append(bas);
      d.modeller.forEach(m => {
        const tr = el('tr'); const ilk = el('td'); const cubuk = el('span', 'mk-pay');
        cubuk.style.width = Math.max(3, m.pay * 80) + 'px'; cubuk.style.background = renkAl(m.model); ilk.append(cubuk, m.ad); ilk.title = m.lab;
        tr.append(ilk, el('td', 'sayi', m.pay > 0 && m.pay < .005 ? '<%1' : '%' + Math.round(m.pay * 100)), el('td', 'sayi', sayi(m.token)), el('td', 'sayi', dolar(m.usd)));
        t.append(tr);
      });
      if (!d.modeller.length) { const tr = el('tr'); const td = el('td', null, 'Bu dönemde kullanım yok.'); td.colSpan = 4; tr.append(td); t.append(tr); }
      else { const tr = el('tr', 'mk-alt-toplam'); tr.append(el('th', null, 'Toplam'), el('th', 'sayi', ''), el('th', 'sayi', sayi(d.token)), el('th', 'sayi', dolar(d.usd))); t.append(tr); }
      const kap = el('div', 'maliyet-kap mk-tablo'); kap.append(t);
      const lab = el('div', 'mk-lab'); const labYazi = el('p', 'alt');
      d.laboratuvar.forEach(l => { const p = el('span'); p.style.width = (l.pay * 100) + '%'; p.style.background = LAB_RENK[l.lab] || '#9a8f80'; p.title = l.lab; lab.append(p); });
      labYazi.textContent = d.laboratuvar.map(l => l.lab + ' %' + Math.round(l.pay * 100)).join(' · ') || '—';
      const kay = el('p', 'alt', 'Kaynak: ' + Object.entries(d.kaynaklar || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => (KAYNAK_AD[k] || k) + ' ' + sayi(n)).join(' · '));
      tabloKap.replaceChildren(kap, el('h3', 'mk-b', 'Laboratuvar'), lab, labYazi, kay,
        ...(d.eksik_fiyat.length ? [el('p', 'alt', 'Fiyatı tanımlı değil: ' + d.eksik_fiyat.join(', ') + ' (USD toplamına girmedi).')] : []));
    };
    const secim = el('div', 'mk-donem'); secim.setAttribute('role', 'group'); secim.setAttribute('aria-label', 'Dönem');
    DONEMLER.forEach(([k, s]) => {
      const b = el('button', k === secili ? 'secili' : '', s); b.type = 'button'; b.setAttribute('aria-pressed', k === secili);
      b.onclick = () => { secili = k; secim.querySelectorAll('button').forEach(x => { const on = x === b; x.classList.toggle('secili', on); x.setAttribute('aria-pressed', on); }); ciz(); };
      secim.append(b); });
    ciz();

    const roller = el('div', 'mk-roller');
    v.roller.forEach(r => { const k = el('div'); k.append(el('b', null, r.ad), el('small', null, [r.model_ad, r.effort, r.lab].filter(Boolean).join(' · ')));
      if (r.aciklama) k.append(el('p', null, r.aciklama)); roller.append(k); });
    return [baslik, ust, ozet, graf, el('h3', 'mk-b', 'Modeller'), secim, tabloKap,
      ...(v.roller.length ? [el('h3', 'mk-b', 'Ofis rolleri'), roller] : []),
      el('p', 'alt', v.not + ' "Tümü" diskte kalan ve önceden okunmuş kayıtları kapsar; Claude Code transkriptleri 30 günde silse de toplam korunur.')];
  }

  window.ModelKullanim = { sayfa };
})();
