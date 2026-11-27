# Risposta di Claude Fable 5.2, effort predefinito, senza conoscere la posizione dell'orchestratore

Testo integrale, come l'ha scritto il modello. Non è stato corretto: dove sbaglia, lo dice `chi-ha-lavorato.md`.

---

## 1. Tesi

Il tool non scrive lo stato: sottomette una **patch atomica di operazioni di grafo con la revisione su cui è stata ragionata**. Il server ha un solo punto di serializzazione per workflow: lì confronta l'impronta (read/write set) della patch con ciò che è stato committato dopo la base, riapplica sulla head, valida il **grafo risultante intero** e solo allora crea una revisione immutabile. Il deploy è lo spostamento di un puntatore, in CAS e solo fast-forward. La granularità del conflitto è una policy del server, non parte del contratto: si parte grossolani e si affina senza cambiare tool. Niente lock né bozze lato server, quindi un agente che muore non lascia nulla.

## 2. Superficie dei tool

Quattro tool.

```ts
get_workflow({ workflow_id, revision?: number|"head"|"live", since?: number })
// → { revision, live, spec, changes_since?: [{revision, author, intent, keys}] }

commit_patch({
  workflow_id, base_revision: number,
  ops: Op[],                 // tutto-o-niente
  intent: string,            // una frase: la leggerà l'altro agente nel conflitto
  idempotency_key: string,
  dry_run?: boolean          // valida e rileva conflitti senza committare
})
// ok → { revision: 14, rebased_over: [13], cascaded: ["e4","e6"], warnings: [] }

test_revision({ workflow_id, revision, suite?: string, cases?: Fixture[] })
// ok → { revision, verified: true, results: [...] }  // effetti esterni simulati

deploy({ workflow_id, revision, expected_live: number, idempotency_key,
         in_flight?: "drain"|"cancel", mode?: "forward"|"rollback" })
// ok → { live: 14, previous: 12, runs_draining: 3 }

type Op =
 | { op:"set_param", node, path, value }
 | { op:"set_add"|"set_remove", node, path, item }      // campi-insieme (n2.fields)
 | { op:"add_node", id, type, params }                   // id generato dal client (ULID)
 | { op:"remove_node", node }                            // cascata sugli archi incidenti
 | { op:"add_edge", id, from, on?, to } | { op:"remove_edge", edge }
 | { op:"retarget_edge", edge, to }
 | { op:"insert_on_edge", edge, node:{id,type,params} }  // spezza l'arco atomicamente
```

Quando: `get_workflow` prima di pianificare e dopo ogni conflitto; `commit_patch` una volta per intento completo; `test_revision` sulla revisione restituita; `deploy` solo su revisione `verified`.

Errori, sempre con `applied: false` e un campo `next`:

```json
{ "code":"CONFLICT", "your_base":12, "head":13,
  "conflicts":[{ "key":"node:n2/param:model", "kind":"write-write",
     "base_value":"gpt-4.1", "yours":"model-y",
     "theirs":{"revision":13,"author":"agent-A","intent":"…","value":"model-x"} }],
  "next":"Rileggi con get_workflow(since:12). Decidi se rinunciare, adattare o sovrascrivere consapevolmente con base_revision:13. Non ritentare identico." }
```

- `INVALID`: `{violations:[{rule, path, message}], valid_on_base: bool}`. Con `valid_on_base:true` il problema nasce dalla combinazione con modifiche altrui.
- `LIVE_MOVED`: `{live_now, your_revision_includes_live: bool}`. Se `true`, ritentare con il nuovo `expected_live` è sicuro.
- `SUPERSEDED`: la live discende già dalla tua revisione, non c'è nulla da fare.
- `NOT_VERIFIED`: manca il test.
- `ESCALATE`: stesso key conteso N volte dagli stessi agenti; fermarsi e chiedere al proprietario.
- Un replay con lo stesso `idempotency_key` restituisce la risposta originale con `replayed:true`.

## 3. Semantica di concorrenza

Ogni op ha un'impronta su chiavi:

- `node:N/exists`
- `node:N/param:<path>`, per elemento nei campi-insieme
- `node:N/in` e `node:N/out` (adiacenza)
- `edge:E`
- `node:N/out-field:<nome>` (output dichiarati)

Regole:

- `set_param` scrive il suo path e legge `exists`.
- `remove_node` scrive tutto il prefisso `node:N/*`, gli archi incidenti e l'adiacenza dei vicini.
- Ogni op sugli archi scrive l'arco e l'adiacenza dei due estremi.
- Un nodo che referenzia `n2.urgency` **legge** `node:n2/out-field:urgency`; togliere il campo lo **scrive**.

