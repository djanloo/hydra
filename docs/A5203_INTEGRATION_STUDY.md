# Studio di integrazione A5203 (picoTDC) in HydraFERS

> Stato: studio di fattibilità / scelte di design — **nessun codice modificato**.
> Obiettivo: un **unico binario** HydraFERS che gestisca sia la famiglia **A5202/DT5202**
> (SiPM, spettroscopia + timing, 64 canali) sia la famiglia **A5203/DT5203**
> (picoTDC, timing puro, fino a 128 canali).
>
> Tutte le affermazioni critiche di questo documento sono state verificate in modo
> adversariale leggendo il codice sorgente reale (ferslib congelata, janus-5202,
> janus-5203, hydra). I riferimenti sono nella forma `file:riga`.

---

## 0. Executive summary & verdetto

**Si può fare, ed è meno invasivo di quanto sembri** — ma la mole di lavoro NON è
nel binding C++, è nei layer Python sopra di esso (config, eventi/istogrammi, GUI).

Due fatti fondanti, entrambi verificati nel codice:

1. **ferslib è GIÀ dual-board.** La libreria C congelata fa il dispatch interno
   su `FERSCode` (letto dalla flash della scheda all'apertura): `FERS_configure`
   chiama `Configure5202`/`Configure5203` da sola ([FERS_configure.c:34-51](../native/ferslib/src/FERS_configure.c#L34)),
   e `FERS_DecodeEvent` instrada al decoder giusto ([FERS_readout.c:1334-1346](../native/ferslib/src/FERS_readout.c#L1334)).
   Il chiamante **non sceglie mai** la scheda. → Il binding **`pyferslib` non va toccato.**

2. **I sistemi misti 5202+5203 NON sono supportati** — e non per una nostra scelta:
   c'è un commento esplicito dello sviluppatore CAEN dentro ferslib,
   `// DNIN: no 5202/5203 mixed system are allowed at the moment`
   ([FERS_readout.c:1598](../native/ferslib/src/FERS_readout.c#L1598)). L'event-building
   confronta timestamp **grezzi** senza normalizzare per il clock (8 ns su 5202,
   12.8 ns su 5203), quindi mischiare le due famiglie produce un ordinamento
   temporale privo di senso ([FERS_readout.c:1761](../native/ferslib/src/FERS_readout.c#L1761)).

**Scope raccomandato:** un binario unico che, all'apertura del sistema, **rileva la
famiglia** e impone l'omogeneità (tutte 5202 *oppure* tutte 5203). Costo ferslib:
**zero**. Costo HydraFERS: medio, concentrato in config + dati + GUI.

### Dove sta il lavoro (sintesi)

| Layer | Va toccato? | Entità | Opzione raccomandata |
|---|---|---|---|
| `ferslib` (C, congelata) | **No** | nessuna | — |
| `pyferslib` (binding 1:1) | **No** | nessuna | resta board-agnostic |
| `pyfers` (SDK) | Sì | bassa | `Board.hv` opzionale + enum per-famiglia |
| `hydrafers.config` | Sì | **alta** | union discriminata su `board_family` |
| `hydrafers.core` (eventi/istogrammi) | Sì | alta | `HistogramSet` per famiglia |
| `hydrafers.io` (file) | Sì | media | header v2 self-describing |
| `hydrafers.gui` | Sì | **alta** | view-stack board-aware |
| scope sistema | Sì | bassa | omogeneo, mode-locked all'open |

---

## 1. La fondazione: cosa ferslib fa già da sola

Queste cose **non costano nulla** perché sono già nel C congelato:

- **Identificazione runtime della scheda.** `FERS_GetBoardInfo` espone `FERSCode`
  (5202/5203) e `NumCh` (64/128) — [FERSlib.h:544-553](../native/ferslib/include/FERSlib.h#L544).
  Il binding li espone già come `board_info.fers_code` / `num_ch`.
- **Dispatch configurazione e decode** su `FERSCode`, internamente (vedi §0).
- **Strutture evento condivise.** `SpectEvent_t`, `CountingEvent_t`, `WaveEvent_t`,
  `ListEvent_t`, `ServEvent_t`, `TestEvent_t` sono definite una volta sola; i
  commenti `// 5202 + 5203` lo confermano ([FERSlib.h:641,674](../native/ferslib/include/FERSlib.h#L641)).
- **Dispatch del tipo evento via DataQualifier** (`DTQ_SPECT/TIMING/COUNT/WAVE/...`),
  identico per entrambe le schede ([FERSlib.h:250-257](../native/ferslib/include/FERSlib.h#L250)).
  Il binding fa `switch(dtq & 0xF)` senza guardare `FERSCode`.
- **Clock-period per-scheda** tracciato in `CLK_PERIOD[]` e usato per convertire i
  tick in microsecondi nel campo `tstamp_us` ([FERSlib.h:296-297](../native/ferslib/include/FERSlib.h#L296)).

**Verifica adversariale (parzialmente vera, sfumatura importante):** le struct sono
condivise *ma i campi sono popolati diversamente per scheda*. In `ListEvent_t`:
- 5202 usa `Tref_tstamp` + array `tstamp[]` (ToA in LSB) — `// 5202 only`
- 5203 usa `tstamp_clk` + array `ToA[]` (uint32!) — `// 5203 only`
  ([FERSlib.h:628-639](../native/ferslib/include/FERSlib.h#L628)).

Quindi `pyferslib` resta agnostico (copia tutti i campi), ma **un layer sopra deve
sapere quale campo è valido per quella famiglia.** È esattamente il ruolo di `pyfers`.

---

## 2. Le cinque dimensioni di divergenza

### 2.1 — `pyferslib` (binding 1:1): **nessuna modifica**

Il binding wrappa l'API C che già fa il dispatch. Supporta 5203 con **zero righe
nuove**. L'unica accortezza: chi consuma gli eventi deve scegliere il campo giusto
(`tstamp[]` vs `ToA[]`), ma quello lo risolviamo in `pyfers` (§2.3). ✅

### 2.2 — Config schema: la superficie più grande

`param_defs.txt` 5202 = **109** parametri, 5203 = **77**, con **517 righe di diff**.
Le divergenze sono strutturali, non cosmetiche:

| Categoria | 5202 | 5203 |
|---|---|---|
| Sezione `[HV_bias]` | **presente** (Vbias, Imax, IndivAdj, TempFeedback…) | **assente** (niente HV) |
| `[Spectroscopy]` (HG/LG gain, shaping, pedestal) | **presente** | **assente** |
| `[Test-Probe]` (probe analogici, test pulse) | **presente** | **assente** |
| `[TDC]` (glitch filter, ToT reject, picoTDC pulser, buffer) | **assente** | **presente** |
| `MeasMode` (LEAD_ONLY/LEAD_TRAIL/LEAD_TOT8/LEAD_TOT11) | **assente** | **presente** |
| `ChEnableMask` | 0,1 (64 ch) | 0,1,2,3 (128 ch) |
| `AcquisitionMode` | SPECTROSCOPY, SPECT_TIMING, TIMING_CSTART/CSTOP, COUNTING, WAVEFORM | COMMON_START, COMMON_STOP, TRG_MATCHING, STREAMING, TEST_MODE_1/2 |
| Istogrammi | Energy (EHistoNbin), ToA, MCS | Lead/Trail, ToT (LSB diverso) |
| Coincidenza | `TstampCoincWindow` | `TrgTimeWindow` (rinominato) |
| `TrefSource`, `T0_Out`, `DigitalProbe*` | set di opzioni 5202 | set diverso |

Lo schema attuale è **100% 5202**: `NUM_CHANNELS=64` hardcoded
([schema.py:41](../src/hydrafers/config/schema.py#L41)), sezioni sempre istanziate,
`ACQUISITION_MODE_OPTS` con i soli valori 5202. Il converter ignora silenziosamente
i parametri sconosciuti (perderebbe `MeasMode`, `TrgTimeWindow`, ecc.).

**Scelta di design — union discriminata (raccomandata, score 5/5).**
Pydantic v2 discriminated union su un campo `board_family`:

```yaml
board_family: 5203          # oppure 5202
# ...sezioni valide solo per quella famiglia
```

```python
HydraConfig = Annotated[
    Union[Hydra5202Config, Hydra5203Config],
    Field(discriminator="board_family"),
]
```

- `Hydra5202Config` → HVBias + Spectroscopy + TestProbe + Discr (T/Q)
- `Hydra5203Config` → TDC + DataAnalysis(Lead/Trail/ToT) + Adapters

**Pro:** ogni famiglia ha esattamente i suoi campi, niente superset gonfio, niente
campi "inutilizzabili", estendibile a 5204 aggiungendo una variante.
**Contro:** refactoring dello schema attuale; il converter deve fiutare la famiglia
(se compare `MeasMode` → 5203, se compare `EHistoNbin` → 5202); i vecchi YAML 5202
vanno taggati (auto-infer 5202 con warning).

*Alternativa scartata (score 3):* superset piatto con `board_family` + validator
condizionali — meno refactoring ma modello gonfio e validazione enum sparsa.

### 2.3 — `pyfers` SDK: HV opzionale + enum per-famiglia

Due punti 5202-coupled, entrambi piccoli:

1. **`Board.hv` è sempre attaccato** ([board.py:135](../src/pyfers/board.py#L135)
   `self.hv = HV(self)`). Sul 5203 **non esiste HV**: verificato che *tutte* le 17
   funzioni `FERS_HV_*` ritornano `FERSLIB_ERR_NOT_APPLICABLE` per FERSCode 5203
   (es. [FERSlib.c:1845,1988,2036](../native/ferslib/src/FERSlib.c#L1845)), e
   `Configure5203` non fa **nessuna** chiamata HV.
   → `board.hv` deve diventare **opzionale** (`None` per 5203), oppure sollevare un
   errore chiaro se usato su una scheda senza HV. Suggerisco una property
   `board.has_hv` derivata da `info.fers_code` e `board.hv` che ritorna `None`.

2. **Gli enum portano solo i valori 5202** ([enums.py:34-39](../src/pyfers/enums.py#L34)):
   `AcqMode` non ha COMMON_START/STREAMING/TRG_MATCHING; `StartMode` ha 6 valori
   mentre il 5203 ne ha 2 (ASYNC, TDL).
   → Servono enum **per-famiglia**: `AcqMode5202` / `AcqMode5203` (o un `AcqMode`
   con membri taggati per famiglia e un validatore che filtra). `to_dtq()` va
   esteso (COMMON_START/STOP/TRG_MATCHING/STREAMING → `DTQ_TIMING`).

3. **Normalizzazione campi evento.** Aggiungere a `pyfers` una property
   board-aware su `ListEvent` (es. `.timestamp` che restituisce `tstamp_clk` su
   5203 o `Tref_tstamp` su 5202), così l'app non tocca i campi grezzi. Questo è il
   posto giusto per assorbire la sfumatura della §1.

`System` deve inoltre rilevare la famiglia all'`open()` e imporre l'omogeneità (§3).

### 2.4 — Eventi, istogrammi, statistiche, file

Il cuore dati è 5202-specifico:

- `HistogramSet` assume **64 canali** ed energia HG/LG
  ([events.py: NUM_CH=64](../src/hydrafers/core/events.py)); il 5203 vuole
  Lead/Trail per-canale + ToT con LSB `3.125ps·2^N`, fino a 128 canali, **niente
  energia**.
- Il file binario serializza larghezze 5202: energy `<u2`, ToA `<u4`, ToT `<u2`.
  Ma la **ToA del 5203 è uint32** ([FERSlib.h:639](../native/ferslib/include/FERSlib.h#L639))
  e la semantica è Lead/Trail. L'header non porta modello/canali per scheda.
- Il dict "neutro" prodotto da `extract_event` non porta `board_model`/`num_ch`/
  `meas_mode`, quindi writer e stats non sanno discriminare.
- La pipeline readout→writer→stats passa `(board_index, dtq, event)`: manca il
  tag di famiglia.

**Scelta di design (raccomandata):**
- **`HistogramSet` per famiglia** (score 5): base + `HistogramSet5202`
  (energia+ToA/ToT, 64ch) e `HistogramSet5203` (Lead/Trail+ToT, fino a 128ch).
  All'avvio del run, l'engine legge `FERSCode` da `pyfers.System` e istanzia la
  sottoclasse giusta; lo stats-thread fa dispatch.
- **Formato file v2 self-describing** (score 4): `format_version=2`, header con
  `board_models`/`channels_per_board`, tag di record con indice scheda + flag di
  schema (energia vs lead/trail, ToA 16 vs 32 bit). I reader v1 (solo 5202)
  restano leggibili.
- Arricchire il dict neutro con `board_model`/`num_ch`/`meas_mode`, passati una
  volta per scheda all'init (non per evento).

### 2.5 — GUI

Lato buono: `config_form.py` è **dichiarativo** (tabelle `SECTION_SPECS`,
`BOARD_SCALARS`, `CHANNEL_ARRAYS`) — ma **verificato che NON è schema-introspettivo**:
le tabelle e il loop delle tab sono hardcoded 5202, e la `ChannelArrayDialog` fissa
una griglia **8×8 = 64**. Quindi aggiungere il 5203 richiede comunque codice GUI.

Punti 5202-coupled (tutti `major`):
- griglia canali 8×8 / 64 in config form, map2d, statistics, selettori spettro
  (`setRange(0,63)`);
- `SPECTRUM_SOURCES` = solo HG/LG/ToA/ToT — il 5203 vuole Lead/Trail/ToT;
- pannello **HV** sempre costruito — va nascosto per 5203;
- nessun device-tree per flotte miste / badge di modello.

**Scelta di design — view-stack board-aware (raccomandata, score 4/5):**
- aggiungere `BoardStatus.num_ch` (da `FERSCode`/`NumCh`);
- dopo `connect`, rilevare i modelli e **mostrare/nascondere** tab e pagine
  (HV e Spectroscopy spariscono su 5203; appare "Timing Config" con MeasMode);
- griglie canali **auto-dimensionate** dal `num_ch`;
- factory di plot: `SpectrumPlot` generalizzato o varianti 5202/5203;
- piccolo selettore/albero schede con badge modello (utile anche oggi).

---

## 3. La domanda critica: sistemi misti?

**No.** Verificato su tre livelli indipendenti:

1. **Commento dello sviluppatore CAEN:** `no 5202/5203 mixed system are allowed at
   the moment` ([FERS_readout.c:1598](../native/ferslib/src/FERS_readout.c#L1598)).
2. **Event-building rotto sotto clock misti:** il sort confronta `q_tstamp` **grezzi**
   senza normalizzare per `CLK_PERIOD` ([FERS_readout.c:1761](../native/ferslib/src/FERS_readout.c#L1761)).
   Un evento 5203 a tick 100 (=1280 ns) verrebbe ordinato *prima* di un evento 5202
   a tick 150 (=1200 ns) pur essendo successivo. Solo `EventBuildingMode=DISABLED`
   evita il confronto cross-board.
3. **Modi di acquisizione mutuamente esclusivi:** non esiste un AcquisitionMode che
   soddisfi entrambe (5202 SPECTROSCOPY vs 5203 COMMON_START), e in TDL lo start è
   un broadcast unico a tutta la catena.

**Scelta di scope — binario unico, omogeneo, mode-locked all'open (score 5/5):**
- a `System.open()` rilevare i `FERSCode` e **rifiutare** una flotta mista con un
  errore chiaro (es. *"Board[1] è 5203 ma il sistema è stato aperto come 5202"*);
- memorizzare la famiglia in `SystemState`;
- filtrare le opzioni `AcquisitionMode` in base alla famiglia rilevata.

Costo ferslib **zero**, rischio di regressione nullo, e rispecchia l'intento di
progetto (un solo software, ma ogni run omogeneo — come Janus, ma unificato).
Estensione futura al pieno mixed-board possibile *se* emergerà un caso d'uso reale
(richiederebbe però patch alla normalizzazione timestamp in ferslib → fuori scope).

---

## 4. Matrice di rischio

| Rischio | Prob. | Impatto | Mitigazione |
|---|---|---|---|
| Refactoring schema rompe i config 5202 esistenti | media | medio | auto-infer `board_family=5202` con warning; test su config legacy |
| Formato file v2 incompatibile con tool offline | bassa | medio | header self-describing; reader v2 legge anche v1 |
| GUI mista mal gestita | bassa | basso | scope omogeneo elimina il caso peggiore |
| Campo evento sbagliato (tstamp vs ToA) | media | alto | normalizzazione centralizzata in `pyfers`; fixture di test 5202 **e** 5203 |
| Drift di ferslib (5202 v5.0.0 vs 5203 v3.0.0) | media | medio | la nostra ferslib vendored è una sola: verificare che contenga `Configure5203` aggiornato (✅ presente) |
| Utente sceglie un mode non valido per la scheda | media | basso | validazione board-aware all'open |

> Nota drift: janus-5202 dichiara SW 5.0.0 (feb 2026), janus-5203 dichiara 3.0.0
> (mag 2025). Sono le **app** legacy; la **ferslib** è una sola libreria condivisa
> e quella vendored in `hydra/native/ferslib` contiene già il path 5203. Da
> validare in fase di build che i registri 5203 referenziati esistano (lo studio
> li ha trovati: `FERS_configure_5203.c`, `FERS_Registers_5215.h`).

---

## 5. Sequenza di lavoro proposta

Indipendenti dove possibile; l'ordine massimizza il valore incrementale:

1. **`pyfers` foundation** (basso costo, sblocca tutto):
   `System.open()` rileva famiglia + enforce omogeneità; `Board.has_hv`/`hv=None`;
   enum per-famiglia; property `ListEvent.timestamp` board-aware.
2. **Config**: union discriminata `board_family`; converter con auto-detect;
   variante `Hydra5203Config` (TDC + MeasMode + 4 ChEnableMask + Lead/Trail/ToT).
3. **Core dati**: `HistogramSet` base + `5203`; dict neutro arricchito; dispatch
   stats per famiglia.
4. **IO**: formato v2 self-describing + reader retro-compatibile.
5. **GUI**: `num_ch` in `BoardStatus`; view-stack board-aware; plot Lead/Trail/ToT;
   nascondere HV/Spectroscopy su 5203; griglie auto-size.
6. **Test**: fixture eventi 5203 (ListEvent con `ToA[]`/`tstamp_clk`), config 5203,
   round-trip file v2; un fake `pyferslib` che simula `fers_code=5203`.

---

## 6. Domande aperte per te

1. **Caso d'uso misto:** ti servirà mai leggere 5202 e 5203 nella stessa finestra di
   acquisizione (con sync esterno), o run separati sequenziali vanno benissimo?
   (Se "mai", confermiamo lo scope omogeneo e chiudiamo la questione.)
2. **MeasMode del 5203:** è per-scheda o può variare per-canale? Influenza se
   l'estrazione deve tracciare il tipo di edge per hit.
3. **Lead/Trail su file:** record separati `REC_LEAD`/`REC_TRAIL` o un unico
   `REC_TIMING` con flag di edge?
4. **Hai hardware 5203** disponibile per testare, o lavoriamo prima tutto con un
   `pyferslib` fittizio e validiamo sul campo dopo?
5. **Adapter A5256:** il 5203 ha una sezione `[Adapters]` (soglie discriminatore
   esterne). La includiamo subito o in un secondo momento?

---

*Documento generato con verifica adversariale del codice sorgente. Workflow:
6 analisi parallele + 5 verifiche su ground-truth (ferslib, janus-5202/5203, hydra).*
