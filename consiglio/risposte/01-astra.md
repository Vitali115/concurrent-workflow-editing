# Risposta di GPT-6.2 Astra, effort predefinito

Testo integrale, come l'ha scritto il modello. Non è stato corretto: dove sbaglia, lo dice `chi-ha-lavorato.md`.

---

## 1. Tesi

Terrei una sola operazione critica, l’attivazione di una revisione in produzione. Gli agenti preparano e testano candidati immutabili in parallelo. Se nel frattempo cambia la live, il server può riapplicare l’intento originale alla nuova base, purché le sue precondizioni valgano ancora. Il risultato passa di nuovo dai test.

## 2. Superficie dei tool

Tre tool. La bozza è un batch di operazioni sul grafo. L’agente può correggerlo e ripresentarlo senza aprire una sessione di editing.

```ts
read({workflow, ref: {target} | {revision} | {job}})
  → {spec, revision, epoch?} | {status, result?}

prepare({workflow, target, authoredAt, ops: Op[], requires?: Predicate[], key})
  → {job}                 // read(job) restituisce l'esito
  → Ready {candidate, basedOn, expectedEpoch, testReport}

activate({workflow, target, key, request:
  {candidate} | {rollbackTo, expectedEpoch}})
  → {previous, active, epoch}

type Op =
  | {op:"set", id, field, value}
  | {op:"addMember"|"removeMember", id, field, member}
  | {op:"addNode"|"addEdge", id, value}
  | {op:"removeNode"|"removeEdge", id}
  | {op:"rewire", edge, from, to, port}
```

`read` serve prima di decidere e per consultare un job. `prepare` riceve un intento completo, lo applica atomicamente in isolamento e avvia validazione e test. `activate` si chiama quando il candidato è pronto e lo si vuole effettivamente pubblicare.

Il JSON Schema del workflow si può generare dal registro versionato dei tipi. Questa notazione compatta indica oggetti con proprietà obbligatorie e `additionalProperties:false`, mappe con chiavi ID e alternative `oneOf`.

```text
Spec = object(entry:ID, nodes:map(ID,Node), edges:map(ID,Edge))
Edge = object(from:ID, to:ID, port:enum("out","yes","no"))
Node = oneOf(
  object(kind:const("trigger"), source:string),
  object(kind:const("classify"), toolRef:PinnedRef, model:string,
         fields:array(string, uniqueItems:true)),
  object(kind:const("branch"), condition:TypedExpression),
  object(kind:const("human"), required:boolean),
  object(kind:const("draft"), toolRef:PinnedRef, tone:string),
  object(kind:const("output"), channel:string))
TypedExpression comprende riferimenti strutturati {node, field}.
```

La revisione identifica lo snapshot dall’esterno. Il backend verifica endpoint, porte, raggiungibilità, cicli ammessi dal motore e disponibilità dei campi su **ogni percorso** che raggiunge un consumatore.

Gli errori hanno `code`, riferimenti precisi e `nextAction`. `read` distingue `NOT_FOUND` e `FORBIDDEN`. `prepare` restituisce `CONFLICT` con base, valore attuale e operazione bloccata, `INVALID_GRAPH` con nodo, porta o dipendenza da correggere, `TEST_FAILED` con fixture e osservazione, oppure `RETRYABLE` per un guasto transitorio. `activate` può restituire `NOT_READY`, `STALE_LIVE` o `POLICY_CHANGED`. Nel primo caso si consulta il job, negli altri si riprepara. Entrambe le mutazioni rifiutano il riuso di una chiave con payload diverso.

## 3. Semantica di concorrenza

`prepare` legge la live `H` e confronta con `authoredAt` le versioni delle risorse necessarie all’operazione. Il server ricava le precondizioni minime. `set` protegge esistenza del nodo e singolo campo, `addMember` la singola appartenenza, `rewire` l’arco e le porte coinvolte. Cancellare un nodo protegge tutto il suo contenuto e l’insieme degli archi incidenti, inclusi eventuali archi aggiunti dopo la lettura. Le versioni crescono anche se un valore torna identico. L’agente può dichiarare condizioni ulteriori in `requires`.

Due intenti interferiscono quando il primo invalida una precondizione del secondo oppure il secondo, applicato a `H`, produce un grafo invalido. Una transazione sul target effettua il CAS sull’`epoch` catturata da `prepare`, controlla l’attestazione del candidato e registra attivazione e chiave idempotente. Questo serializza le pubblicazioni. Un presupposto rimasto soltanto nel ragionamento dell’LLM sfugge al controllo.

## 4. Casi di test

Ogni riga riparte dalla 12. Quando entrambi sono pronti, assumo che A vinca il CAS. B riceve `STALE_LIVE` e richiama `prepare` con **base originale**, stesse operazioni e nuova chiave. Modelli e canali dei test sono abilitati. Per T4–T5 assumo che il contratto di `Branch` permetta una porta `no` scollegata con esito `skipped`. La lavagna lascia aperta questa decisione.

