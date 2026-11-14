// Ajan Ofisi · prosedürel "duygu" karakterleri ve kontrol odası dekoru (harici model/doku yok)
// createDuygu({ tur, ton, yavru }) → createCat ile aynı arayüz:
//   { group, dugum, setDurum, setMeme, setKontur, update, tepki, durum, aktif, desen, tur, duygu, dispose }
// Koordinat: kök = sandalye oturağının üstü, karakter +z'ye bakar (kediyle aynı çerçeve).
// Biçimler özgündür: tek renkli parlak gövde, iri gözler, türüne göre küçük bir tepe işareti.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export const DUYGULAR = {
  neseli:  { ad:'Neşeli',  renk:'#ffc93c', bicim:'gunes' },
  merakli: { ad:'Meraklı', renk:'#2fbfa8', bicim:'anten' },
  telasli: { ad:'Telaşlı', renk:'#ff7a59', bicim:'diken' },
  sakin:   { ad:'Sakin',   renk:'#4f86d6', bicim:'filiz' },
  titiz:   { ad:'Titiz',   renk:'#8cc84b', bicim:'kup' },
  uykucu:  { ad:'Uykucu',  renk:'#8e9bb5', bicim:'sarkik' },
};
const SIRA = ['neseli', 'merakli', 'telasli', 'sakin', 'titiz', 'uykucu'];
const AJAN_DUYGU = {
  ceo:'sakin', gorevci:'titiz', arastirmaci:'merakli', arastirma:'merakli', arsivci:'uykucu', gunlukcu:'neseli',
  stratejist:'telasli', posta:'telasli', kod:'titiz', yazi:'neseli', tasarim:'neseli', veri:'titiz', bekci:'sakin',
};
// sabit eşleme; bilinmeyen ajan, bilinmeyenler arasındaki sırasına göre türü alır
export function ajanDuygusu(id, idler = []) {
  if (Object.hasOwn(AJAN_DUYGU, id)) return AJAN_DUYGU[id];
  const i = idler.filter(x => !Object.hasOwn(AJAN_DUYGU, x)).indexOf(id);
  return SIRA[Math.max(0, i) % SIRA.length];
}
export const duyguSirayla = i => SIRA[((i % SIRA.length) + SIRA.length) % SIRA.length];

const AZ_HAREKET = matchMedia('(prefers-reduced-motion: reduce)');
let PARILTI = true;
export function parlamaAyarla(acik) { PARILTI = !!acik; }

