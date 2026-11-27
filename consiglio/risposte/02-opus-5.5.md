# Risposta di Claude Opus 5.5, effort predefinito

Testo integrale, come l'ha scritto il modello. Non è stato corretto: dove sbaglia, lo dice `chi-ha-lavorato.md`.

---

## 1. Tesi

Non partirei dai lock né dai CRDT. Gli agenti mandano **changeset atomici di operazioni tipizzate**, con una revisione base e precondizioni sui path che hanno letto. Il server li serializza per workflow, fa un rebase automatico se le precondizioni reggono ancora e **valida il grafo intero prima di ogni commit**.

Ne segue che ogni revisione committata è valida per costruzione. Il deploy è un puntatore che si sposta solo con CAS e solo in avanti nella storia. Lo stato del riquadro di destra non si può committare: oltre a non arrivare in produzione, non esiste come revisione.

## 2. Superficie dei tool

Bastano quattro tool. Per T10 serve un quinto, `create_workflow`, che la piattaforma ha comunque.

**Schema del workflow.** Nodi e archi stanno in mappe, non in array, così i path restano stabili. Le dipendenze di dati sono esplicite.

```ts
type Workflow = { id; revision: number; parent: number; hash: string; entry: NodeId;
  nodes: Record<NodeId, { type: "trigger"|"llm"|"branch"|"human"|"output";
    toolRef: string;              // "llm@3": config validata dal JSON Schema di quel toolRef
    config: object;
    inputs?: Record<string, { node: NodeId; field: string }>;  // es. n3.inputs.u = {node:"n2", field:"urgency"}
    outputs?: string[] }>;
  edges: Record<EdgeId, { from: NodeId; to: NodeId | "END"; on?: string }>;
  layout?: Record<NodeId, { x: number; y: number }>;  // escluso dai conflitti, last-writer-wins
}
```

**`read_workflow`**: l'agente lo chiama all'inizio e dopo ogni CONFLICT.
Input: `{workflow_id, revision?, since_revision?}`.
Risultato: la spec, `head_revision`, `live_revision`, i commit successivi a `since_revision` (con autore e `intent`), i changeset recenti di altri agenti. Quest'ultima informazione è puramente indicativa.

**`change_workflow`**: l'agente lo chiama una volta per ogni intento, con tutte le operazioni che servono a quell'intento.

```ts
{ workflow_id; base_revision: number; intent: string; request_id: string; dry_run?: boolean;
  strictness?: "paths" | "entities" | "workflow";   // default "paths"
  expect?: { path: string; equals?: any }[];        // read set esplicito aggiuntivo
  ops: ( {op:"set"; path; value} | {op:"add_to_set"|"remove_from_set"; path; value}
       | {op:"add_node"; id?; node} | {op:"remove_node"; id; edges:"must_be_none"|"remove_incident"}
       | {op:"add_edge"; id?; edge} | {op:"remove_edge"; id} | {op:"set_edge"; id; from?; to?; on?} )[] }
```

In caso di successo restituisce `{revision, rebased_over:[{rev, by, intent}], noops:[op_index], diff, warnings}`.

Gli errori sono pensati per chi li legge, cioè un LLM. Ogni errore porta un campo `next`:

```json
{"ok":false,"error":"CONFLICT","head_revision":13,
 "conflicts":[{"op_index":0,"path":"/nodes/n2/config/model","you_expected":"gpt-4.1",
   "current":"model-x","changed_in":13,"by":"agent-A","their_intent":"cheaper classifier"}],
 "next":"Your change was NOT applied. Decide if it still makes sense given agent-A's change; resubmit with base_revision 13."}
```

Gli altri errori:
- `INVALID`: errori del validatore, con path e codice, per esempio `DANGLING_EDGE e2.to=n3` o `MISSING_INPUT n3.inputs.u -> n2.urgency`. Se un rebase è avvenuto, l'errore indica quale commit intermedio ha causato il problema.
- `BAD_OP`: viola lo schema delle operazioni.
- `BASE_TOO_OLD`: la base è troppo vecchia. Va riletto il workflow.

