# Studio di Fattibilità — Rinnovo del software di acquisizione FERS / Janus

**Data:** 2026-06-05
**Autore:** analisi tecnica preliminare
**Scope:** valutare la fattibilità del rinnovo completo del software di acquisizione per i sistemi FERS (DT5202 / Janus), mantenendo invariata `ferslib`, completando `pyferslib`, eliminando `JanusC` come processo separato e ricostruendo la GUI con un framework moderno.

---

## 1. Sintesi esecutiva

Il rinnovo è **fattibile** e, dal punto di vista architetturale, **fortemente consigliato**. L'analisi del codice attuale conferma che le criticità segnalate (banda limitata, multithreading mal fatto, scritture su disco continue, plotting con gnuplot, GUI tkinter, comunicazione via socket fragile) sono **reali e identificabili nel codice**, non impressioni soggettive.

Il punto fondamentale emerso dall'analisi: **`ferslib` non è il collo di bottiglia**. La libreria C ha già al suo interno un sistema di readout multithread con buffer e code di sorting (`FERS_readout.c`). Il collo di bottiglia è **`JanusC`**, il cui main loop di acquisizione è **single-thread**: legge un evento, aggiorna le statistiche, scrive su disco e fa il plot — tutto sequenzialmente nello stesso ciclo. Questo serializza I/O di rete, elaborazione e I/O su disco, che è esattamente ciò che limita la banda effettiva.

Eliminare `JanusC` e ricostruire la pipeline con un disegno multithread corretto risolve il problema alla radice.

---

## 2. Architettura attuale (stato di fatto)

```
┌─────────────────────┐   TCP socket :50007    ┌──────────────────────┐
│  GUI Python/tkinter │ <───────────────────>  │   JanusC.exe (C)     │
│  (server)           │   protocollo custom    │   (client)           │
│  - lancia JanusC    │   header 2 byte +      │   - main loop ACQ    │
│  - parse risposte   │   primo char = tipo    │   - statistiche      │
└─────────────────────┘                        │   - scrittura file   │
                                               │   - plot via gnuplot │
                                               └──────────┬───────────┘
                                                          │ ferslib (C)
                                                  ┌───────▼────────┐
                                                  │   ferslib      │
                                                  │  readout thread│
                                                  │  + code sorting│
                                                  └───────┬────────┘
                                                          │
                                                    [ Hardware FERS ]
                                                  (Eth / USB / TDLink)
```

### Punti chiave riscontrati nel codice

