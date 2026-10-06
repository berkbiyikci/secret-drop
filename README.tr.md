# secret-drop

**Gizli anahtarları AI sohbetine yapıştırmadan araçlarına teslim et.**

[English](README.md)

![Demo: ajan anahtar ister, yerel pencere açılır, anahtar hedefe yazılır ve sohbette hiç görünmez](docs/demo-tr.gif)

## Neden var?

Claude Code ve Codex gibi kodlama ajanları bir işi bitirmek için sık sık API anahtarı, OAuth client
secret ya da refresh token ister. Genelde akış şöyle ilerler: ajan "şu komutu çalıştır, anahtarı
yapıştır" der ve anahtar sohbete yapıştırılır. O andan sonra anahtar sohbet kaydında, ajanın
bağlamında ve sağlayıcının ya da kendi araçlarının tuttuğu loglarda durur.

secret-drop anahtarı sohbetten alıp ekranına taşır. Ajan bir komut çalıştırır, makinende yerel bir
şifre penceresi açılır, anahtarı oraya yapıştırırsın. Değer doğrudan gitmesi gereken yere yazılır:
bir env dosyasına, ssh üzerinden bir sunucuya, macOS Anahtar Zinciri'ne ya da kendi komutuna. Ajana
yalnızca değerin **uzunluğu** söylenir; işin olduğunu anlamak için bu yeterli.

<img src="docs/popup-tr.png" width="520" alt="secret-drop penceresi: kilit ikonu, 'STRIPE_SECRET_KEY değerini yapıştır', ipucu satırı ve gizli alan">

## Kurulum