/* ---------- paylaşılan geometriler (tek kez; geçişlerde geometri sayısı sabit kalır) ---------- */
const GEO = (() => {
  const kure = new THREE.SphereGeometry(1, 32, 24);
  const kol = new THREE.CapsuleGeometry(.045, .14, 4, 10); kol.translate(0, -.09, 0);
  const koni = new THREE.ConeGeometry(1, 1, 16); koni.translate(0, .5, 0);
  const kup = new RoundedBoxGeometry(1, 1, 1, 4, .3);
  const yay = new THREE.TorusGeometry(.05, .012, 6, 16, Math.PI);
  const halka = new THREE.TorusGeometry(1, .14, 8, 28);
  const disk = new THREE.CircleGeometry(1, 32); disk.rotateX(-Math.PI / 2);
  const kutu = new THREE.BoxGeometry(1, 1, 1);
  const duzlem = new THREE.PlaneGeometry(1, 1);
  const konsol = new THREE.CylinderGeometry(1, 1, 1, 40, 1, true, -.72, 1.44);   // kavisli konsol paneli (+z'ye bakan yay)
  const konsolUst = new THREE.CylinderGeometry(1, 1, 1, 40, 1, false, -.72, 1.44);
  return { kure, kol, koni, kup, yay, halka, disk, kutu, duzlem, konsol, konsolUst };
})();
function parilti() {   // yumuşak ışıma dokusu (tek)
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const x = c.getContext('2d'), g = x.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, 'rgba(255,255,255,.9)'); g.addColorStop(.35, 'rgba(255,255,255,.35)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const DOKU = { parilti:parilti() };
const ORTAK = {
  ak: new THREE.MeshPhysicalMaterial({ color:'#ffffff', roughness:.2, clearcoat:1 }),
  bebek: new THREE.MeshPhysicalMaterial({ color:'#15121a', roughness:.1, clearcoat:1 }),
  isik: new THREE.MeshBasicMaterial({ color:'#ffffff' }),
  cizgi: new THREE.MeshBasicMaterial({ color:'#2a2220' }),
  agizIc: new THREE.MeshStandardMaterial({ color:'#5a2228', roughness:.6 }),
  gozluk: new THREE.MeshStandardMaterial({ color:'#2f3a4a', roughness:.35, metalness:.4 }),
};
const EKRAN = new THREE.Color('#bfe6ff'), KOYU = new THREE.Color('#2a2430');

/* ---------- karakter ---------- */
const YUZ0 = { acik:1, bakX:0, bakY:0, mutlu:0, agiz:0, uzgun:0, kas:0, buyuk:0 };
export function createDuygu({ tur = 'neseli', ton = 0, yavru = false } = {}) {
  if (!DUYGULAR[tur]) tur = 'neseli';
  const D = DUYGULAR[tur];
  const renk = new THREE.Color(D.renk).offsetHSL(0, 0, Math.round(ton * 4) / 4 * .05);
  const govdeMat = new THREE.MeshPhysicalMaterial({ color:renk.clone(), roughness:.35, clearcoat:.6, clearcoatRoughness:.3, emissive:renk.clone(), emissiveIntensity:.25 });
  const golgeMat = new THREE.MeshBasicMaterial({ color:renk.clone(), transparent:true, opacity:.35, depthWrite:false });
  const isimaMat = new THREE.SpriteMaterial({ map:DOKU.parilti, color:renk.clone(), transparent:true, opacity:.35, depthWrite:false, blending:THREE.AdditiveBlending });
  if (yavru) { govdeMat.transparent = true; govdeMat.opacity = .62; }
  const kendiMat = [govdeMat, golgeMat, isimaMat];

  const group = new THREE.Group();
  const kok = new THREE.Group(); group.add(kok);
  const dugum = { kok };
  const mesh = (parent, geo, mat, p = [0, 0, 0], s = [1, 1, 1], golge = true) => {
    const x = new THREE.Mesh(geo, mat); x.position.set(...p); x.scale.set(...s);
    if (golge) x.castShadow = true;
    parent.add(x); return x;
  };
  // biçime göre gövde ölçüsü: [yarıçap x, y, z, merkez y]
  const OLCU = { gunes:[.33, .33, .31, .4], anten:[.28, .39, .27, .45], diken:[.34, .3, .32, .38], filiz:[.36, .32, .33, .38], kup:[.56, .6, .5, .4], sarkik:[.32, .33, .31, .39] }[D.bicim];
  const [rx, ry, rz, cy] = OLCU;
  const kutuMu = D.bicim === 'kup';
  const govde = new THREE.Group(); govde.position.y = cy; kok.add(govde); dugum.govde = govde;
  mesh(govde, kutuMu ? GEO.kup : GEO.kure, govdeMat, [0, 0, 0], kutuMu ? [rx, ry, rz] : [rx, ry, rz]);
  const ust = kutuMu ? ry / 2 : ry, on = kutuMu ? rz / 2 + .005 : rz * .93;

  // tepe işareti (türün imzası)
  if (D.bicim === 'gunes') for (let i = 0; i < 7; i++) {
    const a = (i - 3) * .36, r = mesh(govde, GEO.koni, govdeMat, [Math.sin(a) * rx * .78, Math.cos(a) * ust * .86, -.02], [.045, .13, .045]);
    r.rotation.z = -a;
  }
  if (D.bicim === 'anten') {
    const sap = mesh(govde, GEO.koni, govdeMat, [0, ust * .95, 0], [.014, .22, .014]); sap.rotation.z = .25;
    mesh(govde, GEO.kure, govdeMat, [-.055, ust + .2, 0], [.05, .05, .05]);
  }
  if (D.bicim === 'diken') [[-.5, -.1], [0, 0], [.5, .1]].forEach(([a, dz]) => {
    const r = mesh(govde, GEO.koni, govdeMat, [Math.sin(a) * rx * .7, Math.cos(a) * ust * .85, dz], [.07, .17, .07]); r.rotation.z = -a * 1.2;
  });
  if (D.bicim === 'filiz') {
    mesh(govde, GEO.koni, govdeMat, [0, ust * .97, 0], [.012, .1, .012]);
    const y = mesh(govde, GEO.kure, govdeMat, [.06, ust + .1, 0], [.09, .022, .045]); y.rotation.z = .5;
  }
  if (D.bicim === 'sarkik') { const s = mesh(govde, GEO.koni, govdeMat, [.04, ust * .85, 0], [.13, .32, .13]); s.rotation.z = -1.5; }

  // yüz: göz, kaş, ağız (baş = yüz düğümü; meme aksesuarları buraya takılır)
  const gozY = kutuMu ? .06 : .07;
  const bas = new THREE.Group(); bas.position.set(0, cy + gozY, 0); kok.add(bas); dugum.bas = bas;
  const yuzG = new THREE.Group(); yuzG.position.z = on; bas.add(yuzG);
  const gozOlcek = yavru ? 1.2 : 1;
  const gozler = [-1, 1].map(s => {
    const g = new THREE.Group(); g.position.set(s * (kutuMu ? .12 : rx * .36), 0, 0); g.rotation.y = kutuMu ? 0 : s * .3; g.scale.setScalar(gozOlcek); yuzG.add(g);
    const acikG = new THREE.Group(); g.add(acikG);
    mesh(acikG, GEO.kure, ORTAK.ak, [0, 0, 0], [.072, .088, .035], false);
    const bebek = mesh(acikG, GEO.kure, ORTAK.bebek, [0, 0, .026], [.04, .05, .016], false);
    mesh(bebek, GEO.kure, ORTAK.isik, [.38, .4, .9], [.34, .3, .5], false);
    const yay = new THREE.Mesh(GEO.yay, ORTAK.cizgi); yay.position.z = .02; yay.visible = false; g.add(yay);
    const kas = mesh(g, GEO.kure, ORTAK.cizgi, [0, .115, .02], [.05, .011, .01], false);
    if (kutuMu) { const c = mesh(g, GEO.halka, ORTAK.gozluk, [0, 0, .03], [.095, .095, .095], false); c.userData.gozluk = true; }
    return { g, acikG, bebek, yay, kas, s };
  });
  const gulus = new THREE.Mesh(GEO.yay, ORTAK.cizgi); gulus.position.set(0, -.12, on + .01); gulus.scale.setScalar(1.1); bas.add(gulus);
  const agiz = mesh(bas, GEO.kure, ORTAK.agizIc, [0, -.14, on - .005], [.05, .001, .02], false);

  // kollar
  ['L', 'R'].forEach((y, i) => {
    const o = new THREE.Group(); o.position.set((i ? 1 : -1) * rx * (kutuMu ? .5 : .92), cy - .02, .02); kok.add(o); dugum['on' + y] = o;
    mesh(o, GEO.kol, govdeMat);
  });
  // süzülme gölgesi + ışıma
  const golge = mesh(group, GEO.disk, golgeMat, [0, .015, 0], [.26, 1, .26], false);
  const isima = new THREE.Sprite(isimaMat); isima.position.set(0, cy, -.05); isima.scale.setScalar(1.35); group.add(isima);

  /* ---------- durum makinesi ---------- */
  let durum = 'uyuyor', dis = 'uyuyor', t = Math.random() * 10, bittiT = -1, kirpT = 2 + Math.random() * 3, kirp = 0;
  let meme = null, akt = null, aktT = 0, kontur = null;
  const AKT = { esne:2.4, kuyruk:2.4, tay:2.4, bak:3, gerin:2.4, selam:2.6, gul:2.4 };
  const yuz = { ...YUZ0, acik:0 };
  const poz = { y:0, rx:0, z:0, sy:1, isik:.25, ekran:0, koyu:0, isima:.15 };
  function setDurum(yeni) {
    if (yeni === 'uyku') yeni = 'uyuyor';
    if (yeni === 'bekliyor') yeni = 'bosta';
    if (yeni === dis) return;
    dis = durum = yeni; akt = null;
    if (yeni === 'bitti') bittiT = t;
  }
  function setMeme(spec, { aninda = false } = {}) {
    meme = spec || null; akt = null;
    if (aninda && spec) Object.assign(yuz, YUZ0, ...[spec.yuz || {}].map(yuzCevir));
  }
  function tepki(ad) { if (meme || !AKT[ad]) return; akt = ad; aktT = t; }
  function setKontur(r) { kontur = r || null; }
  // meme yüz alanlarını (kedi) bu yüze çevirir
  const yuzCevir = y => ({ acik:y.acik ?? 1, mutlu:y.mutlu ?? 0, agiz:y.agiz ?? 0, bakX:y.bakX ?? 0, bakY:y.bakY ?? 0, buyuk:y.buyuk ?? 0, kas:y.kas ?? 0 });

  function hedef() {
    const h = { ...YUZ0 }, p = { y:.06, rx:0, z:0, sy:1, isik:.3, ekran:0, koyu:0, isima:.35 };
    if (meme) { Object.assign(h, yuzCevir(meme.yuz || {})); p.isik = .4; p.isima = .5; return [h, p]; }
    if (durum === 'uyuyor') { Object.assign(h, { acik:0 }); Object.assign(p, { y:0, rx:.14, sy:.93, isik:.12, isima:.12 }); }
    else if (durum === 'calisiyor') { Object.assign(h, { bakY:-.55, kas:.35 }); Object.assign(p, { y:.04, rx:.26, z:.12, isik:.35, ekran:1, isima:.55 }); }
    else if (durum === 'dusunuyor') { Object.assign(h, { bakY:.7, bakX:.4 }); Object.assign(p, { y:.08, isik:.35, isima:.45 }); }
    else if (durum === 'bitti') { Object.assign(h, { acik:0, mutlu:1, agiz:.55 }); Object.assign(p, { y:.08, isik:.6, isima:.85 }); }
    else if (durum === 'hata') { Object.assign(h, { uzgun:1, kas:1, bakY:-.3 }); Object.assign(p, { y:.02, rx:.08, sy:.96, isik:.08, koyu:1, isima:.15 }); }
    if (D.bicim === 'sarkik' && h.acik > .5 && durum !== 'bitti') h.acik = .62;   // uykucu: göz kapakları hep yarı inik
    if (akt === 'gul' || akt === 'selam') { h.mutlu = 1; h.acik = akt === 'gul' ? 0 : 1; h.agiz = .4; }
    if (akt === 'esne' || akt === 'gerin') { h.acik = 0; h.agiz = 1; }
    return [h, p];
  }

  function update(dt) {
    t += dt;
    if (akt && t - aktT >= AKT[akt]) akt = null;
    const az = AZ_HAREKET.matches ? .2 : 1;
    const k = 1 - Math.exp(-dt * 7);
    const [hy, hp] = hedef();
    if (meme?.konus) hy.agiz = .2 + Math.abs(Math.sin(t * 9)) * .55;
    if (!meme && (akt === 'bak' || (durum === 'bosta' && !akt))) { hy.bakX = Math.sin(t * .9) * .7; hy.bakY = Math.sin(t * .6) * .3; }
    Object.keys(yuz).forEach(n => { yuz[n] += (hy[n] - yuz[n]) * Math.min(1, k * 1.6); });
    Object.keys(poz).forEach(n => { poz[n] += (hp[n] - poz[n]) * k; });

    // gövde: süzülme, eğilme, zıplama, titreme
    const uyur = durum === 'uyuyor' && !meme;
    let y = poz.y + (uyur ? 0 : Math.sin(t * 1.6) * .035 * az), x = 0, sx = 1, sy = poz.sy, rz = 0;
    if (uyur) sy *= 1 + Math.sin(t * 1.7) * .025 * az;
    const bitiyor = durum === 'bitti' && bittiT >= 0 && t - bittiT < 1.6 && !meme;
    if (bitiyor) {
      const tb = t - bittiT, zip = Math.abs(Math.sin(tb * 6)) * (1 - tb / 1.6);
      y += zip * .22 * az; sy *= 1 + zip * .08 * az; sx = 1 - zip * .04 * az;
    }
    if (durum === 'hata' && !meme) { x = Math.sin(t * 55) * .012 * az; rz = Math.sin(t * 41) * .03 * az; }
    if (akt === 'gul') y += Math.abs(Math.sin(t * 9)) * .05 * az;
    kok.position.set(x, y, poz.z);
    kok.rotation.set(poz.rx, 0, rz);
    govde.scale.set(sx, sy, sx);

    // kollar
    const kol = { L:[0, 0, -.35], R:[0, 0, .35] };
    if (durum === 'calisiyor' && !meme && !akt) {
      kol.L = [-1.1 + Math.sin(t * 11) * .18, 0, -.2]; kol.R = [-1.1 + Math.sin(t * 11 + Math.PI) * .18, 0, .2];
    } else if (durum === 'dusunuyor' && !meme) kol.R = [-1.9, 0, .7];
    else if (durum === 'hata' && !meme) { kol.L = [0, 0, -.12]; kol.R = [0, 0, .12]; }
    else if (uyur) { kol.L = [-.3, 0, -.15]; kol.R = [-.3, 0, .15]; }
    if (bitiyor || akt === 'gerin') { kol.L = [0, 0, -2.5]; kol.R = [0, 0, 2.5]; }
    if (akt === 'selam') kol.R = [0, 0, 2.4 + Math.sin(t * 12) * .35];
    if (meme?.yaz) { kol.L = [-1.1 + Math.sin(t * 11) * .18, 0, -.2]; kol.R = [-1.1 + Math.sin(t * 11 + Math.PI) * .18, 0, .2]; }
    ['L', 'R'].forEach(s => { const o = dugum['on' + s], h = kol[s]; o.rotation.x += (h[0] - o.rotation.x) * k * 1.4; o.rotation.z += (h[2] - o.rotation.z) * k * 1.4; });

    // renk: hata koyulaşır, çalışırken ekran ışığı yüzü serinletir
    govdeMat.color.copy(renk).lerp(KOYU, poz.koyu * .5);
    govdeMat.emissive.copy(renk).lerp(EKRAN, poz.ekran * .45).lerp(KOYU, poz.koyu * .6);
    govdeMat.emissiveIntensity = poz.isik + (durum === 'calisiyor' ? Math.sin(t * 5) * .04 : 0);
    isima.visible = PARILTI;
    isimaMat.color.set(kontur || renk);
    isimaMat.opacity = Math.min(1, poz.isima * (kontur ? 1.3 : 1));
    isima.position.set(kok.position.x, cy + kok.position.y, poz.z - .05);
    isima.scale.setScalar(kutuMu ? 1.55 : 1.35);
    golge.scale.set(.26 - y * .3, 1, .26 - y * .3);
    golgeMat.opacity = .35 - y * .6;

    // göz kırpma ve ifade
    if (!uyur && yuz.acik > .8) { kirpT -= dt; if (kirpT < 0) { kirp = .14; kirpT = 2 + Math.random() * 4; } }
    kirp = Math.max(0, kirp - dt);
    const acik = yuz.acik * (kirp > 0 ? .08 : 1);
    gozler.forEach(o => {
      o.acikG.visible = acik > .22;
      o.acikG.scale.set(1, Math.max(.05, acik), 1);
      o.yay.visible = acik <= .22;
      o.yay.rotation.z = yuz.mutlu > .5 ? 0 : Math.PI;
      o.yay.position.y = yuz.mutlu > .5 ? -.02 : .015;
      o.bebek.position.x = yuz.bakX * .022;
      o.bebek.position.y = yuz.bakY * .024;
      o.g.scale.setScalar(gozOlcek * (1 + yuz.buyuk * .3));
      o.kas.visible = yuz.kas > .1;
      // odak: kaşlar içe iner; üzüntü: iç uçlar kalkar
      o.kas.rotation.z = o.s * (yuz.uzgun > .5 ? .45 : -.35) * yuz.kas;
      o.kas.position.y = .115 - (yuz.uzgun > .5 ? 0 : .015 * yuz.kas);
    });
    gulus.visible = yuz.agiz < .15;
    gulus.rotation.z = yuz.uzgun > .5 ? 0 : Math.PI;   // ∪ gülüş, ∩ üzgün
    gulus.position.y = yuz.uzgun > .5 ? -.16 : -.1;
    agiz.scale.set(.05, .001 + yuz.agiz * .045, .02);
    agiz.visible = yuz.agiz > .02;
  }

  function dispose() {
    group.removeFromParent();
    kendiMat.forEach(m => m.dispose());
  }

  update(0);
  return {
    group, dugum, setDurum, setMeme, setKontur, update, tepki, dispose, tur, duygu:true, desen:tur,
    get durum() { return durum; }, get aktif() { return !!akt; },
  };
}

/* ---------- kontrol odası dekoru: kavisli konsollar, cam pencere bandı, anı küreleri rafı ---------- */
const PENCERE = (() => {
  const c = document.createElement('canvas'); c.width = 512; c.height = 64;
  const x = c.getContext('2d'), g = x.createLinearGradient(0, 0, 0, 64);
  g.addColorStop(0, '#ffd9b8'); g.addColorStop(.55, '#ffeeda'); g.addColorStop(1, '#cfe9f2');
  x.fillStyle = g; x.fillRect(0, 0, 512, 64);
  x.fillStyle = 'rgba(255,255,255,.55)';
  for (let i = 0; i < 9; i++) { x.beginPath(); x.ellipse(30 + i * 58, 46 + (i % 3) * 4, 26, 7, 0, 0, Math.PI * 2); x.fill(); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping;
  return t;
})();
const DEKOR_MAT = {
  pencere: new THREE.MeshBasicMaterial({ map:PENCERE, toneMapped:false }),
  cerceve: new THREE.MeshStandardMaterial({ color:'#e9e1d4', roughness:.6 }),
  raf: new THREE.MeshStandardMaterial({ color:'#d9cfc0', roughness:.7 }),
  konsolUst: new THREE.MeshStandardMaterial({ color:'#f3ece2', roughness:.5 }),
};
const KURE_MAT = new Map();   // renk → anı küresi malzemesi (az sayıda renk, paylaşılır)
function kureMat(r) {
  if (!KURE_MAT.has(r)) KURE_MAT.set(r, new THREE.MeshStandardMaterial({ color:r, emissive:r, emissiveIntensity:.55, roughness:.25 }));
  return KURE_MAT.get(r);
}
const HATA_RENK = '#5b4650', RAF_KAPASITE = 24;

// odalar: {id,cx,cz,w,d,cam}; ajanlar: {id,oda,grup,durum}; anilar: [{ajan, hata}] (eskiden yeniye); tur(a) → duygu türü
export function kontrolOdasiKur({ odalar, ajanlar, anilar = [], tur }) {
  const grup = new THREE.Group(); grup.name = 'kontrol-odasi';
  const kendiMat = [];
  const konsollar = [];
  const m = (parent, geo, mat, p, s, rot) => {
    const x = new THREE.Mesh(geo, mat); x.position.set(...p); x.scale.set(...s); if (rot) x.rotation.set(...rot);
    x.castShadow = false; x.receiveShadow = true; parent.add(x); return x;
  };
  // her masaya kavisli konsol: masanın ön kenarında yay, ajanın renginde yanan panel ve düğmeler
  ajanlar.forEach(a => {
    if (!a.grup) return;
    const g = new THREE.Group(); g.position.copy(a.grup.position); g.scale.copy(a.grup.scale); grup.add(g);
    const r = DUYGULAR[tur(a)]?.renk || '#ffc93c';
    const panel = new THREE.MeshStandardMaterial({ color:'#2b2f3a', emissive:r, emissiveIntensity:.25, roughness:.4, side:THREE.DoubleSide });
    kendiMat.push(panel);
    m(g, GEO.konsol, panel, [0, .905, 0], [1.28, .09, 1.28]);
    m(g, GEO.konsolUst, DEKOR_MAT.konsolUst, [0, .955, 0], [1.31, .02, 1.31]);
    [-.5, -.25, 0, .25, .5].forEach((aci, i) => m(g, GEO.kure, kureMat(i % 2 ? r : '#fff3d6'), [Math.sin(aci) * 1.2, .97, Math.cos(aci) * 1.2], [.03, .02, .03]));
    konsollar.push({ a, panel, faz:Math.random() * 6 });
  });
  const raflar = new Map();
  odalar.forEach(o => {
    const og = new THREE.Group(); og.position.set(o.cx, 0, o.cz); grup.add(og);
    if (!o.cam) {   // arka duvarın üst bandında cam pencere (ekranların üstünde kalır)
      const w = Math.max(2, o.w - 1.4);
      const p = m(og, GEO.duzlem, DEKOR_MAT.pencere, [0, 2.45, -o.d / 2 + .25], [w, .34, 1]);
      p.receiveShadow = false;
      m(og, GEO.kutu, DEKOR_MAT.cerceve, [0, 2.27, -o.d / 2 + .27], [w + .1, .04, .05]);
      m(og, GEO.kutu, DEKOR_MAT.cerceve, [0, 2.63, -o.d / 2 + .27], [w + .1, .04, .05]);
      for (let i = 0, n = Math.max(1, Math.round(w / 1.3)); i <= n; i++) m(og, GEO.kutu, DEKOR_MAT.cerceve, [-w / 2 + i * w / n, 2.45, -o.d / 2 + .27], [.04, .36, .05]);
    }
    // anı küreleri rafı: sağ duvar boyunca iki kat
    const rx = o.w / 2 - .42;
    [1.3, 1.72].forEach(y => m(og, GEO.kutu, DEKOR_MAT.raf, [rx, y, 0], [.32, .04, 2.6]));
    m(og, GEO.kutu, DEKOR_MAT.raf, [rx, 1.5, -1.3], [.32, .5, .04]);
    m(og, GEO.kutu, DEKOR_MAT.raf, [rx, 1.5, 1.3], [.32, .5, .04]);
    const kureler = new THREE.Group(); og.add(kureler);
    raflar.set(o.id, { rx, kureler, liste:[] });
  });
  function kureCiz(raf) {
    raf.kureler.clear();
    raf.liste.slice(-RAF_KAPASITE).forEach((renk, i) => {
      const kat = i < 12 ? 0 : 1, j = i % 12;
      m(raf.kureler, GEO.kure, kureMat(renk), [raf.rx, (kat ? 1.72 : 1.3) + .11, -1.1 + j * .2], [.085, .085, .085]);
    });
  }
  function aniEkle(ajanId, hata, ciz = true) {
    const a = ajanlar.find(x => x.id === ajanId); if (!a) return;
    const raf = raflar.get(a.oda); if (!raf) return;
    raf.liste.push(hata ? HATA_RENK : (DUYGULAR[tur(a)]?.renk || '#ffc93c'));
    if (raf.liste.length > RAF_KAPASITE) raf.liste.shift();
    if (ciz) kureCiz(raf);
  }
  anilar.forEach(x => aniEkle(x.ajan, x.hata, false));
  raflar.forEach(kureCiz);
  function update(t) {
    konsollar.forEach(k => {
      const d = k.a.durum;
      k.panel.emissiveIntensity = d === 'calisiyor' || d === 'dusunuyor' ? .55 + Math.sin(t * 3 + k.faz) * .2 : d === 'bitti' ? .7 : .2;
    });
  }
  function dispose() {
    grup.removeFromParent();
    kendiMat.forEach(x => x.dispose());   // geometriler ve ortak malzemeler paylaşılır, atılmaz
  }
  return { grup, aniEkle, update, dispose };
}
