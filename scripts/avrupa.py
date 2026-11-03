"""ai_navi Avrupa verileri (GitHub Actions'ta çalışır, sonuçlar "veri" sürümüne yüklenir).

Ülke başına dosyalar (telefon yalnız bulunduğu ülkeninkini indirir):
  sarj_XX.txt       şarj istasyonları (OpenStreetMap)
  akaryakit_XX.txt  akaryakıt istasyonları (OpenStreetMap)
  mola_XX.txt       dinlenme tesisi / alanı, çevresindeki yeme-içme ve tuvaletle puanlı (OpenStreetMap)
  fiyat_XX.txt      istasyon başına akaryakıt fiyatı, EUR/L (devletin açık verisi: Fransa, İspanya, İtalya)
Satır biçimleri Türkiye deposuyla (ai_navi-veri) aynıdır; ücretli servis ya da anahtar kullanılmaz.

Kullanım: python scripts/avrupa.py istasyon [DE FR ...] | fiyat
Bir ülke / kaynak başarısız olursa önceki dosyası korunur (yüklenmez).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

CIKTI = Path("out")
UA = "ai_navi-veri-eu/1.0 (+https://github.com/hsynaltunta/ai_navi-veri-eu)"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Avrupa Birliği, EFTA, Birleşik Krallık ve Türkiye'den Avrupa'ya giden yol üstündeki Balkan ülkeleri
ULKELER = ["DE", "AT", "CH", "FR", "IT", "ES", "PT", "NL", "BE", "LU", "GB", "IE", "DK", "SE", "NO", "FI", "IS",
           "PL", "CZ", "SK", "HU", "SI", "HR", "RO", "BG", "GR", "CY", "MT", "EE", "LV", "LT", "LI",
           "RS", "BA", "ME", "MK", "AL", "XK", "MD"]


def log(*a):
    print(*a, flush=True)


def temiz(s: str | None) -> str:
    return (s or "").replace("\n", " ").replace(";", ",").strip()


def http_get(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(query: str, timeout: int = 900) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode()
    son = None
    for url in OVERPASS:
        for _ in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read())
                if "remark" in d and "runtime error" in d["remark"]:
                    raise RuntimeError(d["remark"][:200])
                return d
            except Exception as e:  # sunucu dolu / zaman aşımı: bekleyip yeniden, sonra sıradaki ayna
                son = e
                log(f"  Overpass {url}: {e}")
                time.sleep(30)
    raise RuntimeError(f"Overpass yanıt vermedi: {son}")


def merkez(e: dict):
    if "lat" in e:
        return e["lat"], e["lon"]
    c = e.get("center")
    return (c["lat"], c["lon"]) if c else None


def yaz(ad: str, satirlar: list[str], manifest: dict):
    metin = "\n".join(satirlar) + "\n"
    (CIKTI / ad).write_text(metin, encoding="utf-8")
    manifest["dosyalar"][ad] = {"zaman": int(time.time() * 1000), "sayi": len(satirlar), "boyut": len(metin.encode())}
    log(f"  {ad}: {len(satirlar)} kayıt, {len(metin.encode()) // 1024} KB")


def alan(cc: str) -> str:
    return f'area["ISO3166-1"="{cc}"][admin_level=2]->.a;'


# --- Şarj istasyonları ---

DC_SOKET = ("type2_combo", "ccs", "chademo", "tesla_supercharger", "nacs", "gb_dc")
AC_SOKET = ("type2", "type2_cable", "type1", "schuko", "cee_blue", "cee_red", "type3", "tesla_destination")
KW = re.compile(r"([\d.,]+)\s*(kw|w)?", re.I)


def kw_degeri(s: str) -> float | None:
    m = KW.match(s.strip())
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    if (m.group(2) or "").lower() == "w" or v > 1000:
        v /= 1000
    return v if 0 < v <= 1000 else None


def sarj_satiri(e: dict) -> str | None:
    m = merkez(e)
    if not m:
        return None
    t = e.get("tags", {})
    if t.get("access") in ("private", "no"):
        return None
    soket = [k.split(":")[1] for k in t if k.startswith("socket:") and t[k] not in ("no", "0")]
    ad_metni = f"{t.get('name', '')} {t.get('brand', '')} {t.get('operator', '')}".lower()
    fast = any(s in DC_SOKET for s in soket) or any(w in ad_metni for w in ("supercharger", "ionity", "fastned", "hpc"))
    ac = any(s in AC_SOKET for s in soket)
    guc = [v for k, x in t.items() if (k.startswith("socket:") and k.endswith(":output")) or k == "charging_station:output"
           for v in [kw_degeri(x.split(";")[0])] if v]
    if guc and max(guc) >= 50:
        fast = True
    marka = temiz(t.get("brand") or t.get("operator") or t.get("network"))
    ad = temiz(t.get("name")) or marka or "Charging point"
    if marka and t.get("name") and marka.lower() not in ad.lower():
        ad = f"{marka} • {ad}"
    kw = str(round(max(guc), 1)) if guc else ""
    return f"S;C;{round(m[0], 6)};{round(m[1], 6)};{1 if fast else 0};{1 if (ac or not fast) else 0};{kw};0;{marka};{ad}"


def sarj(cc: str, manifest: dict):
    d = overpass(f'[out:json][timeout:900];{alan(cc)}nwr["amenity"="charging_station"](area.a);out center tags;')
    satirlar = [s for s in (sarj_satiri(e) for e in d.get("elements", [])) if s]
    if not satirlar:
        raise RuntimeError("şarj istasyonu yok")
    yaz(f"sarj_{cc.lower()}.txt", satirlar, manifest)


# --- Akaryakıt istasyonları ---

def akaryakit(cc: str, manifest: dict):
    d = overpass(f'[out:json][timeout:900];{alan(cc)}nwr["amenity"="fuel"](area.a);out center tags;')
    satirlar = []
    for e in d.get("elements", []):
        m = merkez(e)
        if not m:
            continue
        t = e.get("tags", {})
        marka = temiz(t.get("brand") or t.get("operator"))
        ad = temiz(t.get("name") or marka) or "Fuel station"
        lpg = 1 if t.get("fuel:lpg") not in (None, "no", "0") else 0
        satirlar.append(f"S;F;{round(m[0], 6)};{round(m[1], 6)};0;0;;{lpg};{marka};{ad}")
    if not satirlar:
        raise RuntimeError("akaryakıt istasyonu yok")
    yaz(f"akaryakit_{cc.lower()}.txt", satirlar, manifest)


# --- Mola yerleri: otoyol tesisleri ve dinlenme alanları, 300 m çevresindeki yeme-içme / tuvalet / akaryakıtla puanlı ---

class Izgara:
    def __init__(self):
        self.h: dict[tuple[int, int], list] = {}

    def ekle(self, la, lo, deger):
        self.h.setdefault((int(la * 100), int(lo * 100)), []).append((la, lo, deger))

    def yakindakiler(self, la, lo, metre=300):
        dla, dlo = metre / 111_000, metre / 70_000
        ci, cj = int(la * 100), int(lo * 100)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for (pa, po, d) in self.h.get((ci + di, cj + dj), ()):
                    if ((la - pa) / dla) ** 2 + ((lo - po) / dlo) ** 2 <= 1:
                        yield d


def mola(cc: str, manifest: dict):
    d = overpass(f'[out:json][timeout:900];{alan(cc)}nwr["highway"~"^(services|rest_area)$"](area.a)->.s;.s out center tags;'
                 'nwr(around.s:300)["amenity"~"^(restaurant|cafe|fast_food|toilets|fuel)$"];out center tags;')
    tesis, cevre = [], Izgara()
    for e in d.get("elements", []):
        t = e.get("tags", {})
        m = merkez(e)
        if not m:
            continue
        if t.get("highway") in ("services", "rest_area"):
            tesis.append((e, m))
        elif t.get("amenity"):
            cevre.ekle(m[0], m[1], t["amenity"])
    satirlar = []
    for e, m in tesis:
        t = e["tags"]
        tur = "tesis" if t["highway"] == "services" else "dinlenme"
        c = set(cevre.yakindakiler(m[0], m[1]))
        if t.get("toilets") == "yes":
            c.add("toilets")
        restoran, kafe, hizli = "restaurant" in c, "cafe" in c, "fast_food" in c
        yemek = 3 if restoran else 2 if hizli else (1 if tur == "tesis" else 0)
        kahve = 3 if kafe else 2 if (restoran or hizli) else 1 if ("fuel" in c or tur == "tesis") else 0
        dinlenme = 2 + (1 if "toilets" in c else 0)
        parca = [a for a, v in (("restaurant", restoran), ("café", kafe), ("fast food", hizli),
                                ("fuel", "fuel" in c), ("toilets", "toilets" in c)) if v]
        not_ = ", ".join(parca).capitalize()
        ad = temiz(t.get("name") or t.get("brand")) or ("Service area" if tur == "tesis" else "Rest area")
        satirlar.append(f"M;{e['type'][0]}{e['id']};{round(m[0], 6)};{round(m[1], 6)};{tur};{yemek};{kahve};{min(3, dinlenme)};{ad};{temiz(not_)}")
    if not satirlar:
        raise RuntimeError("mola yeri yok")
    yaz(f"mola_{cc.lower()}.txt", list(dict.fromkeys(satirlar)), manifest)


# --- Akaryakıt fiyatları (istasyon başına, EUR/L): P;enlem;boylam;benzin;motorin;lpg ---

def fiyat_satiri(la, lo, benzin, motorin, lpg) -> str | None:
    def f(v):
        return "" if v is None or not (0.3 < v < 5) else f"{v:.3f}"
    if benzin is None and motorin is None and lpg is None:
        return None
    return f"P;{round(la, 6)};{round(lo, 6)};{f(benzin)};{f(motorin)};{f(lpg)}"


def fiyat_fr() -> list[str]:
    """Fransa: prix-carburants (Ekonomi Bakanlığı), anlık akış"""
    z = zipfile.ZipFile(io.BytesIO(http_get("https://donnees.roulez-eco.fr/opendata/instantane")))
    kok = ET.fromstring(z.read(z.namelist()[0]))
    out = []
    for p in kok.iter("pdv"):
        try:
            la, lo = float(p.get("latitude")) / 100000, float(p.get("longitude")) / 100000
        except (TypeError, ValueError):
            continue
        fiyat = {}
        for x in p.iter("prix"):
            try:
                v = float(x.get("valeur"))
            except (TypeError, ValueError):
                continue
            fiyat[x.get("nom")] = v / 1000 if v > 10 else v
        s = fiyat_satiri(la, lo, fiyat.get("E10") or fiyat.get("SP95") or fiyat.get("SP98"), fiyat.get("Gazole"), fiyat.get("GPLc"))
        if s:
            out.append(s)
    return out


def fiyat_es() -> list[str]:
    """İspanya: Ministerio para la Transición Ecológica, akaryakıt istasyonları ve fiyatlar"""
    d = json.loads(http_get("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"))

    def sayi(s):
        try:
            return float((s or "").replace(",", "."))
        except ValueError:
            return None
    out = []
    for e in d.get("ListaEESSPrecio", []):
        la, lo = sayi(e.get("Latitud")), sayi(e.get("Longitud (WGS84)"))
        if la is None or lo is None:
            continue
        s = fiyat_satiri(la, lo, sayi(e.get("Precio Gasolina 95 E5")), sayi(e.get("Precio Gasoleo A")),
                         sayi(e.get("Precio Gases licuados del petróleo")))
        if s:
            out.append(s)
    return out


def fiyat_it() -> list[str]:
    """İtalya: MIMIT (Osservaprezzi carburanti), istasyon listesi + sabah 8 fiyatları"""
    def oku(url):
        metin = http_get(url).decode("utf-8", "replace").splitlines()
        satir = metin[1:] if metin and metin[0].lower().startswith("estrazione") else metin
        ayirici = "|" if satir and satir[0].count("|") > satir[0].count(";") else ";"
        return list(csv.reader(satir[1:], delimiter=ayirici))
    yer = {}
    for r in oku("https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"):
        try:
            yer[r[0]] = (float(r[-2]), float(r[-1]))
        except (ValueError, IndexError):
            pass
    fiyat: dict[str, dict] = {}
    for r in oku("https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"):
        try:
            i, ad, v, self_ = r[0], r[1].lower(), float(r[2]), r[3] == "1"
        except (ValueError, IndexError):
            continue
        tur = "benzin" if ad.startswith("benzina") else "motorin" if ad.startswith("gasolio") else "lpg" if ad == "gpl" else None
        if tur and (self_ or tur not in fiyat.get(i, {})):
            fiyat.setdefault(i, {})[tur] = v
    out = []
    for i, f in fiyat.items():
        if i in yer:
            s = fiyat_satiri(*yer[i], f.get("benzin"), f.get("motorin"), f.get("lpg"))
            if s:
                out.append(s)
    return out


FIYAT = {"fr": fiyat_fr, "es": fiyat_es, "it": fiyat_it}


def main():
    CIKTI.mkdir(exist_ok=True)
    yol = CIKTI / "manifest.json"
    manifest = json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else {"surum": 1, "dosyalar": {}}
    is_ = sys.argv[1] if len(sys.argv) > 1 else "istasyon"
    hata = 0
    if is_ == "fiyat":
        for cc, f in FIYAT.items():
            log(f"Fiyat {cc}...")
            try:
                satirlar = f()
                if len(satirlar) < 500:
                    raise RuntimeError(f"beklenenden az ({len(satirlar)})")
                yaz(f"fiyat_{cc}.txt", satirlar, manifest)
            except Exception as e:
                hata += 1
                log(f"!! fiyat {cc} başarısız (önceki dosya korunuyor): {e}")
    else:
        for cc in (sys.argv[2:] or ULKELER):
            log(f"{cc}...")
            for ad, f in (("şarj", sarj), ("akaryakıt", akaryakit), ("mola", mola)):
                try:
                    f(cc, manifest)
                except Exception as e:
                    hata += 1
                    log(f"!! {cc} {ad} başarısız (önceki dosya korunuyor): {e}")
                time.sleep(5)
    manifest["guncelleme"] = int(time.time() * 1000)
    manifest["ulkeler"] = sorted({k.split("_")[1][:2] for k in manifest["dosyalar"]})
    yol.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Bitti ({hata} hata)")


if __name__ == "__main__":
    main()
