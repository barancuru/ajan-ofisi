// Ajan Ofisi · hafif 2D görünüm: WebGL yok, rAF yok. Ana modülün veri durumundan (veri()) çizilir;
// her öğe imzasıyla karşılaştırılır, yalnız değişen kart, oda ya da satır DOM'da güncellenir.
// veri() biçimi: { ozet:[[deger, etiket]], odalar:[{id, ad, renk, kartlar:[kart], masalar:[metin]}], terminaller:[satir] }
// kart: { anahtar, ad, harf, renk, durum, durumYazi, alt, ac:{tur:'ajan'|'oda', id} }
// satir: { anahtar, ust, alt, durum }

function el(tag, cls, txt) { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }

export function ofis2dKur(kok, { veri, ac }) {
  const ozet = el('div', 'o2-ozet');
  const odalar = el('div', 'o2-odalar');
  const term = el('section', 'o2-blok');
  const termBaslik = el('h3', 'o2-baslik', 'Terminal oturumları');
  const termListe = el('ul', 'o2-terminal');
  const termBos = el('p', 'o2-bos', 'Açık terminal oturumu yok.');
  term.setAttribute('aria-label', 'Terminal oturumları');
  term.append(termBaslik, termListe, termBos);
  kok.append(ozet, odalar, term);

  const imza = new WeakMap();
  const degisti = (d, v) => { const s = JSON.stringify(v); if (imza.get(d) === s) return false; imza.set(d, s); return true; };
  const odaDom = new Map(), kartDom = new Map(), termDom = new Map();

  function kartCiz(d, k) {
    d.dataset.durum = k.durum;
    d.style.setProperty('--renk', k.renk);
    const harf = el('span', 'o2-harf', k.harf); harf.setAttribute('aria-hidden', 'true');
    const durum = el('span', 'o2-durum'); durum.append(el('span', 'o2-nokta'), el('span', null, k.durumYazi));
    d.replaceChildren(harf, el('span', 'o2-ad', k.ad), durum, ...(k.alt ? [el('span', 'o2-alt', k.alt)] : []));
  }
  function odaCiz(o) {
    let x = odaDom.get(o.id);
    if (!x) {
      const s = el('section', 'o2-oda'), h = el('h3'), b = el('button', 'o2-oda-ad');
      b.type = 'button'; b.onclick = () => ac({ tur:'oda', id:o.id });
      h.append(b); const govde = el('div', 'o2-kartlar'), masa = el('div', 'o2-masalar');
      s.append(h, govde, masa);
      x = { s, b, govde, masa }; odaDom.set(o.id, x);
    }
    if (degisti(x.s, [o.ad, o.renk])) { x.b.textContent = o.ad; x.s.style.setProperty('--oda', o.renk); x.s.setAttribute('aria-label', o.ad); }
    const sira = o.kartlar.map(k => {
      let d = kartDom.get(k.anahtar);
      if (!d) { d = el('button', 'o2-ajan'); d.type = 'button'; kartDom.set(k.anahtar, d); }
      d.onclick = () => ac(k.ac);
      if (degisti(d, k)) kartCiz(d, k);
      return d;
    });
    if (o.kartlar.length === 0 && !x.govde.querySelector('.o2-bos')) x.govde.replaceChildren(el('p', 'o2-bos', 'Bu odada masa yok.'));
    else if (o.kartlar.length) yerlestir(x.govde, sira);
    if (degisti(x.masa, o.masalar)) x.masa.replaceChildren(...o.masalar.map(m => el('div', 'o2-masa', m)));
    return x.s;
  }
  // kapsayıcının çocuklarını verilen sıraya getirir; yerinde olan düğüme dokunmaz
  function yerlestir(kap, sira) {
    sira.forEach((d, i) => { if (kap.children[i] !== d) kap.insertBefore(d, kap.children[i] || null); });
    while (kap.children.length > sira.length) kap.lastElementChild.remove();
  }

  function ciz() {
    const v = veri();
    if (degisti(ozet, v.ozet)) ozet.replaceChildren(...v.ozet.map(([deger, etiket]) => { const d = el('div'); d.append(el('b', null, String(deger)), el('span', null, etiket)); return d; }));
    yerlestir(odalar, v.odalar.map(odaCiz));
    const gelenOda = new Set(v.odalar.map(o => o.id));
    odaDom.forEach((x, id) => { if (!gelenOda.has(id)) odaDom.delete(id); });
    const gelenKart = new Set(v.odalar.flatMap(o => o.kartlar.map(k => k.anahtar)));
    kartDom.forEach((d, id) => { if (!gelenKart.has(id)) { d.remove(); kartDom.delete(id); } });
    const satirlar = v.terminaller.map(t => {
      let d = termDom.get(t.anahtar);
      if (!d) { d = el('li'); termDom.set(t.anahtar, d); }
      if (degisti(d, t)) { d.dataset.durum = t.durum; d.replaceChildren(el('b', null, t.ust), el('span', null, t.alt)); }
      return d;
    });
    yerlestir(termListe, satirlar);
    const gelenTerm = new Set(v.terminaller.map(t => t.anahtar));
    termDom.forEach((d, id) => { if (!gelenTerm.has(id)) termDom.delete(id); });
    termBos.hidden = satirlar.length > 0;
  }
  return { ciz };
}