**Due patch si toccano** se e solo se W(P) o R(P) interseca l'unione dei write set delle revisioni base+1..head. È OCC con validazione all'indietro. Se non si toccano, la patch viene riapplicata sulla head e gira il validatore completo: riferimenti, raggiungibilità dall'entry, esaustività dei branch, tipi dei parametri, aciclicità se richiesta.

La serializzazione è una transazione per workflow (`UPDATE … WHERE head = :h`, o scrittore unico per workflow). La storia è lineare.

Garantito:
- ogni revisione esistente rispetta gli invarianti;
- nessun lost update;
- le patch accettate equivalgono a un'esecuzione seriale;
- atomicità.

Non garantito:
- che la somma di due modifiche compatibili sia ciò che qualcuno voleva;
- le dipendenze nascoste in testo libero (prosa di un prompt);
- la liveness sotto contesa;
- la qualità del comportamento, che è compito dei test.

## 4. Casi di test

| | Primo arrivato | Secondo | Stato finale |
|---|---|---|---|
| **T1** | ok → 13 | ok → 14, `rebased_over:[13]` | entrambe |
| **T2** | ok → 13 | `CONFLICT` write-write, con valore e intento altrui | model del primo. Il secondo può sovrascrivere solo ripartendo dalla 13; al ping-pong `ESCALATE` |
| **T3** | ok → 13 | ok → 14 (chiavi `param:model` e `param:fields/sentiment`) | entrambe |
| **T4** | A prima: B riceve `CONFLICT` «n5 rimosso dalla 13» e di norma rinuncia. B prima: A riceve `CONFLICT` «n5 modificato» e può ricancellare dalla 13 | | Mai «delete vince» in automatico |
| **T5** | ok | `CONFLICT` | n1→n2→n4→n6 in entrambi gli ordini |
| **T6** | vedi sotto | | |
| **T7** | ok → 13 (n2→Translate→n3) | `CONFLICT` su `edge:e2` | Il secondo sceglie su quale nuovo arco inserirsi |
| **T8** | ok | `LIVE_MOVED` o `SUPERSEDED` | la revisione più avanzata |
| **T9** | replay → stessa risposta | — | nessuna revisione doppia, nulla da ripulire |
| **T10** | — | — | `ESCALATE` |

**T5.** Lo stato rotto è impossibile per tre barriere indipendenti: patch atomica, cascata sugli archi, validatore sul risultato unito. Le impronte si intersecano (A scrive `n3/out`, B scrive `n3/*`), quindi il secondo va in conflitto.
- Se A è primo: B rilegge, trova n5 già sparito, risottomette `{remove_node n3, retarget e2→n4}` sulla 13.
- Se B è primo: A rilegge, vede il proprio intento già soddisfatto e si ferma.
- Con un validatore che pretende branch esaustivi, la patch di A è `INVALID` già da sola («outcome no senza destinazione»). Parte del disastro della lavagna è una patch sottospecificata, e lo direi all'intervistatore.

**T6.** A da sola è `INVALID` già sulla 12, perché n3 legge urgency: A deve sistemare n3 nella stessa patch.
- Se B aggiunge un nodo che usa urgency e arriva secondo: `CONFLICT` read-write.
- Se B arriva primo: A riceve `INVALID` con `valid_on_base:true`.
- Vale solo se i riferimenti sono strutturati (`{ref:"n2.urgency"}` o template parsabili). In prosa libera lo vede solo il test run.

**T7.** L'ordine Redact/Translate cambia il significato (cosa viene tradotto), quindi il sistema non deve sceglierlo. Gli ID generati dal client evitano che entrambi creino «n7».

**T8.** Con storia lineare A ha la 13 e B la 14, che contiene la 13.
- Se vince A: B riceve `LIVE_MOVED` con `your_revision_includes_live:true` e ritenta.
- Se vince B: A riceve `SUPERSEDED`.
- Ogni run fissa la revisione all'avvio e finisce sulla 12 (`drain`), comprese le approvazioni umane pendenti. Per questo `toolRef` e modello sono pinnati e le revisioni vecchie restano eseguibili.

**T9.** Non ci sono bozze né lock lato server; l'unico stato dell'agente è una lista di op in memoria. Il deploy è un singolo swap.

**T10.** Il tool non arbitra obiettivi. Le vie sono un proprietario umano o un traffic split sul puntatore live. Il fork ingenuo duplica il trigger Zendesk: ogni ticket riceverebbe due risposte.

## 5. Ciclo di vita

