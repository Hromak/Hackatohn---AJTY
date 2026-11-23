# Floorball Mate

Tabletová aplikace pro zapisovatele florbalu: střídání jedním dotekem (AI navrhne další pětku,
zapisovatel potvrdí) a střely klepnutím na hřiště. Data bere ze služby OLC (`hackathon-zapisovatel-api`)
a zápisy jí posílá přes frontu, která funguje i bez připojení.

## Spuštění

```bash
docker compose up -d            # ve složce služby OLC: API na 127.0.0.1:8000, token "demo"
python3 serve.py                # tady: aplikace na http://<IP počítače>:5173
```

Tablet ve stejné Wi-Fi otevře `http://<IP počítače>:5173`. `serve.py` přeposílá `/api/` na službu
(ta je v Dockeru jen na localhostu). Jiná adresa služby: `FM_API=http://host:8000 python3 serve.py`.

## Jak se to používá

Záložky nahoře: **Střely** (hřiště a pětky), **Střídání**, **Zápis** (seznam událostí, Opravit/Smazat)
a **Analýza**.

1. Vyberte utkání. V části Střídání u každého týmu zvolte brankáře (výchozí je první na soupisce).
2. **Čas** (v částech Střely a Střídání): minuty a sekundy, šipky u minut po 1 min, u sekund tlačítka −10/+10 a −1/+1. Časomíra se často
   zastavuje, proto aplikace žádné stopky nemá: po uložení střely se čas posune o +5 s
   (`11:58` → `12:03`); oprava ani zrušení ho neposunou. Střídání berou tentýž čas.
   **Zámek** vedle času zamkne pro danou část střely i střídání; opravy jdou dál v Zápisu (filtr podle části, typu a týmu).
3. **Začátek části:** klepněte na navrženou pětku, nebo „Vybrat hráče ručně…“.
4. **Přesilovka:** tlačítko „Přesilovka“ pod týmem, který ji hraje. Tým v přesilovce hraje v 5,
   soupeř se sám přepne do oslabení ve 4; druhé ťuknutí vrátí vyrovnaný stav. Šest hráčů = hra bez brankáře.
5. **Střídání:** polovina pro každý tým (strany jako na mapě). **Přidat nové střídání** předvyplní hráče, kteří
   právě hrají, a na druhé polovině ukáže sestavy týmu: ťuknutí na hráče tady a pak tam (nebo naopak) je
   prohodí, **Celá sestava** vloží celou řadu. Po ťuknutí na hráče se světle zvýrazní ti, kdo ho v utkání
   nejčastěji střídali (na stejné pozici má přednost; `replacementsFor` v `js/predict.js`). Dole je i
   **brankář** (vybraný je ten, kdo hraje) a **Bez brankáře**; v každém novém střídání je i **místo navíc** – hráč dosazený tam hraje místo brankáře (6 hráčů, v oslabení 5); změna brankáře platí
   i pro střely; když jde do branky druhý brankář, u střídání se ukáže **B**. Brankář ke střídání se ukládá jen v tabletu (API ho nemá). **Zapsat
   střídání** ho uloží v čase z horní lišty. Pod tím střídání zvolené třetiny s **+/−**: nahoře to, které je na hřišti, pak ostatní od nejnovějšího (góly vstřelené minus
   obdržené, dokud byla pětka na hřišti); **Zobrazit další střídání** ukáže všechna, ťuknutí na řádek ho opraví.
   **Upravit řady** (dole pod týmem): celá obrazovka – u domácích řady vlevo, hráči vpravo, u hostů naopak. Ťuknout na hráče a pak na místo (nebo místo a pak hráče) – hráči se prohodí.
   Řady se ukládají jen v tabletu (API formace zapsat neumí), výchozí jsou předvolby trenéra.
6. **Střela (3 ťuknutí):** ťuknutí na hřiště → u prstu menu Gól / Na branku / Tyčka / Mimo → na půlce
   obrazovky soupiska týmu (podle poloviny hřiště): nahoře pětka na hřišti, pod ní ostatní hráči pro
   případ nestihnutého střídání. Druhá půlka přepne na druhý tým. U gólu ještě asistence.
