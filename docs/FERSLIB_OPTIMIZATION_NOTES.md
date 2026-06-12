# ferslib — Note di ottimizzazione (analisi del codice)

**Data:** 2026-06-09
**Scope:** analisi delle problematiche di *performance/throughput* nel codice di `ferslib`
(la libreria C di interfaccia ai sistemi FERS). **Solo prestazioni** — non stile, non sicurezza.
**Vincolo del progetto:** `ferslib` resta **invariata**. Questo documento serve a:
1. capire quali limiti stanno *sotto* `pyferslib` e che HydraFERS **non può** rimuovere;
2. capire cosa HydraFERS **può aggirare** con scelte architetturali a monte;
3. eventualmente fornire feedback a chi mantiene `ferslib` (CAEN) per migliorie future.

File analizzati (in `ferslib/src/`): `FERS_readout.c` (2042), `FERSlib.c` (3096),
`FERS_LLeth.c` (905), `FERS_LLusb.cpp` (1608), `FERS_LLtdl.c` (1825).

---

## 0. Sintesi esecutiva — la scoperta principale

Il throughput di `ferslib` è limitato soprattutto da **due fatti architetturali**, non da micro-inefficienze:

### (A) Tutto il lavoro pesante di readout gira nel thread del *consumatore*
I thread interni di `ferslib` (uno per board/concentratore nei livelli LL) fanno **solo** il
trasferimento grezzo *socket/USB → RxBuff*. Tutto il resto — riassemblaggio dei byte, decodifica,
push/pop nelle code, **sorting** ed **event building** — avviene **dentro `FERS_GetEvent`**, cioè nel
thread di chi chiama ([FERS_readout.c:1823](ferslib/src/FERS_readout.c#L1823); `eth_usb_ReadRawEvent`
è invocata *dentro* GetEvent a [riga 1849](ferslib/src/FERS_readout.c#L1849) e
[1964](ferslib/src/FERS_readout.c#L1964)).

> **Conseguenza per HydraFERS:** è esattamente questo che amplificava il collo di bottiglia
> single-thread di JanusC. Il `ReadoutThread` di HydraFERS che chiama `drain_events`/`GetEvent` **è**
> il thread che paga decode+sort. Mitigazione possibile (vedi §6): un thread dedicato che fa *solo*
> `GetEvent` e scarica su coda, così il costo di decodifica non è in serie con scrittura su disco e
> statistiche. Non possiamo spostare il decode fuori dal nostro processo, ma possiamo isolarlo.

### (B) Ogni evento viene copiato ~5 volte dal filo alla struct decodificata
Catena di copie per singolo evento:
`socket → RxBuff` (thread LL) → `RxBuff → LLBuff` (memcpy in `LLxxx_ReadData`) →
`LLBuff → EvBuff` (riassemblaggio byte nel decode) → `EvBuff → queue` (`q_push`,
[memcpy riga 127](ferslib/src/FERS_readout.c#L127)) → `queue → tmp_event` (`q_pop`,
[memcpy riga 146](ferslib/src/FERS_readout.c#L146)) → `tmp_event → SpectEvent_t` (`FERS_DecodeEvent`).

> **Conseguenza per HydraFERS:** è interno a `ferslib`, **non rimovibile** da noi. Definisce un tetto
> di CPU per evento. Da tenere presente nei benchmark: la banda massima reale è quella che questa
> pipeline regge, non quella del solo link fisico.

Il resto del documento elenca le inefficienze concrete, raggruppate per file, con `file:riga`,
severità, impatto e — dove rilevante — **cosa può fare HydraFERS**.

Legenda severità (dal punto di vista del throughput di acquisizione):
**ALTA** = sul data-plane ad alto rate · **MEDIA** = latenza/CPU su monitoraggio o setup ripetuto ·
**BASSA** = solo su path rari (firmware upgrade, init una tantum).

---

## 1. `FERS_readout.c` — il cuore del readout (impatto maggiore)

| # | Punto | Sev. | Problema | Perché pesa | HydraFERS |
|---|---|---|---|---|---|
| R1 | [1823](ferslib/src/FERS_readout.c#L1823)/[1849](ferslib/src/FERS_readout.c#L1849)/[1964](ferslib/src/FERS_readout.c#L1964) | **ALTA** | Decode + sort + event-building eseguiti nel thread del chiamante di `FERS_GetEvent`, non in un thread interno | Serializza CPU di decodifica con qualunque cosa faccia il consumatore (in JanusC: disco + plot) | Isolare `GetEvent` in un `ReadoutThread` dedicato che fa *solo* quello (§6) |
| R2 | [127](ferslib/src/FERS_readout.c#L127), [146](ferslib/src/FERS_readout.c#L146) | **ALTA** | `q_push`/`q_pop` fanno una `memcpy` completa dell'evento in ingresso e in uscita dalla coda | 2 copie per evento *in aggiunta* alle altre della catena (§0-B) | Non rimovibile (interno). Solo da contabilizzare nei limiti |
| R3 | [1845](ferslib/src/FERS_readout.c#L1845) (`!q_busy`) + [133-136](ferslib/src/FERS_readout.c#L133) | **ALTA** | Flag globale `q_busy`: se **una** coda è piena, il riempimento di **tutte** le code si ferma | Head-of-line blocking in modalità *sorted*: una board lenta blocca tutte | In sorted mode dimensionare bene il buffer a valle; preferire unsorted + sorting nostro se diventa critico |
| R4 | [1881-1895](ferslib/src/FERS_readout.c#L1881) | MEDIA | Ricerca del timestamp più vecchio = scansione lineare O(NumBoard) **per evento** | Costo per-evento che cresce col numero di board; con molte board non banale | Irrilevante per poche board; per molte, valutare sorting nostro a valle |
| R5 | [195-204](ferslib/src/FERS_readout.c#L195) (`get_d32`) | MEDIA | Branch su ogni parola a 32 bit per gestire il wrap del ring buffer | Un branch per ogni word di ogni evento durante il decode | Non rimovibile (interno) |
| R6 | [659-669](ferslib/src/FERS_readout.c#L659) | **ALTA** | In `tdl_ReadRawEvent`, se un evento è spezzato tra due read, busy-loop con `Sleep(1)` fino a **5000 iterazioni (5 s)** | Gira nel thread del consumatore → stalla `GetEvent` fino a 1 ms (e in patologia molto di più) per evento frammentato | Isolando GetEvent (§6) lo stallo non blocca disco/stat; non eliminabile internamente |
| R7 | [1855-1864](ferslib/src/FERS_readout.c#L1855) | MEDIA | Path "no data" basato su contatore di polling con timeout (`FERSLIB_QUEUE_TIMEOUT_MS`), ritorna 0 e il chiamante deve rifare polling | Niente blocking/condvar: il consumatore gira a vuoto quando non ci sono dati | Nel `ReadoutThread` gestire il "0 eventi" con attesa adattiva, non spin |
| R8 | [1428-1479](ferslib/src/FERS_readout.c#L1428) | OK | `malloc` di tutti i buffer (LLBuff, EvBuff, code, waveform) | — | **Positivo**: allocazioni solo in `InitReadout`, **non** sul path per-evento |

**Nota:** la decodifica per-evento **non alloca** (usa `EvBuff`/`tmp_event` statici): bene. Il problema
non è la memoria ma le copie multiple (§0-B) e la collocazione del lavoro (R1).

---

## 2. `FERS_LLeth.c` / `FERS_LLusb.cpp` / `FERS_LLtdl.c` — livelli di trasporto

I tre livelli condividono lo stesso schema (thread ricevente per board che fa `recv`/`read` in
`RxBuff`, consumato poi da `LLxxx_ReadData`). Le inefficienze sono quindi simili e ricorrenti.

| # | Punto | Sev. | Problema | Perché pesa | HydraFERS |
|---|---|---|---|---|---|
| L1 | eth [430-529](ferslib/src/FERS_LLeth.c#L430), usb ~1088-1207, tdl ~1066-1073 | **ALTA** | Mutex tenuto attraverso le syscall di I/O (`select`/`recv`) nel main loop del thread ricevente | Serializza I/O e accesso ai buffer: il consumatore si blocca sul lock durante le socket op | Interno, non rimovibile |
| L2 | eth [595-609](ferslib/src/FERS_LLeth.c#L595), usb/tdl analoghi | **ALTA** | Scrittura raw data con `fwrite` **+ `fflush`** dentro il thread ricevente, sotto lock | `fflush` forza I/O disco sincrono: ogni blocco aspetta il disco (1-10 ms) | **Non usare** il raw-save interno di ferslib sul path ad alto rate; gestire la scrittura nel nostro `WriterThread` bufferizzato |
| L3 | eth ~490/521, usb ~1156/1186, tdl ~1029/1069 | MEDIA | `Sleep(10)`/`Sleep(1)` fissi nei loop dei thread riceventi | Latenza artificiale 1-10 ms per ciclo quando i dati sono disponibili | Interno; mitigato da buffer a valle ampio |
| L4 | eth ~573-576, usb/tdl analoghi | MEDIA | Polling a tempo ogni 10 ms del flag `WaitingForData` invece di semaforo/condvar | ~5 ms di latenza media per richiesta dati | Interno |
| L5 | eth [435](ferslib/src/FERS_LLeth.c#L435), tdl ~973 | MEDIA | Timeout di `select()` fisso a 100 ms | Picchi di latenza fino a 100 ms quando i dati arrivano a fine finestra | Interno |
| L6 | eth `ETH_BLK_SIZE=1024` vs `RX_BUFF_SIZE` (MB) | MEDIA | Blocco di `recv` piccolo (1 KB) rispetto al buffer RX | Tanti switch di buffer → più sync/context switch; possibile mancato utilizzo banda di rete | Interno; verificare in benchmark se è il limite reale su Eth |
| L7 | tcp: nessun `TCP_NODELAY` / nessun tuning `SO_RCVBUF` evidente | MEDIA | Nagle non disabilitato, socket buffer non aumentato | Aumenta latenza e può limitare il throughput su rete | Interno (a livello socket di ferslib) |
| L8 | usb [356-358](ferslib/src/FERS_LLusb.cpp#L356), [394-396](ferslib/src/FERS_LLusb.cpp#L394), 780-782, 813-815 | MEDIA | `stream_enable(true)` inviato in loop **10 volte** | 10× overhead di comando USB / banda sprecata al setup acquisizione | Interno |
| L9 | usb [471-530](ferslib/src/FERS_LLusb.cpp#L471) | MEDIA | `read_pipe` con `try_to_lock`: ritorna subito con 0 byte se il lock è occupato → il chiamante fa busy-wait a livello superiore | CPU sprecata in spin quando l'accesso ai registri interferisce col readout | Interno |
| L10 | usb [499](ferslib/src/FERS_LLusb.cpp#L499) | BASSA | `std::vector::erase(begin, begin+n)` sui "leftover": O(n), ricopia il resto | CPU per-read quando i leftover si accumulano | Interno |
| L11 | tdl ~1189/1236 | MEDIA | `while (trylock(...));` spin senza yield aspettando il mutex | 100% di un core sotto contesa | Interno |
| L12 | tdl [495-516](ferslib/src/FERS_LLtdl.c#L495), 614-637, 667-691 | MEDIA | Retry R/W registri (`TDL_RW_MAX_ATTEMPTS=10`) senza backoff | Le op su registro durano 10× se i timeout sono frequenti | Interno (control-plane) |
| L13 | tdl ~1118 | BASSA | `RxBuff_wp` aggiornato fuori dal lock | Possibile race/lettura stantia sotto contesa (correttezza, non solo perf) | Interno — segnalare a CAEN |

**Punto operativo più importante di questa sezione (L2):** il salvataggio raw integrato in `ferslib`
fa `fflush` per blocco dentro il thread di ricezione. **HydraFERS non deve appoggiarsi a quel
meccanismo per il path ad alto rate**: la scrittura va fatta nel nostro `WriterThread` bufferizzato
(grandi scritture sequenziali), come già previsto nel feasibility study.

---

## 3. `FERSlib.c` — core (per lo più control-plane: HV, I2C, firmware)

Queste inefficienze stanno quasi tutte su path di **controllo/monitoraggio/firmware**, non sul
data-plane. Pesano sulla **latenza** (es. lettura HV/temperature durante l'acquisizione) e sulla
durata degli upgrade, non sulla banda eventi.

| # | Punto | Sev. | Problema | Perché pesa | HydraFERS |
|---|---|---|---|---|---|
| C1 | [1274-1277](ferslib/src/FERSlib.c#L1274) (`Wait_i2c_busy`) | MEDIA | Polling I2C con `Sleep(1)` fisso, fino a 50 iterazioni | +1 ms per chiamata anche se l'HW finisce in µs; chiamata molte volte per ogni accesso HV/I2C | Leggere HV/temperature a **bassa frequenza** dal `ServiceThread`, mai nel loop dati |
| C2 | [2208-2214](ferslib/src/FERSlib.c#L2208) (`FERS_HV_ReadReg`) | MEDIA | Loop di 5 retry, ognuno con 2× `Wait_i2c_busy` → worst case ~500 ms per lettura HV | Se chiamata in un loop di acquisizione, la blocca | Campionare HV con cadenza ~1 Hz, fuori dal data-plane |
| C3 | [1386-1389](ferslib/src/FERSlib.c#L1386) | BASSA | `malloc`/`free` di un singolo `uint32_t` per ogni lettura I2C/EEPROM | Overhead allocatore per-registro (init/calibrazione) | Interno |
| C4 | [2571-2580](ferslib/src/FERSlib.c#L2571) (`waitFlashfree`) | BASSA | Polling flash con `Sleep(1)` fino a 300 iter (300 ms) | +300 ms per op flash (solo firmware) | Path raro |
| C5 | [2597-2605](ferslib/src/FERSlib.c#L2597) | BASSA | Buffer 8192 azzerato interamente a ogni chunk in upgrade FW | ~64M scritture a zero per FW da 4 MB | Path raro |
| C6 | [2688-2698](ferslib/src/FERSlib.c#L2688) | BASSA | Triplo loop annidato con `Sleep(5)` in verifica CRC FW: worst case ~10 s | Upgrade molto lento | Path raro |
| C7 | [2440-2461](ferslib/src/FERSlib.c#L2440) | BASSA | Loop doppio incondizionato nello scrivere i coefficienti HV (sembra retry, ma duplica sempre) | Raddoppia la latenza di setup coefficienti | Control-plane |
| C8 | [2539-2542](ferslib/src/FERSlib.c#L2539), [2720-2726](ferslib/src/FERSlib.c#L2720) | BASSA | Loop di polling **senza** `Sleep` (TDC measurement, param FW) | Spin a 100% CPU mentre aspetta l'HW | Control-plane |
| C9 | [697-706](ferslib/src/FERSlib.c#L697) | BASSA | `Sleep(1)` ×4 nello scrivere i DC offset all'apertura device | +4 ms per board allo startup | Path una tantum |

---

## 4. Cosa significa per i limiti di banda di HydraFERS

- Il **tetto di throughput** non è il link fisico ma la pipeline interna di `ferslib`:
  copie multiple per evento (§0-B) + decode/sort nel thread chiamante (R1) + lock attraverso I/O nei
  thread LL (L1). Questi **non sono rimovibili** mantenendo `ferslib` invariata.
- Quello che HydraFERS **può** fare per avvicinarsi a quel tetto:
  1. **Isolare `GetEvent`/`drain_events` in un `ReadoutThread` dedicato** (R1, R6, R7) così il costo di
     decodifica non è in serie con disco e statistiche.
  2. **Non usare il raw-save interno di ferslib** sul path ad alto rate (L2): scrivere noi, bufferizzato,
     in un `WriterThread`.
  3. **Usare `drain_events`** (batch) per ridurre il numero di attraversamenti del confine Python↔C
     (questo è un limite di `pyferslib`, non di `ferslib`, ma si combina).
  4. **Leggere HV/temperature a bassa frequenza** in un `ServiceThread` (C1, C2): mai nel data-plane.
  5. In *sorted mode*, **dimensionare bene il buffer a valle** per assorbire l'head-of-line blocking di
     `q_busy` (R3); se diventa critico con molte board, valutare *unsorted mode* + sorting fatto da noi.

## 5. Cosa segnalare a CAEN (migliorie lato `ferslib`, fuori scope per noi)
Priorità per impatto sul throughput:
1. **Spostare decode/sort in un thread interno** (o offrire una API che restituisca eventi già
   decodificati da un thread di servizio) — risolve R1 alla radice.
2. **Ridurre le copie** della catena (§0-B): es. decodificare direttamente da `RxBuff`.
3. **`fwrite` senza `fflush` per blocco** e su thread separato nel raw-save (L2).
4. **Lock più fini** nei thread LL: non tenere il mutex attraverso `select`/`recv` (L1).
5. **`TCP_NODELAY` + `SO_RCVBUF` tuning** e blocchi `recv` più grandi su Ethernet (L6, L7).
6. Sostituire i **`Sleep` di polling** con primitive bloccanti/condvar (L3, L4, R6, C1).

## 6. Pattern di mitigazione raccomandato (riepilogo per l'engine)
```
LL rx-threads (ferslib)         ReadoutThread (HydraFERS)      WriterThread        StatsThread
 socket → RxBuff        →   drain_events()  →  bounded queue  →  EventWriter      (sample ~15 Hz)
 (interno, non ns.)         (SOLO questo:      (assorbe i picchi  (buffer 4 MiB,    rates+histo,
                            paga decode/sort   e gli stalli R6)   grandi write)     no blocco readout)
                            R1/R6, niente
                            disco/stat qui)                       ServiceThread: HV/temp ~1 Hz (C1/C2)
```
Questo non elimina i limiti interni di `ferslib`, ma garantisce che HydraFERS **non ne aggiunga di
propri** e che decode, disco, statistiche e monitoraggio HV non si blocchino a vicenda — l'esatto
errore di JanusC.

---

*Metodo: analisi statica del codice. Le righe di `FERS_readout.c` sono verificate direttamente; le
righe dei livelli LL e di `FERSlib.c` provengono da una lettura sistematica dei rispettivi file e
vanno considerate accurate al blocco di codice indicato. Nessun file di `ferslib` è stato modificato.*
