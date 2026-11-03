# ai_navi-veri-eu

ai_navi navigasyon uygulamasının **Avrupa** verileri. Türkiye verileri ayrı depodadır: [ai_navi-veri](https://github.com/hsynaltunta/ai_navi-veri).

Uygulama bulunduğu ülkeye göre depoyu kendisi seçer: Türkiye'de `ai_navi-veri`, Avrupa ülkelerinde bu depo
(ülke bilinmiyorsa telefonun dili: Türkçe ise Türkiye deposu). Yalnız bulunulan ülkenin dosyaları indirilir.

| Dosya | İçerik | Kaynak | Yenileme |
|---|---|---|---|
| `sarj_XX.txt` | Şarj istasyonları | OpenStreetMap (ODbL) | Haftalık |
| `akaryakit_XX.txt` | Akaryakıt istasyonları | OpenStreetMap (ODbL) | Haftalık |
| `mola_XX.txt` | Otoyol tesisleri / dinlenme alanları, puanlı | OpenStreetMap (ODbL) | Haftalık |
| `fiyat_XX.txt` | İstasyon başına akaryakıt fiyatı (EUR/L) | Fransa: prix-carburants.gouv.fr, İspanya: MITECO, İtalya: MIMIT | 6 saatte bir |

Dosyalar [veri sürümünde](https://github.com/hsynaltunta/ai_navi-veri-eu/releases/tag/veri) yayımlanır;
`manifest.json` her dosyanın son güncelleme zamanını içerir. Ücretli servis ya da API anahtarı kullanılmaz.

Map data © OpenStreetMap contributors, ODbL. Fuel prices: open data of the French, Spanish and Italian governments.
