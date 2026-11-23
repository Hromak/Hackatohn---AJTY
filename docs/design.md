# Návrh a rozhodnutí

Proč služba vypadá tak, jak vypadá. Podrobnosti chování jsou v [README](../README.md)
a v [`openapi.json`](openapi.json); tady jsou důvody.

## K čemu služba je

Týmy na hackathonu staví dotykové rozhraní pro zapisovatele florbalového utkání a předvádějí
**své aplikace**. Tahle služba jim jen dává data (utkání, soupisky, předvolby formací) a sbírá,
co zapsaly (střely a střídání).

Stojí samostatně, mimo informační systém Českého florbalu (FIS). Data ale mají jeho tvar
a pravidla, aby povedené rozhraní šlo později na FIS napojit: stačí stejný kontrakt
implementovat nad ním.

## Co služba dělá a co ne

Dělá: čtení utkání, částí, soupisek, formací a číselníků; zápis, opravu a smazání střel
a střídání; oddělení týmů tokenem.

Nedělá: tresty, timeouty, nájezdy, vlastní góly, trestná střílení, statistiky, přihlašování
zapisovatele, úpravu soupisek, push ani WebSocket.

## Rozhodnutí

**Jedna operace `PUT` s UUID od klienta pro vytvoření i opravu.** Zapisovatel pracuje v hale
se špatnou wifi. Aplikace proto musí umět poslat událost znovu, aniž ví, jestli první pokus
dorazil. Když identifikátor události určí klient a opakování se stejným obsahem nic nezmění,
duplicita vzniknout nemůže a oprava je vždy úprava původní události. Zvažovaná alternativa –
`POST` pro vytvoření a zvláštní klíč proti duplicitám – by znamenala dvě cesty a víc míst, kde
se dá splést.

**Pořadí vyhodnocení `PUT`:** nejdřív tvar a pravidla těla (422); pak smazaná → 410; jiný typ → 422; stejný obsah → beze změny (i když
poslaná `version` nesedí – je to opakované doručení požadavku, jehož odpověď se ztratila);
jiný obsah a zastaralá `version` → 409; jinak úprava.

**Smazání je konečné.** Opožděné opakování z fronty by jinak mohlo smazanou událost oživit.
„Vrátit smazání“ je nová událost. Vyprázdnění utkání (`reset`) naopak události odstraní
doopravdy, aby šlo utkání použít znovu se stejnými identifikátory.

**Střídání je sestava, ne dvojice odchází/přichází.** Tak ho drží FIS a tak se v hale i děje:
mění se celá pětka. Kdo přišel a kdo odešel, dopočítá služba při čtení proti předchozímu
střídání téhož týmu, takže po opravě dřívějšího střídání zůstávají rozdíly správně.

**Pevná orientace hřiště.** Domácí útočí po celé utkání doprava. Kdyby se souřadnice řídily
tím, kde týmy v hale stojí, data ze dvou třetin by nešla sečíst a po výměně stran by se
zrcadlily i starší střely. Služba střelu z vlastní poloviny neodmítá (stává se), ale označí ji
upozorněním, takže převrácená třetina je hned vidět.

**Čas jako `period` + `"mm:ss"`.** Tak ho ukazuje časomíra a tak ho zapisovatel čte. Čas
z hodin tabletu by se s časem utkání rozcházel při každém přerušení hry.

**Pravidla převzatá z praxe.** Tým nemůže mít dvě střídání ve stejném čase; brankář do
sestavy v poli nepatří; šest hráčů v poli jen při hře bez brankáře; prodloužení je kratší.
Pravidla jsou ověřená přehráním celého skutečného zápasu (viz
`sample-data/full-match-events.json` a `tests/test_demo_replay.py`).

**Každá chyba má stejný tvar a stabilní kód.** Aplikace podle kódu rozhodne, co s událostí
udělá (zkusit znovu, ukázat zapisovateli, zahodit), a člověku ukáže českou větu.

**Vynucená chyba.** Aplikace se má zachovat rozumně, i když API zápis odmítne nebo
neodpovídá. Přepínač, který takové chování vyvolá, je proto součást služby.

**SQLite a jeden proces.** Jednotky týmů, desítky událostí za minutu. Jeden soubor se snadno
zálohuje a služba se dá pustit jedním příkazem i na notebooku.

**Popis API a vzorová data se generují z kódu.** Test hlídá, že nejsou zastaralé, takže
dokumentace se nemůže rozejít s chováním.

## Co je v kontraktu navíc proti dnešnímu FIS

Výsledek střely `miss` (mimo), příznak hry bez brankáře, hráči na hřišti při gólu,
identifikátor události od klienta a verze události. Při napojení na FIS bude potřeba tyto věci
dořešit.

**Limity chrání týmy navzájem.** Token, který se už jednou ověřil, má vlastní rozpočet
požadavků a nejvýš čtyři rozpracované požadavky najednou. Všechno ostatní – požadavky bez
tokenu, s neznámým tokenem, statické stránky – sdílí jeden malý rozpočet. Nikdo bez platného
tokenu tak nemůže vyčerpat rozpočet týmu ani celé služby, a jeden tým nezahltí ostatní.

## Zabezpečení

Token na tým (v databázi jen jeho otisk), každý tým vidí jen svá utkání a cizí utkání vypadá
stejně jako neexistující. Vstupy se kontrolují přísně (typy, rozsahy, žádná neznámá pole),
velikost a počet požadavků jsou omezené, chyby neprozrazují vnitřnosti. Služba drží jen herní
data utkání a soupisky z veřejných zápisů.