7. **Hlas:** tlačítko mikrofonu vedle „Zamknout“ (zelené = zapnuto). Při zapnutí aplikace zkontroluje
   prohlížeč a rovnou si řekne o povolení mikrofonu. Pak ťuknutí na hřiště spustí poslech: řekněte např.
   „gól devadesát asistence 86“ (pauzy mezi slovy nevadí) – políčka v okénku (tým, výsledek, střelec,
   asistence) se vyplňují **průběžně**, poslech skončí sám 1,8 s po posledním slově. Neznámé číslo je
   červeně, vše jde opravit, a uloží se až tlačítkem **Uložit**. Parser je pravidlový (`js/voice.js`),
   bez AI modelu a bez klíče v prohlížeči.
   **Kde mikrofon funguje:** Chrome nebo Edge, s internetem (rozpoznávání běží na serveru Googlu/Microsoftu),
   jen na `https://` nebo `localhost`. Na PC tedy `http://localhost:5173`. Na tabletu přes `http://IP:5173`
   prohlížeč mikrofon zakáže – buď zrcadlení z PC, nebo v Chrome na tabletu `chrome://flags` →
   „Insecure origins treated as secure“ → přidat `http://IP:5173` → Relaunch.
8. **Analýza** (třetí záložka): mapa za libovolnou část nebo celé utkání, filtry tým / poměr sil /
   výsledek / hráč a souhrn za každý tým (střely, na branku, góly, úspěšnost, podíl ze slotu, průměrná
   vzdálenost, 3 hráči s nejvíc střelami a 3 s nejvíc minutami na hřišti). Minuty se počítají ze střídání:
   hráč je na hřišti od střídání, kterým přišel, do dalšího střídání svého týmu; brankáři se nepočítají. **Slot** = do 8 m od branky a nejvýš 45° z osy – jednoduché pravidlo
   místo xG, protože z jednoho zaznamenaného zápasu xG poctivě spočítat nejde.
9. **Strany** se střídají samy: 1. a 3. část sloupec domácích vlevo, 2. část a prodloužení vpravo. Mapa je otočená tak, aby každý tým střílel směrem od svého sloupce.
   **Prohodit strany** to obrátí, když je hala naopak. Mění se jen zobrazení. Do API jdou souřadnice vždy s domácími útočícími doprava.

Vpravo nahoře je tlačítko **celé obrazovky** (pozná i F11). Stav odesílání se tam ukáže jen když něco čeká nebo bylo odmítnuto: „Vše odesláno“ / „Čeká na odeslání: n“ / „Odmítnuto: n“. Odmítnuté zápisy
zůstávají nahoře v seznamu s českou zprávou z API, dají se opravit nebo poslat znovu.

## AI: co dělá a jak přesná je

`js/predict.js` navrhuje další pětku z předvoleb trenéra a z dosavadních střídání v utkání (novější
mají větší váhu). Nic nezapisuje sama; u každého návrhu ukazuje důvod a podíl. Bez předvoleb se učí od
nuly: po prvních dvou pětkách navrhuje tu, která nejdéle nehrála.

Měření na jediném zaznamenaném zápase (`node eval/eval-predict.js`, 132 střídání):

| | 1. část | 2. část | 3. část | celkem | mezi 3 návrhy |
|---|---|---|---|---|---|
| s předvolbami | 95 % | 38 % | 24 % | 51 % | 61 % |
| bez předvoleb | 81 % | 35 % | 34 % | 49 % | 60 % |

Ve 2. a 3. části trenér skládá nové pětky, které v utkání ještě nebyly; ty přesně předpovědět nejde.

## Testy

```bash
node --test test/*.test.js      # 29 testů, bez sítě
node test/e2e-real.js           # proti běžící službě OLC přes serve.py; RESETUJE utkání 1
node eval/eval-predict.js       # přesnost návrhů
```