**`test_workflow`**: l'agente lo chiama dopo un commit e prima del deploy.
Input: `{workflow_id, revision, suite?|cases?, request_id}`.
Risultato: `{status:"passed"|"failed"|"pending", results[], trace_ids}`. Il risultato è legato all'hash della revisione e quindi va in cache. Per il polling si richiama con lo stesso `request_id`.

**`deploy_workflow`**: l'agente lo chiama solo se il compito richiede la produzione e la revisione ha passato i test.
Input: `{workflow_id, revision, expected_live_revision, request_id, reason, allow_revert?: boolean}`.
Risultato: `{live, previous_live, runs_pinned_to_previous: n}`.
Errori:
- `LIVE_MOVED`: riporta la live attuale, chi l'ha spostata e se la tua revisione la contiene già.
- `NOT_FAST_FORWARD`: la revisione proposta non discende dalla live, quindi la ripristinerebbe a uno stato precedente. Va passato `allow_revert` in modo esplicito.
- `NOT_TESTED`.

## 3. Semantica di concorrenza

Per ogni operazione il server calcola un **read set**: i path che scrive, l'esistenza delle entità che tocca e gli `expect` espliciti. Su `entities` il read set si allarga all'intero nodo, su `workflow` diventa il CAS globale della baseline. Il server tiene anche, per ogni path, la revisione dell'ultima modifica.

**Due modifiche «si toccano» se vale una di queste tre condizioni:**
1. Un path nel read set è stato modificato dopo `base_revision` e ora ha un valore diverso da quello che aveva alla base. Il confronto è per valore, così le scritture identiche non generano falsi conflitti.
2. Un'operazione richiede un'entità che è stata cancellata.
3. Il grafo che risulta dal rebase non passa la validazione.

**Che cosa controlla la validazione:** JSON Schema, integrità referenziale, raggiungibilità, outlet completi dei branch, tipi del dataflow tramite `inputs`, compatibilità dei `toolRef`.

**Dove avviene la serializzazione:** in un solo punto per workflow, `UPDATE … SET head=head+1 WHERE head=:h`. La concorrenza che non genera conflitti la assorbe un retry lato server: l'agente non spende token.

**Garantito:**
- ogni revisione committata è valida;
- la storia è lineare;
- non ci sono lost update sui path letti;
- il commit di un changeset è tutto-o-niente.

**Non garantito:**
- write skew su path non dichiarati;
- dipendenze implicite, per esempio un prompt che nomina «urgency» nel testo.

Le dipendenze implicite le coprono i test, non la concorrenza.

## 4. Casi di test (tutti dalla revisione 12)

| | A | B | Stato finale |
|---|---|---|---|
| T1 | ok → 13 | ok → 14, rebased_over 13 | entrambe le modifiche |
| T2 | primo: ok → 13 | CONFLICT su `/nodes/n2/config/model` (attuale `model-x`, di A) | model-x. Se B avesse scritto lo stesso valore: noop, ok |
| T3 | ok → 13 | `add_to_set` commuta con `set`: ok → 14 | model nuovo + sentiment |
| T4 | se A è primo: ok → 13 | CONFLICT `ENTITY_DELETED n5 by A` | senza n5 |
| T4' | se B è primo, il delete di A fallisce: «n5 modificato da B dopo la tua base». Chi cancella deve aver visto quello che cancella | ok → 13 | tone friendly; A decide di nuovo |
| T5 | ok → 13 (deve dire cosa succede al ramo «no», per esempio `no→END`, altrimenti INVALID già da solo) | vedi sotto | mai rotto |
| T6 | vedi sotto | vedi sotto | sempre valido |
| T7 | primo: ok | CONFLICT su `e2.to` | n2→Translate→n3. B ripianifica |
| T8 | vedi sotto | vedi sotto | live sempre in avanti |
| T9 | il retry restituisce la stessa risposta (13) | — | nessuna revisione duplicata |
| T10 | non lo decide la concorrenza | | vedi sotto |

