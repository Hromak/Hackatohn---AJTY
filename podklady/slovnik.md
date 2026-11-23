# Slovník

Pojmy, které v zadání a v API potkáte. Jak hra v hale skutečně probíhá, se nejlíp dozvíte od
někoho, kdo zapisoval – ptejte se mentorů.

| Pojem | Co znamená | V API |
|---|---|---|
| **Zápis o utkání** | Úřední záznam zápasu. Vzniká v hale během hry, dnes ve FIS. | – |
| **Zapisovatel** | Člověk u stolku vedle hrací plochy, který zápis vede. Často rodič nebo hráč jiného týmu, bez školení. | – |
| **Domácí / hosté** | Dva týmy utkání. Domácí je v zápisu první. | `home` / `away` |
| **Soupiska utkání** | Hráči, kteří k utkání nastoupili: číslo dresu, jméno, post. | `GET …/roster` |
| **Post** | Brankář, obránce, útočník. | `G`, `D`, `F` |
| **Třetina** | Hrací část. Utkání má tři po dvaceti minutách. | `period` 1–3 |
| **Prodloužení** | Čtvrtá, kratší část, když je po třetinách nerozhodně. Hraje se v menším počtu hráčů. | `period` 4 |
| **Čas utkání** | Čas na časomíře v hale: minuty a sekundy od začátku hrací části. Není to čas na hodinách. | `time`, `"mm:ss"` |
| **Formace, řada, pětka** | Pět hráčů v poli, kteří chodí na hřiště společně: levé křídlo, center, pravé křídlo, levý a pravý obránce. Tým mívá tři. | `GET …/formations`, `lw` `c` `rw` `ld` `rd` |
| **Střídání** | Výměna hráčů na hřišti, většinou celé pětky najednou, zhruba každou minutu a za hry. | `type: "substitution"` |
| **Přesilovka** | Tým má na hřišti víc hráčů než soupeř, protože soupeř má vyloučeného. | `strength: "power_play"` |
| **Oslabení** | Opak: tým hraje bez vyloučeného hráče, ve čtyřech nebo ve třech. | `strength: "short_handed"` |
| **Hra bez brankáře** | Tým odvolá brankáře a pošle místo něj šestého hráče do pole. | `empty_net: true` |
| **Střela** | Pokus o gól. Zapisuje se odkud, kdo, jak dopadla a kdy. | `type: "shot"` |
| **Výsledek střely** | Mimo branku, na branku (brankář chytil), do tyčky, gól. | `miss`, `on_goal`, `post`, `goal` |
| **Asistence** | Přihrávka, po které padl gól. | `assist_id` |
| **Výměna stran** | Týmy si po třetině mění poloviny hřiště. Souřadnice v API se tím nemění. | viz README, Hřiště a souřadnice |