| Caso | A | B | Stato finale |
|---|---|---|---|
| T1 | Attiva `friendly`. | Riprepara, testa e attiva `email`. | Entrambe le modifiche. |
| T2 | Attiva `model-x`. | `CONFLICT` su `n2.model`, con `model-x` attuale e `model-y` richiesto. | `model-x`. |
| T3 | Attiva il nuovo modello. | Aggiunge `sentiment` e passa i test sul nuovo modello. | Modello e campo nuovi. |
| T4 | Elimina `n5,e4,e6` insieme. | `CONFLICT`, `n5` cancellato. | Ramo rimosso. Se vince B, A trova `n5` modificato e la cancellazione si ferma. |
| T5 | Rimuove il ramo `no`. | Il piano completo di B ridirige `e2` da `n2` a `n4` sulla porta `out` ed elimina `n3,n5,e3,e4,e6`. Trova cambiata la topologia e riceve `CONFLICT`. | Rimane A. B può rileggere e proporre il bypass residuo. Se vince B, rimane `n1→n2→n4→n6` e A trova il ramo già rimosso. |
| T6 | `INVALID_GRAPH` già sulla 12 se `Urgent?` legge `n2.urgency`. | Può pubblicare la sua condizione valida o il nuovo consumatore. | `urgency` resta disponibile. Se B fosse il *primo* consumatore, ciascun piano isolato passerebbe e il secondo fallirebbe in validazione dopo il rebase. |
| T7 | Inserisce `Translate`. | `CONFLICT` su `e2`, con i nuovi endpoint. | Solo `Translate`. L’ordine con `Redact PII` richiede una scelta esplicita. |
| T8 | Attiva il suo candidato. | Perde il CAS. | Nuovi run su A, run già assegnati alla 12 ancora sulla 12. |
| T9 | Dopo il timeout, stessa chiave e payload restituiscono il job o la ricevuta originaria. Se muore, la bozza inutilizzata scade. | Prosegue indipendentemente. | Al massimo un’attivazione per chiave, nessun lock abbandonato. |
| T10 | Pubblica sul target A. | Pubblica sul target B. | Due varianti con routing esplicito per tenant, trigger o coorte. Se rivendicano lo stesso traffico esclusivo, serve una decisione di prodotto. |

Se entrambe le uscite del branch sono obbligatorie, A fallisce già in `prepare` in T4 e T5. In T5 il bypass completo di B resta valido. La sola cancellazione di `n3` fallisce sempre per gli endpoint orfani.

## 5. Ciclo di vita

`read` → bozza → `prepare` → compilazione e test run con fixture ed effetti esterni simulati → `activate`. L’attestazione lega digest del grafo compilato, dipendenze fissate, suite e policy. Il target è un puntatore mutabile. Ogni run persiste la revisione all’ammissione e la riusa anche dopo una pausa di approvazione. Il rollback sposta il puntatore con un nuovo CAS a una revisione storica ancora ammessa. I messaggi Slack già inviati restano inviati.

Testerei il tool generando interleaving di preparazioni, attivazioni, crash e retry. Verificherei un solo vincitore per `epoch`, nessun puntatore a grafi invalidi o privi di attestazione, nessun doppio effetto da retry, e ripresa sulla 12 di un run sospeso prima del rollback.

## 6. Dove si rompe e quanto costa

Un target molto conteso causa ripetuti test e possibile starvation. Un candidato lungo può scadere continuamente. Il controllo semantico arriva fino ai contratti dichiarati e i test LLM campionano il comportamento. Riutilizzerei esiti soltanto a parità degli input attestati.

Sceglierei **spec intera con CAS** per workflow piccoli quando misuro che le collisioni sono rare e rileggere, rigenerare e ritestare costa meno che mantenere algebra delle operazioni e precondizioni.

## 7. Critica alla baseline

Il buco principale è tra «ciascuno testa la propria bozza» e «uniamo le modifiche». Due report verdi separati lasciano scoperto proprio l’artefatto da pubblicare. Anche «stesso nodo» è una granularità insufficiente, come mostrano T3 e T6. Liveblocks aiuta a vedere chi lavora dove. Un CRDT è adatto a layout, note e testo collaborativo. La convergenza delle repliche, da sola, permette anche che tutte convergano sul grafo rotto della lavagna.

## 8. Risposta parlata

«Partirei dal caso disegnato. Se tolgo il branch per mandare tutti in approvazione, la mia modifica comprende anche il nuovo collegamento dal classificatore all’approvazione. Il server deve poter accettare o rifiutare quell’intento per intero.

Darei all’agente tre tool. Legge una revisione, prepara un insieme di operazioni e attiva il candidato testato. Quando prepara, indica la revisione su cui ha ragionato. Se qualcuno ha cambiato il canale Slack, posso ancora cambiare il tono della risposta. Se qualcuno ha cancellato il nodo della risposta, ricevo un conflitto con l’ID e la modifica che lo ha causato.

Poi valido il grafo risultante, compresi i campi letti dai nodi a valle, ed eseguo i test proprio su quella revisione. Al deploy cambio il puntatore solo se la produzione è ancora quella osservata. Se perdo la corsa, ripreparo il mio intento sulla versione nuova e testo la combinazione. Un ticket già fermo in approvazione riprenderà sulla revisione con cui era partito.»