- **Comunicazione GUI↔JanusC**: socket TCP su `localhost:50007`. Protocollo custom non documentato: messaggi con 2 byte di header (dimensione) e primo carattere come discriminatore di tipo (`m`=log, `a`=acq status, `S`=stat, `h`=HV, `i`=info, `w`=warning, `Q`=quit...). Comandi GUI→JanusC come caratteri singoli (`S`, `V0/V1`, `q`, `U`...). Riferimenti: [socket2daq.py](janus-5202/gui/socket2daq.py), [console.c](janus-5202/src/console.c).
- **La socket NON trasporta i dati di acquisizione**: trasporta solo statistiche aggregate, log e comandi. I dati raw li scrive JanusC direttamente su file. Questo è cruciale per la valutazione di banda (§4).
- **Main loop single-thread**: in [JanusC.c:1970](janus-5202/src/JanusC.c#L1970) il ciclo `while (!Quit ...)` fa in sequenza: check comandi → `FERS_GetEvent` → update statistiche → scrittura list file → plot. Nessuna separazione tra consumo eventi e I/O.
- **Scritture su disco inline**: `fwrite`/`fprintf` chiamate dentro il loop di consumo eventi ([outputfiles.c](janus-5202/src/outputfiles.c)), con split automatico in subrun. Su rate alti questo blocca il consumo degli eventi.
- **Plotting via gnuplot esterno**: processo separato lanciato con `popen`, comandi inviati via `fprintf(plotpipe, ...)` ([plot.c](janus-5202/src/plot.c)). Lento, fragile, esterno alla GUI.
- **pyferslib incompleto**: pybind11 già configurato ma copre solo 5 funzioni (`open_device`, `get_board_info`, `close_device`, `init_tdl_chains`, `tdl_chains_initialized`). Manca tutto il resto ([pyfers.cpp](pyferslib/python/pyfers.cpp)).

---

## 3. Architettura proposta

Il lato Python è organizzato in **livelli netti** (dettaglio completo in §5). Dal basso verso l'alto:

```
┌───────────────────────────────────────────────────────────────────────┐
│                       Applicazione HydraFERS                            │
│                                                                         │
│  ┌──────────────────────────┐   stats queue   ┌──────────────────────┐ │
│  │ hydrafers.core (Engine)  │ ──────────────> │ Frontend             │ │
│  │  thread READOUT          │   stato/stats   │  GUI PySide6 (plot    │ │
│  │  thread WRITER           │ <────────────── │   embedded pyqtgraph) │ │
│  │  thread STATS            │   comandi       │  CLI/TUI Textual      │ │
│  └────────────┬─────────────┘                 └──────────────────────┘ │
│               │ usa l'SDK pythonico                                     │
│  ┌────────────▼─────────────┐                                          │
│  │ pyfers  (Python puro)    │  SDK OOP/pythonico: Board/System,        │
│  │                          │  enum, properties, context manager,      │
│  │                          │  eventi tipizzati, eccezioni             │
│  └────────────┬─────────────┘                                          │
│  ┌────────────▼─────────────┐                                          │
│  │ pyferslib (C++ pybind11) │  binding FEDELE 1:1 a ferslib:           │
│  │                          │  stesse funzioni/struct/tipi/costanti    │
│  └────────────┬─────────────┘   (GIL released sulle chiamate)          │
└───────────────┼─────────────────────────────────────────────────────────┘
                │
          ┌─────▼─────┐
          │  ferslib  │  ← INVARIATA
          └─────┬─────┘
                │
          [ Hardware FERS ]   (Eth / USB / TDLink)
```

> **Nota sul percorso ad alto throughput (data-plane):** l'SDK `pyfers` serve per ergonomia e
> *control-plane* (configurazione, HV, start/stop, accesso OOP). Il *data-plane* ad alto rate (il
> loop `get_event` del ReadoutThread) può chiamare direttamente `pyferslib` o una primitiva batch,
> bypassando il livello ergonomico per non pagare l'overhead Python per-evento. Vedi §5.4.

**Eliminazioni**: processo `JanusC`, socket TCP, protocollo custom, gnuplot.
**Aggiunte**: stack Python a livelli (binding fedele + SDK pythonico + engine), plot embedded, config in formato strutturato.

---

## 4. Valutazione punto per punto delle richieste

### 4.1 — Banda massima / colli di bottiglia

| | |
|---|---|
| **Ha senso?** | Sì, è il requisito più importante. |
| **Problema reale?** | Sì, confermato nel codice. |
| **Causa** | Il main loop di JanusC è single-thread e mischia readout, statistiche, scrittura disco e plot nello stesso ciclo. L'I/O su disco e il plot bloccano il consumo eventi. |

**Come si fa:**
- **Separare i ruoli in thread distinti**: un thread *readout* che chiama solo `FERS_GetEvent` (che rilascia il GIL → nessun blocco Python); uno o più thread *writer* che scrivono su disco da un buffer; un thread *stats/plot* che aggiorna le statistiche e la GUI a frequenza ridotta (es. 10–20 Hz, l'occhio umano non ha bisogno di più).
- **Disaccoppiare con un ring buffer / coda**: gli eventi prodotti dal readout finiscono in un buffer in memoria; i writer li drenano in modo asincrono. Picchi di rate vengono assorbiti dal buffer invece di bloccare il readout.
- **Il GIL non è un problema**: `pyferslib` già usa `py::gil_scoped_release` attorno alle chiamate ferslib. Le sezioni critiche di throughput restano in C.

> **Nota importante sul limite teorico**: il throughput massimo verso l'hardware è determinato da `ferslib` (immutata) e dal collegamento fisico (Eth/USB/TDLink). Il rinnovo **non aumenta** quel limite hardware, ma **rimuove la penalità software** che oggi impedisce di avvicinarsi ad esso. In altre parole: oggi si perde banda per colpa di JanusC; dopo il rinnovo si arriverà vicino al limite reale di ferslib.

**Verdetto:** ✅ Sensato e risolvibile. È il principale beneficio del rinnovo.

---

### 4.2 — Multithreading fatto bene

| | |
|---|---|
| **Ha senso?** | Sì. |
| **Problema reale?** | Sì. Il modello attuale è essenzialmente single-thread sul consumo eventi, con `Sleep()` sparsi (decine di `Sleep(10)`, `Sleep(100)` nel loop) usati come sincronizzazione grezza. |

**Come si fa:**
- Modello **producer/consumer** classico: readout (producer) → buffer → writer + stats (consumer).
- In Python: `threading` con `queue.Queue` (thread-safe nativa) è sufficiente perché le sezioni pesanti rilasciano il GIL. Per casi estremi si può valutare `multiprocessing` o spostare il drenaggio buffer→disco in C dentro pyferslib.
- Eliminare i `Sleep()` di polling sostituendoli con primitive di sincronizzazione vere (condition variables / queue bloccanti con timeout).

**Rischio:** Basso-Medio. Il pattern è standard. Va testato su hardware reale ad alto rate.

**Verdetto:** ✅ Sensato. Migliora banda e reattività.

---

### 4.3 — Scritture su disco

| | |
|---|---|
| **Ha senso ottimizzarle?** | Sì. |
| **Problema reale?** | Sì. Scritture `fwrite`/`fprintf` inline nel loop di consumo eventi. |

**Come si fa:**
- **Scrittura su thread dedicato** alimentato dal buffer in memoria (vedi §4.1).
- **Buffering esplicito**: accumulare blocchi grandi prima di scrivere, invece di una `fwrite` per evento.
- **Formato binario efficiente** come default (l'ASCII/CSV resta opzionale per debug/analisi offline).
- Valutare scrittura asincrona / memory-mapped file se il rate lo richiede.
- **Compatibilità**: il formato file attuale ha un header ben definito ([outputfiles.c](janus-5202/src/outputfiles.c), `WriteListfileHeader`). Va deciso se mantenere bit-per-bit la compatibilità con i file esistenti o introdurre un nuovo formato versionato. Raccomandazione: mantenere un *reader* compatibile col vecchio formato e introdurre un nuovo formato di scrittura versionato.

**Verdetto:** ✅ Sensato. Strettamente legato a §4.1 e §4.2.

---

### 4.4 — Plot embedded nella GUI (eliminare gnuplot)

| | |
|---|---|
| **Ha senso?** | Sì, decisamente. |
| **Problema reale?** | Sì. gnuplot è un processo esterno pilotato via pipe testuale: lento, fragile, finestra separata, dipendenza eseguibile da distribuire. |

**Come si fa (opzioni):**
- **`pyqtgraph`** — *raccomandato per dati real-time*. Costruito proprio per plotting scientifico ad alta frequenza dentro Qt. Gestisce bene istogrammi, mappe 2D, waveform che si aggiornano molte volte al secondo. Integrazione nativa in finestre Qt.
- **`matplotlib` con backend Qt** — più ricco esteticamente e familiare, ma più lento per aggiornamenti real-time ad alta frequenza. Buono per plot statici / report.
- **`VisPy` / OpenGL** — se servono prestazioni estreme (milioni di punti), ma più complesso.

I tipi di plot da replicare (visti in [plot.c](janus-5202/src/plot.c)): spettri energia (PHA HG/LG), ToA/ToT, MCS time, mappe 2D di rate/carica, istogrammi di conteggio per canale. Tutti standard e ben supportati da pyqtgraph.

**Verdetto:** ✅ Sensato e ad alto impatto sulla qualità percepita. `pyqtgraph` è la scelta naturale.

---

### 4.5 — File di configurazione (mantenere, formato moderno, scambiabile)

| | |
|---|---|
| **Ha senso?** | Sì. |
| **Problema reale?** | Parziale. Il sistema attuale usa file di testo custom (`param_defs.txt` + `Janus_Config.txt`), parsati **due volte** con due parser diversi (uno in C in `FERS_paramparser.c`/`paramparser.c`, uno in Python in `cfgfile_rw.py`). Duplicazione = fonte di bug. |

**Come si fa:**
- **Formato raccomandato: YAML** — leggibile dall'uomo, supporta commenti (utili per documentare i parametri), gerarchico (board / canali / globale). Alternativa: **JSON** (più rigido, niente commenti, ma universale) o **TOML** (buon compromesso, commenti sì, meno annidamento).
- **Un solo file scambiabile**: requisito pienamente soddisfacibile. Tutta la configurazione (parametri globali + per-board + per-canale + maschere pixel) in un unico file. Si carica/salva/condivide come singolo artefatto.
- **Un solo parser**: in Python, eliminando la duplicazione C/Python. La validazione si fa con uno schema (es. `pydantic` o JSON Schema) → errori chiari all'utente.
- **Migrazione**: fornire un convertitore one-shot dal vecchio formato testo al nuovo, così le configurazioni esistenti non vanno perse.

**Punto di attenzione:** verificare *come* ferslib si aspetta i parametri. Se JanusC oggi passa la config a ferslib via `FERS_configure` leggendo struct interne, bisogna assicurarsi che pyferslib esponga il caricamento dei parametri nella struct attesa da ferslib (le `FERS_configure_520X.c` lavorano su registri). Questo va mappato con cura ma è fattibile.

**Verdetto:** ✅ Sensato. YAML consigliato. Beneficio collaterale: eliminazione del doppio parser.

---

### 4.6 — GUI con framework moderno (non tkinter)

| | |
|---|---|
| **Ha senso?** | Sì. |
| **Problema reale?** | Sì. tkinter è datato, lo stile è difficile da modernizzare, il layout attuale usa posizionamento assoluto (`place(x=, y=)`) che è fragile e non scala con DPI/risoluzioni diverse. |

**Come si fa (opzioni):**

| Opzione | Pro | Contro |
|---|---|---|
| **PySide6 / Qt6** *(raccomandato)* | Standard de-facto per app desktop scientifiche Python; integrazione nativa con pyqtgraph; stile via QSS (simile a CSS); widget ricchi (tabelle, tree, LED); ottimo supporto multipiattaforma e HiDPI | Curva di apprendimento; licenza LGPL (PySide6 ok per uso interno/commerciale) |
| **Tauri / Electron + backend Python** | Permette di replicare *esattamente* lo stile web visto negli screenshot (CAEN Web Interface); UI in HTML/CSS/JS moderni | Toolchain più pesante (Node.js, build frontend); IPC Python↔frontend da gestire; deployment più complesso |
| **Dear PyGui / imgui** | Velocissimo, GPU-accelerated | Estetica meno "professionale", meno adatto a UI complesse con form |

**Sullo stile target:** gli screenshot in `screenshots_gui/` (device tree, link status, info board con temperature e data rate) sono la **CAEN Web Interface**, un'app web con sidebar + tabelle + device tree. Quello stile è replicabile:
- con **PySide6 + QSS** in modo molto fedele (sidebar, LED colorati, tabelle di stato, tree dei dispositivi) — pragmatico per un'app desktop standalone;
- con **Tauri/Electron** in modo *identico* perché si userebbe vero HTML/CSS — ma a costo di una toolchain più complessa.

**Raccomandazione:** **PySide6** per il miglior rapporto fedeltà-stile / semplicità di deployment / integrazione con il resto dello stack Python. Tauri solo se la fedeltà pixel-perfect allo stile web è un requisito vincolante.

**Verdetto:** ✅ Sensato. PySide6 raccomandato.

---

### 4.7 — Modalità CLI / headless (senza GUI, con menu e statistiche)

| | |
|---|---|
| **Ha senso?** | Sì, molto. |
| **Problema reale?** | È un requisito nuovo, ma il codice attuale lo supporta già in forma grezza. |

**Stato attuale:** JanusC ha **già** una doppia modalità nativa: la variabile `SockConsole` ([JanusC.c:38](janus-5202/src/JanusC.c#L38)) vale `0` per console stdio (CLI) e `1` per socket (GUI). La modalità console esiste già — il problema è che è implementata **malissimo**: decine di `if (SockConsole) ... else ...` sparsi in tutto il codice ([JanusC.c](janus-5202/src/JanusC.c), `RunTimeCmd`), con `gotoxy`/`ClearScreen` basati su escape ANSI grezzi e menu testuali costruiti a mano. La logica di acquisizione e quella di presentazione sono intrecciate.

Questo in realtà è una **conferma forte** della bontà dell'architettura proposta: la separazione tra *engine* e *frontend* (§3) rende CLI e GUI semplicemente due presentazioni dello stesso core. L'engine non sa né gli importa chi lo sta pilotando.

```
                  ┌──────────────────────┐
                  │  Acquisition Engine  │   ← unico core, nessuna logica UI
                  │  (readout/writer/    │
                  │   stats threads)     │
                  └──────────┬───────────┘
                             │  API interna (start/stop/config/stats/eventi)
              ┌──────────────┼──────────────┐
              │                             │
      ┌───────▼────────┐           ┌────────▼────────┐
      │  Frontend GUI  │           │  Frontend CLI   │
      │  (PySide6)     │           │  (Textual/Rich) │
      └────────────────┘           └─────────────────┘
```

**Come si fa (CLI moderna):**
- **`Textual`** *(raccomandato)* — framework TUI moderno (stesso autore di Rich). Permette interfacce a terminale con menu, pannelli, tabelle di statistiche aggiornate in tempo reale, persino mini-grafici ASCII/sparkline. Reattivo, con layout dichiarativo simile al web (CSS-like). Ideale per "menu + alcune stats in modo moderno".
- **`Rich`** — se basta output formattato (tabelle di statistiche live, progress bar, colori) senza una vera applicazione interattiva a schermo intero. Più semplice di Textual.
- **Modalità batch/script puro** — per esecuzioni completamente automatiche (cron, acquisizioni programmate, integrazione con altri tool): l'engine si pilota da riga di comando con argomenti (`--config run.yaml --duration 3600 --output ./data`) senza alcuna UI interattiva. Utile per data taking non presidiato.

**Requisito di design abilitante:** perché CLI e GUI condividano davvero il core, l'engine deve esporre **un'API interna pulita** (es. una classe `AcquisitionEngine` con metodi `configure()`, `start()`, `stop()`, `get_stats()`, callback/queue per gli eventi). Sia la GUI che la CLI consumano questa API. Questo va tenuto presente fin dall'inizio nel disegno dell'engine (§4.2): **nessuna logica di presentazione dentro l'engine**.

**Vantaggio collaterale:** la modalità CLI/headless è anche il miglior banco di prova per i **benchmark di throughput** (§4.1) — si misura la banda pura dell'engine senza l'overhead di rendering della GUI.

**Verdetto:** ✅ Sensato e a basso costo aggiuntivo *se* l'engine è progettato correttamente separato dal frontend. Textual raccomandato per la TUI interattiva; modalità batch da argomenti CLI per l'automazione.

---

### 4.8 — Build system moderno ma Visual Studio-compatibile

| | |
|---|---|
| **Ha senso?** | Sì. |
| **Problema reale?** | Sì. I build system attuali sono eterogenei, in parte datati e duplicati per piattaforma. |

**Stato attuale (rilevato nei progetti):**

| Progetto | Build system attuale | Note |
|---|---|---|
| `ferslib` | Visual Studio (`ferslib.sln` + `.vcxproj`) **+** autotools (`configure.ac`) | Due sistemi paralleli: VS per Windows, autotools per Linux. Doppia manutenzione. |
| `janus-5202` | Visual Studio (`.vcxproj`) **soltanto** | Solo Windows. Su Linux si usa un Makefile a parte (citato nei sorgenti). |
| `pyferslib` | **CMake** + **scikit-build-core** (`pyproject.toml`) + `meson.build` + CI `cibuildwheel` | Già moderno e multipiattaforma. Genera wheel per Win/Linux/macOS. **Questo è il modello da seguire.** |

**Punto chiave:** la richiesta "moderno **ma** Visual Studio-compatibile" è esattamente ciò che **CMake** fa per design. CMake non è alternativo a Visual Studio: è un *generatore* che produce nativamente soluzioni VS.
- `cmake -G "Visual Studio 17 2022"` genera `.sln` e `.vcxproj` apribili e debuggabili in Visual Studio.
- Lo stesso `CMakeLists.txt`, su Linux, genera Makefile o progetti Ninja.
- Visual Studio 2019/2022 ha inoltre **supporto CMake nativo**: si può aprire la cartella con il `CMakeLists.txt` direttamente, senza generare nulla a mano.

Quindi non c'è alcun trade-off: CMake **è** la risposta sia al "moderno" sia al "VS-compatibile".

**Come si fa:**
- **Adottare CMake come unico build system** per tutta la parte nativa (C/C++), eliminando autotools e i `.vcxproj`/`.sln` scritti a mano (che diventano artefatti generati, non versionati).
- **Riutilizzare ciò che già esiste**: il [CMakeLists.txt](pyferslib/CMakeLists.txt) di pyferslib **già compila ferslib da sorgente e il modulo pybind11**, multipiattaforma, con supporto MSVC (`if(MSVC) ...`). È la base di partenza ideale.
- **Per `ferslib` (vincolo: sorgente invariato):** il vincolo riguarda il *codice sorgente*, non il build. Si può aggiungere/aggiornare un `CMakeLists.txt` che compila i sorgenti ferslib così come sono, senza toccarli. CMake genera la soluzione VS quando serve il debug in IDE.
- **Per il packaging Python:** `scikit-build-core` (già in `pyproject.toml`) fa da ponte tra CMake e pip/wheel. `cibuildwheel` (già in CI) produce i pacchetti per tutte le piattaforme e versioni Python.
- **Per i frontend Python puri** (GUI/CLI): nessun build nativo necessario — packaging via `pyproject.toml` + PyInstaller per l'eseguibile distribuibile.

**Struttura build proposta:**
```
CMake (root)
 ├── ferslib            → libreria nativa (sorgente invariato), genera .sln per VS su richiesta
 ├── pyferslib          → modulo pybind11, già su CMake/scikit-build-core
 └── pyproject.toml     → wheel Python (engine + GUI + CLI), via scikit-build-core
                          PyInstaller per eseguibili standalone Windows/Linux
```

**Decisione da prendere:** se mantenere anche `meson.build` (presente in pyferslib) o consolidare tutto su CMake. Raccomandazione: **un solo build system nativo (CMake)** per ridurre la manutenzione. meson è valido ma avere due build paralleli ricrea il problema attuale di ferslib.

**Verdetto:** ✅ Sensato e in gran parte **già impostato** in pyferslib. CMake soddisfa contemporaneamente "moderno" e "VS-compatibile". Il lavoro è consolidare, non inventare.

---

## 5. Lo stack Python a due livelli: `pyferslib` (binding fedele) + `pyfers` (SDK pythonico)

| | |
|---|---|
| **Ha senso?** | Sì, molto. È un miglioramento rispetto a un binding monolitico unico. |
| **Problema reale?** | Sì. Un binding unico finirebbe per mescolare due responsabilità diverse: *tracciare l'API C* e *offrire un'API piacevole in Python*. Sono due cose che cambiano a ritmi diversi e con criteri diversi. |

Invece di un unico modulo che fa da binding *e* da API ergonomica, lo si separa in **due livelli con confini netti**. È un pattern collaudato nel software scientifico (es. `h5py` ha un binding Cython di basso livello + il package "high-level" `h5py._hl`; molte librerie di strumentazione fanno lo stesso).

### 5.1 — `pyferslib` — binding fedele 1:1 (livello basso)

Modulo di estensione C++ (pybind11) che riproduce **ferslib così com'è**, senza reinterpretarla:

- **Stesse funzioni**: ogni `FERS_*` rilevante esposta una a una, con la stessa semantica.
- **Stesse struct e tipi**: `FERS_BoardInfo_t`, `FERS_CncInfo_t`, `SpectEvent_t`, `CountingEvent_t`, `WaveEvent_t`, `ListEvent_t`, `ServEvent_t`, `TestEvent_t` esposte come classi Python (`py::class_`) con i campi reali. Gli array a dimensione fissa (`energyHG[64]`, ecc.) e i puntatori+lunghezza (`wave_hg`/`ns`) diventano array NumPy.
- **Stesse costanti/enum**: `DTQ_*`, `ROMODE_*`, `STARTRUN_*`, `CFG_HARD/SOFT` esposte tali e quali.
- **API string-based mantenuta** a questo livello: `FERS_SetParam(handle, name, value)` resta com'è. Qui non si "aggiusta" nulla del design: si traduce fedelmente.
- **Out-parameter → valori di ritorno**: i parametri-puntatore C (`int* handle`, `float* vmon`) diventano valori restituiti, perché in Python non esiste l'idioma del puntatore di uscita. Questa è una traduzione meccanica, non un cambio di design.
- **Unica concessione "non-C"**: i codici di ritorno negativi diventano `FERSError` (eccezione che porta codice + testo da `FERS_GetLastError`). Propagare interi di errore in Python è *peggio* dell'originale C e tutti li incapsulerebbero comunque. **Decisione da confermare**: se si vuole la fedeltà assoluta, si può esporre la coppia (codice, dato) e lasciare l'eccezione al livello `pyfers`. Raccomandazione: eccezioni già qui, è il default Python sano.

**Cosa completare** (oggi sono 5 funzioni su molte decine — [pyfers.cpp](pyferslib/python/pyfers.cpp)):
- Device/info: `OpenDevice`, `CloseDevice`, `GetBoardInfo`, `GetCncInfo`, `GetNumBrdConnected`, `GetClockPeriod`, `Reset_IPaddress`.
- Acquisizione: `StartAcquisition`, `StopAcquisition`, `GetEvent`/`GetEventFromBoard` con tutti i tipi di evento.
- Readout: `InitReadout`, `CloseReadout`, `FlushData`.
- Config string-based: `LoadConfigFile`, `SetParam`, `GetParam`, `configure`.
- Registri/comandi: `ReadRegister`, `WriteRegister`, `WriteRegisterSlice`, `SendCommand`.
- HV: `HV_Init`, `HV_Set_OnOff`, `HV_Get_Status`, `HV_Set/Get_Vbias`, `HV_Get_Vmon`, `HV_Set_Imax`, `HV_Get_Imon`, temperature HV.
- Temperature: `Get_FPGA_Temp`, `Get_Board_Temp`, `Get_TDC0/1_Temp`.
- TDL: `InitTDLchains`, `EnumTDLchains`, `SyncTDLchains`, `TDLchainsInitialized`.

**Proprietà chiave**: questo livello è *stabile* — cambia solo quando cambia ferslib. È auditabile riga per riga contro `FERSlib.h`. Non contiene scelte di design discutibili.

**Rischio**: esporre struct con array fissi via pybind11 (`def_property` che ritorna NumPy **copiando** dal buffer ferslib, che viene riusato — mai una view). Medio, ma è pattern noto (`py::array_t` già usato per `init_tdl_chains`).

### 5.2 — `pyfers` — SDK pythonico (livello alto, Python puro)

Package Python puro **sopra** `pyferslib`, dove vivono le scelte di design migliorate. Qui si "aggiusta" tutto ciò che in C era obbligato:

- **Accesso OOP alle schede**: una classe `Board` che incapsula l'handle e l'identità della scheda; una classe `System` (o `Detector`) che gestisce più schede + concentratore.
  ```python
  with pyfers.System.open("eth:192.168.50.3") as sys:
      board = sys.boards[0]
      print(board.info.model_name, board.info.fpga_fw)
      board.hv.vbias = 62.5          # property, non set_param("HV_Vbias", "62.5 V")
      board.hv.on = True
      sys.configure(my_config)
      sys.start_run(run_number=12)
      for event in sys.events():     # iteratore, non polling con GetEvent
          ...
      sys.stop_run()
  ```
- **Niente string-based esposto all'utente**: `board.hv.vbias = 62.5` o `board.params.hg_gain = 51` invece di `set_param("HG_Gain", "51")`. Internamente questi *traducono* alle chiamate string-based di `pyferslib` (o ai registri), ma l'utente vede attributi tipati. Si integra naturalmente con lo schema `pydantic` del livello config (§4.5): `board.apply(config)`.
- **Eventi tipizzati**: `get_event` grezzo diventa un iteratore che produce oggetti/`dataclass` tipizzati (`SpectEvent`, `CountingEvent`, ...) con campi NumPy, invece di dover interpretare a mano il `DataQualifier`.
- **Enum invece di interi magici**: `pyfers.StartMode.ASYNC`, `pyfers.AcqMode.SPECTROSCOPY`, `pyfers.SortMode.TRGID` al posto di `0x11`, ecc.
- **Context manager / RAII**: `with Board(...)` chiude device e readout in automatico; niente leak di handle.
- **Eccezioni e logging idiomatici**, type hints ovunque, docstring.

**Proprietà chiave**: questo livello è *Python puro* → testabile senza hardware (mock di `pyferslib`), facile da modificare, ed è dove si itera sul design dell'API senza ricompilare nulla.

### 5.3 — Confini e dipendenze

```
ferslib (C, frozen)
  → pyferslib   (C++ pybind11)  — fedele 1:1, raramente cambia, traccia ferslib
    → pyfers    (Python puro)   — OOP/pythonico, qui vivono le scelte di design
      → hydrafers.core (engine) — threading, IO, stats; usa pyfers per il control-plane
        → hydrafers.cli / hydrafers.gui
```

- `pyferslib` non importa `pyfers` (dipendenza a senso unico).
- `pyfers` è un SDK **riutilizzabile** in sé: chi vuole pilotare un sistema FERS da Python in modo pulito può usare solo `pyfers`, senza l'intera app HydraFERS.
- **Decisione di packaging da prendere**: `pyfers` come *distribuzione separata* (`pip install pyfers`, massima riusabilità) oppure come sotto-package di `hydrafers`. Raccomandazione: distribuzione separata, coerente con l'idea di un SDK generale. `pyferslib` resta la sua distribuzione (è il progetto che hai già iniziato).

### 5.4 — Le prestazioni non ne soffrono (data-plane vs control-plane)

L'unica preoccupazione legittima del doppio livello è l'overhead Python per-evento sul percorso ad alto rate. Si risolve distinguendo i due piani:

- **Control-plane** (configurazione, HV, start/stop, info): bassa frequenza → si usa l'SDK ergonomico `pyfers`, l'overhead è irrilevante.
- **Data-plane** (il loop `get_event` del ReadoutThread, milioni di chiamate/s): può chiamare **direttamente `pyferslib`**, o usare una **primitiva batch** che dreni più eventi per chiamata, evitando un frame Python per-evento. Per il massimo assoluto, il salvataggio raw può restare in C dentro ferslib (`FERS_OpenRawDataFile`), con `pyfers`/engine che campionano a rate ridotto per stat e plot.

Questo mantiene **insieme** design pulito e prestazioni: l'ergonomia non è sul cammino critico.

### 5.5 — Impatto sul lavoro già abbozzato

La bozza di implementazione precedente assumeva un **unico** `pyfers` che restituiva `dict`. Con questa architettura:
- quel binding diventa `pyferslib` (struct-based, fedele) — il `dict` lascia il posto a classi/struct;
- nasce il nuovo livello `pyfers` (OOP) che prima non esisteva;
- `hydrafers.core` si appoggia a `pyfers` per il control-plane e a `pyferslib`/primitiva batch per il data-plane.

Il `CONTRACT.md` va quindi **diviso**: §1a (API fedele `pyferslib`) e §1b (SDK `pyfers`). Va riallineato prima di riprendere l'implementazione.

**Verdetto:** ✅ Sensato e raccomandato. Separa "tracciare il C" da "progettare una bella API Python", aumenta la riusabilità, e non penalizza il throughput se si distinguono data-plane e control-plane. È il lavoro più tecnico e va affrontato per primo (prima `pyferslib`, poi `pyfers`).

---

## 6. Matrice rischi

| Area | Rischio | Severità | Mitigazione |
|---|---|---|---|
| `pyferslib` event structs | Mappatura corretta di ~6 struct evento (array fissi → NumPy, copia non view) | Media | Test unitari contro dati noti; partire da SpectEvent (il più usato) |
| Doppio livello `pyferslib`/`pyfers` | Overhead Python per-evento sul data-plane | Media | Data-plane chiama `pyferslib`/primitiva batch; ergonomia solo sul control-plane (§5.4) |
| Confini di livello | "Sanguinamento" di logica string-based/handle nel livello alto o di OOP nel binding | Bassa | Regole di dipendenza a senso unico (§5.3); review dedicata ai confini |
| Throughput / multithreading | Non raggiungere la banda target su HW reale | Media | Benchmark precoci su hardware; ring buffer dimensionato; profiling |
| Compatibilità formato file | Rompere la lettura dei file esistenti | Media | Reader retro-compatibile + nuovo formato versionato |
| Config: mapping verso ferslib | Parametri non passati correttamente a ferslib | Media | Studiare `FERS_configure_520X.c`; validare con schema |
| GUI: fedeltà allo stile | Discostarsi dallo stile target | Bassa | PySide6 + QSS; iterare sugli screenshot |
| Deployment Windows | Distribuzione DLL ferslib + dipendenze Python | Bassa | PyInstaller / packaging; CI già presente in pyferslib |
| Logica Jobs (run multipli) | Riprodurre comportamento automazione | Bassa | Logica semplice, riscrivibile in Python |

Nessun rischio è classificato come **Alto** o bloccante.

---

## 7. Conclusioni

| Richiesta | Fattibile | Sensato | Note |
|---|---|---|---|
| Aumentare banda / togliere colli di bottiglia | ✅ | ✅✅ | Beneficio principale; causa = JanusC single-thread |
| Multithreading fatto bene | ✅ | ✅ | Pattern producer/consumer standard |
| Eliminare scritture disco continue | ✅ | ✅ | Thread writer + buffering |
| Plot embedded (no gnuplot) | ✅ | ✅✅ | pyqtgraph |
| Config mantenuta, formato moderno, 1 file | ✅ | ✅ | YAML consigliato; elimina doppio parser |
| GUI framework moderno (no tkinter) | ✅ | ✅ | PySide6 raccomandato |
| CLI / headless moderna (menu + stats) | ✅ | ✅ | Textual / Rich; doppia modalità già esiste in JanusC ma mal fatta |
| Build system moderno + VS-compatibile | ✅ | ✅ | CMake (genera .sln nativamente); già impostato in pyferslib |
| Stack Python a 2 livelli (`pyferslib`+`pyfers`) | ✅ | ✅✅ | Binding fedele 1:1 + SDK pythonico OOP; separa "tracciare il C" da "API pythonica" (§5) |
| ferslib invariata | ✅ | — | Vincolo rispettato (sorgente, non build) |
| JanusC eliminato | ✅ | ✅✅ | Sostituito da engine Python in-process |

**Il rinnovo è fattibile, coerente e tecnicamente sensato in tutti i suoi punti.** L'eliminazione di JanusC come processo separato è la decisione architetturale chiave: rimuove la socket fragile, il collo di bottiglia single-thread e gnuplot in un colpo solo, e concentra tutta la logica in un'unica applicazione Python multithread, più semplice da mantenere e da ottimizzare.

**Principio architetturale portante:** separare nettamente l'**Acquisition Engine** (core, senza alcuna logica di presentazione) dai **frontend** (GUI PySide6, CLI/TUI Textual, modalità batch). Questa separazione è ciò che rende possibili, a basso costo, sia la GUI moderna sia la CLI headless richieste — sono solo presentazioni diverse dello stesso core.

### Sequenza di lavoro consigliata
0. **Consolidare il build system su CMake** partendo dal setup già esistente in pyferslib (compila ferslib + binding, genera soluzioni VS su richiesta, multipiattaforma). Fondazione trasversale a tutto il resto.
1. **Completare `pyferslib`** — binding fedele 1:1 (acquisizione + eventi struct-based + config string-based + HV + registri + TDL). Prerequisito per tutto (§5.1).
2. **`pyfers`** — SDK pythonico OOP sopra `pyferslib` (Board/System, enum, properties, eventi tipizzati, context manager). Testabile con mock di `pyferslib`, senza hardware (§5.2).
3. **Acquisition Engine** (`hydrafers.core`) Python multithread (readout / writer / stats separati) con **API interna pulita e senza logica UI** — usa `pyfers` per il control-plane e `pyferslib`/primitiva batch per il data-plane. Qui si recupera la banda.
4. **Frontend CLI/headless** (Textual + modalità batch) — leggero, primo consumatore dell'engine, ideale per i **benchmark di throughput** su hardware reale prima della GUI.
5. **Nuova GUI** PySide6 con plot pyqtgraph embedded, sopra la stessa API dell'engine.
6. **Config YAML** + parser unico + convertitore dal vecchio formato (integrato con le properties di `pyfers`).
7. **Test di compatibilità** formato file e validazione end-to-end.

### Stack tecnologico raccomandato
- **Binding fedele (`pyferslib`):** pybind11 (già in uso) su ferslib invariata — funzioni/struct/tipi/costanti 1:1, string-based mantenuto
- **SDK pythonico (`pyfers`):** Python puro sopra `pyferslib` — OOP (Board/System), enum, properties, eventi tipizzati, context manager, eccezioni
- **Engine (`hydrafers.core`):** Python `threading` + `queue` + buffer, sezioni critiche con GIL rilasciato — API interna pulita, zero logica UI
- **GUI:** PySide6 (Qt6)
- **Plot:** pyqtgraph
- **CLI/TUI:** Textual (interattiva) + Rich (output formattato) + modalità batch da argomenti
- **Config:** YAML + validazione con schema (pydantic), integrato con le properties di `pyfers`
- **Build nativo:** CMake (unico, genera soluzioni Visual Studio su richiesta) + scikit-build-core come ponte verso i wheel Python
- **Packaging:** `pyferslib` e `pyfers` come distribuzioni (potenzialmente separate); wheel via cibuildwheel (CI già presente in pyferslib) + PyInstaller per eseguibili standalone