- **Immutabili:** revisioni (con hash e parent), attestazioni di test (hash revisione + hash suite), la revisione di ogni run.
- **Puntatori:** `head` (avanza solo via commit) e `live` (si sposta solo via deploy in CAS).
- **Stati:** `committed` (strutturalmente valida) → `verified` (test passati sull'intera revisione, non sul diff) → deployabile.
- **Rollback:** `deploy(mode:"rollback")` su una verified precedente, stesso CAS. Poi serve una patch di revert sulla head, altrimenti il prossimo deploy riporta il bug.

Test del tool:

1. I casi della lavagna come test tabellari, eseguiti in **tutte le permutazioni d'arrivo**.
2. Test model-based con simulazione deterministica: N agenti, op casuali, interleaving casuali, crash tra commit e risposta. Invarianti:
   - ogni revisione passa il validatore;
   - lo stato finale coincide con un'applicazione seriale delle patch accettate;
   - una patch rifiutata non lascia traccia;
   - replay non crea una nuova revisione;
   - live punta sempre a una verified;
   - un run osserva una sola revisione.
3. Eval dell'agente: dato un `CONFLICT`, rilegge e ripianifica, o ritenta identico?

## 6. Dove si rompe

- **Contesa:** ogni conflitto costa una rilettura e una ripianificazione LLM. Su workflow caldi c'è starvation di chi fa patch grandi.
- **Impronte:** grossolane danno falsi conflitti, fini lasciano passare conflitti semantici.
- **Trunk condiviso:** un commit scadente di A fa fallire la verifica di B.
- **Validatore:** diventa il componente critico; ogni regola mancante è un buco.

**Alternativa scartata: scrittura dell'intera spec con CAS sulla revisione** (gli appunti a mano più `expected_revision`). Vince se i conflitti sono rari e i workflow piccoli: nessuna logica di merge, e il validatore sul risultato resta. È il mio design con impronta «tutto il workflow», quindi è un v0 legittimo. Perde appena due agenti lavorano davvero in parallelo, perché T1 e T3 diventano conflitti.

I **branch per agente con merge** vincono invece quando le modifiche durano ore, vanno testate in isolamento o passano da review umana.

## 7. Critica alla baseline

- «Non si toccano» è l'intera domanda ed è rimasto indefinito.
- La bozza per agente rimanda il conflitto al deploy. Lì il CAS su live non basta: B fallisce, ritenta con `expected_live:13` e **cancella il lavoro di A**. Manca la regola di discendenza.
- Mancano idempotenza, agente morto, pinning dei run, cosa fa un test run con Slack e Zendesk, la distinzione tra validità strutturale e verifica comportamentale, e il contratto degli errori.
- «Avvisi e conferme»: un LLM conferma qualsiasi cosa, quindi non è un controllo.
- Il fork duplica i trigger.
- **Liveblocks/CRDT** danno consapevolezza e convergenza, non validità: il riquadro di destra è esattamente uno stato CRDT convergente. Il loro posto è il canvas umano (presenza, posizioni dei nodi, commenti, co-editing del testo di un prompt). Per questo «posizione» va tolta dalla spec versionata. Non vanno sul percorso che porta in produzione.

## 8. Risposta parlata

«Parto dal riquadro di destra: quello è uno stato in cui due modifiche valide sono state unite senza guardare il risultato. Quindi il tool non scrive la spec: sottomette una patch atomica di operazioni di grafo, dichiarando la revisione su cui ha ragionato. Il server serializza per workflow e fa due controlli. Primo: la patch tocca qualcosa che è cambiato dopo la mia base? "Toccare" è preciso: stesso parametro, stesso arco, adiacenza dello stesso nodo, oppure un campo che io leggo e l'altro ha tolto. Secondo: riapplica sulla head e valida il grafo intero; solo allora nasce una revisione immutabile. Nodi diversi o campi diversi si uniscono da soli; stesso campo, modifica contro cancellazione, due inserimenti sullo stesso arco tornano come conflitto strutturato, con il valore e l'intento dell'altro, così l'agente rilegge e decide. Non ci sono lock né bozze sul server, quindi un agente che muore non lascia niente, e ogni chiamata ha una chiave di idempotenza. Il deploy è un puntatore: compare-and-swap, solo su revisioni testate e solo in avanti, così chi arriva secondo non cancella il primo. I run in corso finiscono sulla revisione con cui sono partiti. Lo testo con i vostri casi in tutte le permutazioni d'arrivo e con una simulazione che verifica che ogni revisione sia valida e che il risultato equivalga a un ordine seriale. Il limite: se la dipendenza sta nel testo di un prompt, la vede solo il test run. E se due agenti vogliono cose opposte, il tool si ferma e scala a un umano.»