**T5.** Il changeset di B deve gestire e2, e3 ed e4 in modo esplicito. `remove_node n3` con `edges:"must_be_none"` fallisce se ci sono archi incidenti.
- Se B ha incluso «rimuovi n5, e4, e6; e2.to=n4», sopra la 13 quelle cancellazioni diventano noop (l'intento è già soddisfatto). B ottiene ok → 14 con `noops` e `rebased_over: 13`. Grafo finale: n1→n2→n4→n6.
- Se il changeset di B lascia e2 o e3 appesi, riceve `INVALID: DANGLING_EDGE e2, e3` insieme al diff della 13.

Il riquadro di destra è esattamente ciò che succede quando si uniscono le operazioni senza un controllo che fermi il commit.

**T6.** In questo esempio, togliere `urgency` è già INVALID per A da solo, perché n3 legge quel campo tramite `inputs`. Se B aggiunge un nodo che usa `urgency`, chi arriva secondo riceve `MISSING_INPUT … removed in 13 by A`. Se la dipendenza è solo testuale non viene vista: la scopre `test_workflow`.

**T7.** Il conflitto qui è voluto. L'ordine tra Redact e Translate è una scelta semantica: la redazione dei dati personali va fatta prima di mandare il testo a un LLM. Un merge deterministico, come una insert su una lista CRDT, sceglierebbe l'ordine a caso.

**T8.** La serializzazione avviene sul puntatore live.
- Se la revisione di B (14) contiene la 13 di A: A spinge la 13 e B riceve `LIVE_MOVED`, con `contains_current_live: true`. B riprova con `expected=13` e il deploy è un fast-forward.
- Se fosse la 13 ad arrivare dopo la 14, sarebbe `NOT_FAST_FORWARD`.

I run già in corso restano agganciati alla revisione con cui sono partiti, perché ogni run fissa la propria revisione. Questo conta soprattutto per i run fermi su n4, che possono aspettare giorni. Le revisioni non si cancellano finché un run le usa.

**T9.**
- Retry dopo timeout: senza `request_id`, un `add_node` ripetuto creerebbe due nodi Translate.
- Agente che muore: non esistono lock né bozze persistenti, quindi non resta niente da liberare. Lo spazio di prova personale è `dry_run`, che restituisce la spec risultante, il diff e la validazione senza salvare stato. Ogni commit è atomico, quindi nessuno stato intermedio è visibile.

**T10.** Due workflow con lo stesso trigger su Zendesk mandano due risposte su Slack per ogni ticket. Le opzioni corrette:
- un fork con un trigger o un filtro disgiunto;
- uno split di traffico (esperimento) sul puntatore live;
- un'escalation all'orchestratore o a un umano.

Non va bene chiuderla con «creo un nuovo workflow» e basta.

## 5. Ciclo di vita

**Immutabili:** le revisioni (indirizzate per contenuto), i risultati dei test, la revisione fissata da ogni run.

**Puntatori:** `head` (la linea di sviluppo, che non è produzione) e `live`.

Sequenza delle chiamate:
1. `read_workflow`;
2. `change_workflow` con `dry_run`, se l'agente vuole esplorare, poi il commit;
3. su CONFLICT: rileggere, ripianificare, rimandare;
4. `test_workflow` sulla revisione esatta;
5. `deploy_workflow` con `expected_live_revision`.

Il rollback è un deploy di una revisione precedente con `allow_revert`. Rimette indietro il puntatore e non tocca i run in corso.

**Come testare il tool.** Generazione property-based di batch concorrenti a partire da una stessa base, poi verifica della storia, stile Jepsen. Le proprietà:
1. ogni revisione committata passa il validatore;
2. la storia equivale a una sequenza seriale dei soli changeset riusciti: rieseguirli in ordine produce la head;
3. ogni write riuscita è visibile oppure sovrascritta da qualcuno che l'aveva letta;
4. lo stesso `request_id` dà la stessa risposta e nessuna revisione in più;
5. la live si muove solo in avanti, salvo `allow_revert`;
6. ogni run punta a una revisione che esiste.

In più T1–T10 come golden test, e un'eval con agenti LLM veri: dato un CONFLICT o un INVALID, recuperano senza intervento umano?

## 6. Dove si rompe

- **Path molto contesi**, come lo stesso prompt modificato da cinque agenti: conflitti ripetuti, token sprecati, rischio di livelock. Mitigazione: backoff, oppure un lease opzionale solo su quel nodo.
- **Campi di testo trattati come valori atomici**: due modifiche a frasi diverse dello stesso prompt vanno in conflitto. Lo accetto.
- **Linea `head` condivisa**: B può fare il deploy di una revisione che contiene un intento di A non finito. Mitigazioni: changeset atomici per intento, test obbligatori, un diff verso la live con gli autori al momento del deploy. Se non basta, servono branch per agente.
- **Dipendenze implicite**: valgono solo i test, e la loro copertura non la so stimare.
- **Costo**: il validatore e il diff calcolato a ogni commit. Per grafi di queste dimensioni è trascurabile.

**Alternativa migliore: scrittura dell'intera spec con CAS sulla revisione più validazione**, cioè il punto di partenza della lavagna. Gli LLM scrivono JSON completo meglio di quanto compongano operazioni. Vince quando la probabilità che arrivi un altro commit mentre un agente fa read→modify→write è bassa (pochi agenti per workflow, poche percentuali di collisione) e la spec sta comodamente nel contesto: a quel punto rifare tutto costa meno di costruire un'algebra di operazioni.

Si possono anche ibridare: `change_workflow` accetta `spec` al posto di `ops`, il server ricava le operazioni con un merge a tre vie (base, head, proposta) e da lì il percorso è lo stesso. Non sono sicuro che il diff riconosca bene le operazioni tra «nodo spostato» e «cancellato e ricreato».

## 7. Critica alla baseline

- **«Si toccano» non è definito.** Senza read set e senza una validazione post-rebase che fermi il commit, si arriva proprio al riquadro di destra.
- **Una bozza per agente sposta il merge al deploy**, il punto peggiore per scoprire un conflitto.
- **Il CAS sulla live da solo non basta.** Se B fa il deploy della propria revisione derivata dalla 12 dopo che A ha spostato la live, e riprova con il nuovo `expected`, cancella in silenzio il lavoro di A. Serve il controllo di fast-forward.
- **Mancano:** idempotenza, revisione fissata dai run (con attese umane lunghe), dipendenze di dati esplicite per T6, il trattamento della cancellazione di cose già cancellate, le scritture identiche come noop, errori leggibili da un LLM, test legati all'hash della revisione.
- **«Crea un nuovo workflow»** ignora il doppio trigger.

**Liveblocks** è presenza pensata per umani. Gli agenti non vedono cursori, e la presenza è comunque solo indicativa: non può reggere la correttezza. Per un agente, il suo equivalente è il campo dei changeset recenti in `read_workflow`.

**Un CRDT** garantisce che le copie convergano, non che il risultato sia valido: il riquadro di destra è proprio ciò verso cui convergerebbe. Il suo posto giusto è l'editing umano del canvas (`layout`) o del testo dei prompt dentro l'editor, sempre a monte del controllo di validazione al commit.

## 8. Risposta parlata

«Ho ripensato al problema partendo dal riquadro di destra. Lì ogni modifica era plausibile da sola, ma il risultato è un grafo rotto. Quindi il punto non è evitare le sovrascritture: è che non deve mai esistere una revisione invalida.

Il tool che disegno riceve un changeset atomico di operazioni tipizzate, tipo set di un campo, aggiunta a un set, rimozione di un nodo con gestione esplicita degli archi. Insieme mando la revisione da cui sono partito e una request id per l'idempotenza.

Il server serializza per workflow. Per ogni operazione controlla il read set: i path che scrivo devono avere ancora il valore che avevo letto. Se reggono, fa il rebase sulla head e valida tutto il grafo: schema, riferimenti, outlet dei branch e dipendenze di dati, che dichiaro in modo esplicito negli input dei nodi. Solo allora committa.

Se c'è un conflitto, l'agente riceve un errore pensato per un LLM: il path, il valore che si aspettava, quello attuale, chi l'ha cambiato e cosa fare dopo.

Le revisioni sono immutabili. I test si legano all'hash della revisione. Il deploy è un compare-and-swap sul puntatore live che va solo in avanti, quindi nessuno annulla in silenzio il deploy di un altro, e i run in corso restano sulla revisione con cui sono partiti.

Liveblocks o un CRDT li userei solo per l'editing umano del canvas, perché garantiscono che le copie convergano, non che il grafo sia valido.»