Paket yöneticisi de `curl | sh` da yok. Tek bir Python dosyası; standart kütüphane dışında bağımlılığı
yok (Python 3.9+, macOS'la birlikte geliyor).

```bash
git clone https://github.com/berkbiyikci/secret-drop.git ~/tools/secret-drop
echo 'export PATH="$HOME/tools/secret-drop:$PATH"' >> ~/.zshrc
exec zsh
secret-drop --version
```

Pencere ilk açıldığında macOS, terminalinin (ya da ajanı çalıştıran uygulamanın) **System Events**'i
kontrol etmesine izin verip vermeyeceğini sorar. İzin ver; pencere bu sayede öne gelir.

Mesajlar sistem diline göre seçilir. Türkçe için `~/.config/secret-drop/config` dosyasına
`[settings]` altında `lang = tr` yaz ya da `SECRET_DROP_LANG=tr` tanımla.

## Kullanım

### `ask`: tek anahtar, tek hedef

```bash
secret-drop ask AD HEDEF ["pencerede görünen ipucu"] [--then "komut"]
```

`AD` bir ortam değişkeni gibi olmalı: `^[A-Z][A-Z0-9_]*$`. Pencere 10 dakika sonra kendiliğinden
kapanır. Vazgeçersen, süre dolarsa ya da alanı boş gönderirsen hiçbir şey yazılmaz.

| Hedef | Ne olur |
|---|---|
| `file:<yol>` | Yerel bir env dosyasında `AD=değer` satırını yazar. Diğer satırlar korunur, yazma atomiktir ve dosyanın izni `600` olur. |
| `ssh:<host>:<yol>` | Aynısını uzak makinede yapar. Değer ssh'e **stdin**'den gider, komut satırına hiç girmez. `<host>` için `ssh`'in kabul ettiği her şey olur, `~/.ssh/config`'teki takma adlar dahil. |
| `keychain:<servis>` | macOS giriş anahtar zincirine generic password olarak yazar (servis = `<servis>`, hesap = `AD`). Değer `security -i`'ye stdin'den gider. |
| `exec:<komut>` | Bir shell komutu çalıştırır; değeri **stdin**'den, adı `$SECRET_DROP_NAME` ortam değişkeninden verir. Komutun stdout'u atılır, böylece değeri ajana geri basamaz. |
| `@<ad>` | Config dosyasında tanımlı bir hedef (aşağıda). |

```bash
# yerel .env
secret-drop ask OPENAI_API_KEY file:.env "platform.openai.com → API keys"

# sunucudaki env dosyası, ardından servisi yeniden başlat
secret-drop ask STRIPE_SECRET_KEY ssh:deploy@app.example.com:/srv/app/.env \
  "Stripe Paneli → Geliştiriciler → API anahtarları" \
  --then "ssh deploy@app.example.com sudo systemctl restart app"

# macOS Anahtar Zinciri
secret-drop ask GITHUB_TOKEN keychain:my-scripts

# stdin okuyan her şey, ör. bir GitHub Actions secret'ı
secret-drop ask NPM_TOKEN 'exec:gh secret set "$SECRET_DROP_NAME" --repo me/my-lib'
```

Başarılı olunca `ask` tek satır yazar:

```
STRIPE_SECRET_KEY → @prod yazıldı (uzunluk 107)
```

`--then`, yazma başarılı olduktan sonra çalışır. Değeri hiç görmez; ortamında yalnızca
`$SECRET_DROP_NAMES` ve `$SECRET_DROP_TARGET` bulunur.

### `google-oauth`: kopyala-yapıştırsız refresh token

```bash
secret-drop google-oauth ÖNEK CLIENT_ID "SCOPE'LAR" HEDEF [--no-open] [--reuse-secret] [--then "komut"]
```

**"Desktop app" türündeki bir OAuth istemcisi** için Google izin akışının tamamını yürütür:

1. Client secret'ı pencereden ister. `--reuse-secret` verilirse `ÖNEK_CLIENT_SECRET`'ı hedeften geri
   okur; yeniden izin alırken işe yarar.
2. `127.0.0.1` üzerinde rastgele bir portta tek seferlik bir dinleyici açar; `state` kontrolü ve PKCE
   (S256) kullanır.
3. İzin ekranını tarayıcıda açar. `--no-open` ile adresi `AUTH_URL <adres>` olarak yazdırır; böylece
   istediğin Chrome profilinde açabilirsin.
4. Kodu token'a çevirir ve hedefe `ÖNEK_CLIENT_ID`, `ÖNEK_CLIENT_SECRET` ve `ÖNEK_REFRESH_TOKEN`
   yazar.

```bash
secret-drop google-oauth GMAIL 1234-abc.apps.googleusercontent.com \
  "https://www.googleapis.com/auth/gmail.readonly" @prod --no-open
```

<img src="docs/terminal-tr.svg" alt="secret-drop ask ve google-oauth terminal çıktısı; yalnızca adlar, hedefler ve uzunluklar görünüyor">

### Config dosyası ve adlandırılmış hedefler

Config dosyası `~/.config/secret-drop/config` konumunda durur. `$XDG_CONFIG_HOME/secret-drop/config`
ya da `$SECRET_DROP_CONFIG` ile başka bir yer gösterebilirsin:

```ini
[settings]
# en ya da tr; varsayılan sistem dili
lang = tr
# pencerenin kaç saniye sonra kapanacağı
timeout = 600

[target.prod]
target = ssh:deploy@app.example.com:/srv/app/.env
then = ssh deploy@app.example.com sudo systemctl restart app

[target.local]
target = file:~/projects/app/.env
```

Bu config ile `secret-drop ask STRIPE_SECRET_KEY @prod` değeri sunucuya yazar ve servisi yeniden
başlatır. `secret-drop targets` tanımlı hedefleri listeler; ajan da neyin nereye gideceğini buradan
öğrenir.

| Ortam değişkeni | Anlamı |
|---|---|
| `SECRET_DROP_CONFIG` | Config dosyasının yolu. |
| `SECRET_DROP_LANG` | `en` ya da `tr`. Config'i ve sistem dilini ezer. |
| `SECRET_DROP_TIMEOUT` | Pencerenin zaman aşımı (saniye). |
| `SECRET_DROP_PROMPTER` | Pencere yerine kullanılacak, değeri stdout'a basan bir shell komutu. Ortamında `$SECRET_DROP_NAME` ve `$SECRET_DROP_PROMPT` bulunur. Testler bunu kullanıyor; bir şifre yöneticisi CLI'ına da bağlayabilirsin. |

## Ajanına söyle

Bunu `CLAUDE.md`, `AGENTS.md` ya da ajanının sistem talimatına yapıştır:

```markdown
## Gizli anahtarlar
- Kullanıcıdan API anahtarını, token'ı, şifreyi ya da client secret'ı sohbete yapıştırmasını asla isteme.
- Gerekince `secret-drop ask <AD> <hedef> "<nerede bulunur>"` çalıştır. Kullanıcının ekranında bir
  pencere açılır, değer doğrudan hedefe gider ve sen yalnızca uzunluğunu görürsün.
- Hedefler: `@<ad>` (listesi için `secret-drop targets`), `file:<yol>`, `ssh:<host>:<yol>`,
  `keychain:<servis>`, `exec:<komut>`. Ardından servisi yeniden başlatmak için `--then "<komut>"` ekle.
- Google OAuth refresh token için
  `secret-drop google-oauth <ÖNEK> <client_id> "<scope'lar>" <hedef>` çalıştır.
- Bir anahtarı asla geri yazdırma: anahtar tutan dosyalarda `cat`, `grep` ya da `echo` yok. Anahtarlara
  yalnızca adıyla atıf yap.
```

## Güvenlik

**Neyi korur**

- **Sohbet kaydını ve ajanın bağlamını.** Değer hiçbir zaman yazdırılmaz; yalnızca uzunluğu yazdırılır.
- **Shell geçmişini ve process listesini.** Değer hiçbir zaman komut satırına girmez. `ssh`'e,
  `security`'ye ve `exec:` komutlarına stdin'den gider; bu yüzden ne `ps`'te ne de `~/.zsh_history`'de
  görünür.
- **Diskteki dosyaları.** Env dosyaları yerelde de uzakta da atomik olarak ve `600` izniyle yazılır.
- **Yapıştırmadan önceki hataları.** Pencere açılmadan önce ad ve hedef doğrulanır, ssh bağlantısı
  denenir. Böylece kimse anahtarı çıkmaz bir yola yapıştırmaz.
- **OAuth yönlendirmesini.** Yalnızca loopback'te dinler, `state`'i kontrol eder, PKCE kullanır ve
  başıboş istekleri yok sayar.

**Neyi korumaz**

- **Makinene ya da hedefe zaten erişimi olan birini.** Env dosyaları ve anahtar zinciri, sahibi olan
  hesap kadar güvenlidir.
- **Ajanın sonradan hedefi okumasını.** Dosya ya da shell erişimi olan bir ajan yine `cat .env`
  çalıştırabilir. Yukarıdaki talimat bloğu bir kuraldır, zorlayıcı bir mekanizma değildir. Bu senin
  için önemliyse ajanının izin kurallarıyla birleştir (ör. `.env` dosyalarını okumayı yasakla).
- **Panoyu.** Kopyala-yapıştır panodan geçer; pano geçmişi tutan uygulamalar bir kopyasını saklar. Bu
  uygulamaları hariç tut ya da geçmişi temizle.
- **Senin yazdığın komutları.** `exec:` ve `--then` ne verirsen onu çalıştırır.
- **Odağı.** Pencere açılınca klavye odağını alır. O sırada başka bir yere yazıyorsan tuşların gizli
  alana düşer. Yapıştırmadığın noktalar görürsen vazgeç.

## Platformlar

macOS'ta test edildi. Linux'ta, kuruluysa `zenity` ya da `kdialog` kullanır. Bu yol **deneysel ve test
edilmedi**; `keychain:` hedefi yalnızca macOS'ta çalışır.

## Geliştirme

```bash
python3 -m unittest discover -s tests                            # GUI gerekmez
SECRET_DROP_TEST_KEYCHAIN=1 python3 -m unittest discover -s tests  # giriş anahtar zincirine de yazar, sonra temizler
python3 docs/make_screenshots.py                                 # docs/ görsellerini yeniden üretir
```

Testlerde pencerenin yerini `SECRET_DROP_PROMPTER` alır. `PATH`'e sahte bir `ssh` konur; bu `ssh` uzak
scripti yerelde çalıştırır ve değerin argv'de olmadığını kanıtlamak için argv'sini kaydeder. OAuth
akışı, PKCE doğrulayıcısını kontrol eden yerel bir sahte token servisine karşı çalışır.

**Görseller nasıl üretildi?** `docs/make_screenshots.py` gerçek pencereyi sahte bir değer önceden
doldurulmuş halde açar ve yalnızca o pencereyi `screencapture -l` ile yakalar. Terminal SVG'lerini
gerçek CLI çıktısından üretir; bu çıktı aynı sahte `ssh` ve sahte bir Google token servisiyle alınır.
Bu yüzden hiçbir yerde gerçek bir anahtar, sunucu ya da hesap görünmez. Demo GIF'i
[Remotion](https://www.remotion.dev) ile render edildi.

## Lisans

MIT
