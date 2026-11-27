# Editing concorrente di un workflow: la risposta

Lavagna del colloquio: «Concurrent workflow editing · test cases». Due o più agenti partono dalla stessa revisione del workflow di supporto (n1…n6), lo modificano in parallelo e poi lo vogliono in produzione.

## In breve

`edit({ spec })` riscrive tutto il workflow, quindi chi arriva secondo cancella il lavoro del primo. Lo sostituisco con un batch atomico di operazioni sul grafo, riferito alla revisione che l'agente ha letto.

Il server è l'unico punto di commit. Rifiuta il batch se collide con ciò che è stato salvato nel frattempo. Altrimenti lo riapplica sull'ultima revisione e salva solo se l'intero grafo risultante è valido. Le revisioni sono immutabili. La produzione è un puntatore che si sposta con un compare-and-swap, solo in avanti e solo su una revisione testata.

Con queste regole lo stato rotto del riquadro di destra non può essere salvato, in nessun ordine di arrivo. `prototipo.py`, nella stessa cartella, riproduce quello stato e fa girare i casi di questa pagina.

## Cosa mostra la lavagna

La lavagna contiene due guasti diversi.

1. **Scritture perse.** Con `read_spec()` e `edit({ spec })` ogni agente legge tutto, modifica la sua copia e riscrive tutto. Il secondo che scrive parte da una lettura vecchia e cancella in silenzio la modifica del primo.
2. **Un'unione che dà un grafo invalido.** Il riquadro di destra è ciò che si ottiene unendo due modifiche elemento per elemento: un agente toglie n5 con i suoi archi, l'altro toglie n3. Tutti vedono lo stesso stato, ma l'arco e2 arriva a un nodo che non c'è più e l'etichetta «yes» parte dal vuoto.

Il JSON Schema da solo non ferma il secondo guasto: quel grafo rotto rispetta lo schema, perché «e2 arriva a un nodo che non esiste» non riguarda la forma del documento.

Servono quindi due garanzie separate: nessuna scrittura va persa, e nessuna revisione invalida può esistere.

## Schema del workflow

Il workflow di esempio, revisione 12:

```json
{
  "entry": "n1",
  "nodes": {
    "n1": { "type": "trigger", "name": "New support ticket", "config": { "source": "zendesk" } },
    "n2": { "type": "llm", "name": "Classify", "config": { "model": "gpt-4.1", "fields": ["urgency", "topic"] } },
    "n3": { "type": "branch", "name": "Urgent?", "inputs": { "value": { "node": "n2", "field": "urgency" } } },
    "n4": { "type": "human", "name": "Human approval", "config": { "required": true } },
    "n5": { "type": "llm", "name": "Draft reply", "config": { "tone": "angry" } },
    "n6": { "type": "output", "name": "Send", "config": { "channel": "slack" } }
  },
  "edges": {
    "e1": { "from": "n1", "to": "n2", "on": "next" },
    "e2": { "from": "n2", "to": "n3", "on": "next" },
    "e3": { "from": "n3", "to": "n4", "on": "yes" },
    "e4": { "from": "n3", "to": "n5", "on": "no" },
    "e5": { "from": "n4", "to": "n6", "on": "next" },
    "e6": { "from": "n5", "to": "n6", "on": "next" }
  }
}
```

Le scelte che contano:

- **Nodi e archi sono mappe indicizzate per ID stabile, non array.** Un'operazione nomina il suo bersaglio, e due inserimenti concorrenti non spostano gli indici l'uno dell'altro. Gli ID li genera chi crea il nodo, così due agenti non creano entrambi «n7».
- **`inputs` dichiara quale campo a monte legge un nodo.** La dipendenza di n3 da `n2.urgency` diventa un dato controllabile, invece di restare nel testo di una condizione.
- **`on` nomina l'uscita.** Un branch ha `yes` e `no`, gli altri nodi `next`. `END` è la destinazione riservata per dire «questo ramo finisce qui».
- **La revisione non sta nella spec.** Sta sull'involucro: `{ workflow_id, revision, parent, spec }`.
- **Posizione e direzione dei box stanno fuori.** Sono layout del canvas. Se restano nella spec, spostare un box va in conflitto con chi cambia la logica.

Rispetto agli appunti a mano: `nome` è `name`, `tipo` è `type`, `parti variabili` è `config`, `versione` è la revisione dell'involucro, `posizione` e `direzione` vanno nel layout.

Il JSON Schema che valida la forma:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:workflow:spec:v1",
  "type": "object",
  "required": ["entry", "nodes", "edges"],
  "additionalProperties": false,
  "properties": {
    "entry": { "$ref": "#/$defs/id" },
    "nodes": {
      "type": "object",
      "minProperties": 1,
      "propertyNames": { "$ref": "#/$defs/id" },
      "additionalProperties": { "$ref": "#/$defs/node" }
    },
    "edges": {
      "type": "object",
      "propertyNames": { "$ref": "#/$defs/id" },
      "additionalProperties": { "$ref": "#/$defs/edge" }
    }
  },
  "$defs": {
    "id": { "type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$", "not": { "const": "END" } },
    "ref": {
      "type": "object",
      "required": ["node", "field"],
      "additionalProperties": false,
      "properties": { "node": { "$ref": "#/$defs/id" }, "field": { "type": "string", "minLength": 1 } }
    },
    "node": {
      "type": "object",
      "required": ["type", "name"],
      "additionalProperties": false,
      "properties": {
        "type": { "enum": ["trigger", "llm", "branch", "human", "output"] },
        "name": { "type": "string", "minLength": 1 },
        "config": { "type": "object" },
        "inputs": {
          "type": "object",
          "propertyNames": { "$ref": "#/$defs/id" },
          "additionalProperties": { "$ref": "#/$defs/ref" }
        }
      },
      "allOf": [
        {
          "if": { "properties": { "type": { "const": "trigger" } } },
          "then": { "required": ["config"], "properties": { "config": { "required": ["source"] } } }
        },
        {
          "if": { "properties": { "type": { "const": "branch" } } },
          "then": { "required": ["inputs"], "properties": { "inputs": { "required": ["value"] } } }
        },
        {
          "if": { "properties": { "type": { "const": "output" } } },
          "then": { "required": ["config"], "properties": { "config": { "required": ["channel"] } } }
        },
        {
          "if": { "properties": { "type": { "const": "llm" } } },
          "then": {
            "properties": {
              "config": { "properties": { "fields": { "type": "array", "items": { "type": "string" }, "uniqueItems": true } } }
            }
          }
        }
      ]
    },
    "edge": {
      "type": "object",
      "required": ["from", "to", "on"],
      "additionalProperties": false,
      "properties": {
        "from": { "$ref": "#/$defs/id" },
        "to": { "anyOf": [{ "$ref": "#/$defs/id" }, { "const": "END" }] },
        "on": { "enum": ["next", "yes", "no"] }
      }
    }
  }
}
```

Quello che lo schema non può esprimere lo controlla il validatore del server, sull'intero grafo, prima di ogni commit:

| Regola | Violazione |
|---|---|
| Ogni arco parte da un nodo esistente e arriva a un nodo esistente o a `END` | `DANGLING_EDGE` |
| Ogni uscita ha un solo arco, del tipo giusto per il nodo | `DUPLICATE_PORT`, `BAD_PORT` |
| Un branch ha sia `yes` sia `no`; ogni altro nodo, tranne l'output, ha il suo `next` | `MISSING_OUTLET` |
| Ogni nodo è raggiungibile dall'entry e non ci sono cicli | `UNREACHABLE_NODE`, `CYCLE` |
| Ogni campo letto esiste ed è prodotto a monte su ogni percorso | `MISSING_INPUT`, `INPUT_NOT_UPSTREAM` |

## I quattro tool

Tengo i due nomi della lavagna, cambio ciò che riceve `edit` e ne aggiungo due.

| Tool | Quando lo chiama l'agente | Riceve | Restituisce |
|---|---|---|---|
| `read_spec` | All'inizio, e dopo ogni `CONFLICT`, `MERGE_INVALID` o `LIVE_MOVED` | `workflow_id`, `revision` (facoltativa) | La spec, la sua revisione, la head, la live, i commit recenti con autore e intento |
| `edit` | Una volta per ogni intento completo | `workflow_id`, `base_revision`, `ops`, `intent`, `request_id`, `dry_run` | La nuova revisione e le revisioni sopra cui è stato riapplicato |
| `test` | Dopo `edit`, sulla revisione restituita | `workflow_id`, `revision` | `test_id`, esito, traccia |
| `deploy` | Solo se il compito chiede la produzione | `workflow_id`, `revision`, `expect_live`, `test_id` | La nuova live |

I tool hanno permessi separati: chi può modificare non è detto che possa pubblicare. `edit` crea una revisione e non ha effetti esterni, `deploy` cambia ciò che risponde ai clienti.

La definizione di `edit`:

```json
{
  "name": "edit",
  "description": "Applica al workflow un batch atomico di operazioni: o tutte o nessuna. Il batch deve contenere l'intento completo: se togli un nodo, sistema nello stesso batch gli archi che lo toccano. Non manda mai la spec intera.",
  "input_schema": {
    "type": "object",
    "required": ["workflow_id", "base_revision", "ops", "intent", "request_id"],
    "additionalProperties": false,
    "properties": {
      "workflow_id": { "type": "string", "minLength": 1 },
      "base_revision": {
        "type": "integer",
        "minimum": 1,
        "description": "La revisione restituita dall'ultima read_spec. È quella su cui hai ragionato."
      },
      "intent": {
        "type": "string",
        "minLength": 1,
        "description": "Una frase su cosa vuoi ottenere. La legge l'altro agente se va in conflitto con te."
      },
      "request_id": {
        "type": "string",
        "minLength": 1,
        "description": "Chiave di idempotenza. Se ripeti la chiamata dopo un timeout, riusa la stessa."
      },
      "dry_run": {
        "type": "boolean",
        "default": false,
        "description": "Se true, esegue tutti i controlli e restituisce l'esito senza salvare."
      },
      "ops": {
        "type": "array",
        "minItems": 1,
        "items": {
          "oneOf": [
            {
              "type": "object",
              "required": ["op", "node", "key", "value"],
              "additionalProperties": false,
              "properties": { "op": { "const": "set" }, "node": { "type": "string" }, "key": { "type": "string" }, "value": {} }
            },
            {
              "type": "object",
              "required": ["op", "node", "key", "item"],
              "additionalProperties": false,
              "properties": {
                "op": { "enum": ["add_item", "remove_item"] },
                "node": { "type": "string" },
                "key": { "type": "string" },
                "item": { "type": "string" }
              }
            },
            {
              "type": "object",
              "required": ["op", "node", "name", "ref"],
              "additionalProperties": false,
              "properties": {
                "op": { "const": "set_input" },
                "node": { "type": "string" },
                "name": { "type": "string" },
                "ref": {
                  "type": "object",
                  "required": ["node", "field"],
                  "additionalProperties": false,
                  "properties": { "node": { "type": "string" }, "field": { "type": "string" } }
                }
              }
            },
            {
              "type": "object",
              "required": ["op", "id", "node"],
              "additionalProperties": false,
              "properties": {
                "op": { "const": "add_node" },
                "id": { "type": "string" },
                "node": { "type": "object", "required": ["type", "name"] }
              }
            },
            {
              "type": "object",
              "required": ["op", "id"],
              "additionalProperties": false,
              "properties": { "op": { "enum": ["remove_node", "remove_edge"] }, "id": { "type": "string" } }
            },
            {
              "type": "object",
              "required": ["op", "id", "edge"],
              "additionalProperties": false,
              "properties": {
                "op": { "const": "add_edge" },
                "id": { "type": "string" },
                "edge": {
                  "type": "object",
                  "required": ["from", "to"],
                  "additionalProperties": false,
                  "properties": {
                    "from": { "type": "string" },
                    "to": { "type": "string" },
                    "on": { "enum": ["next", "yes", "no"] }
                  }
                }
              }
            },
            {
              "type": "object",
              "required": ["op", "id"],
              "minProperties": 3,
              "additionalProperties": false,
              "properties": {
                "op": { "const": "set_edge" },
                "id": { "type": "string" },
                "from": { "type": "string" },
                "to": { "type": "string" },
                "on": { "enum": ["next", "yes", "no"] }
              }
            },
            {
              "type": "object",
              "required": ["op", "revision"],
              "additionalProperties": false,
              "properties": { "op": { "const": "restore" }, "revision": { "type": "integer", "minimum": 1 } }
            }
          ]
        }
      }
    }
  }
}
```

`remove_node` non cancella a cascata gli archi. È voluto: chi toglie un nodo deve dire dove vanno a finire i collegamenti, e se non lo dice il batch è invalido.

Gli errori li legge un LLM, quindi ognuno dice cosa è successo e cosa fare dopo.

| Errore | Significato | Cosa fa l'agente |
|---|---|---|
| `INVALID_EDIT` | Il batch lascia il grafo invalido già sulla revisione letta | Completa l'intento nello stesso batch e rimanda |
| `CONFLICT` | Dopo la sua base, qualcuno ha salvato qualcosa che il batch scrive o dà per letto | Rilegge la head, decide se l'intento ha ancora senso, rimanda con la nuova base |
| `MERGE_INVALID` | Il batch era valido da solo, ma non insieme alle revisioni arrivate dopo | Rilegge e riformula |
| `KEY_REUSED` | Stessa `request_id` con contenuto diverso | Usa una nuova `request_id` |
| `LIVE_MOVED` | La produzione è cambiata dopo la sua lettura | Se la live contiene già la sua revisione ha finito, altrimenti riprova indicando la live attuale |
| `NOT_FORWARD` | La revisione non è più avanti della live: pubblicarla annullerebbe lavoro altrui | Si ferma; per tornare indietro si usa l'operazione `restore` |
| `TEST_REQUIRED` | Manca un test passato sul contenuto esatto di quella revisione | Chiama `test` su quella revisione |

Un `CONFLICT` come lo restituisce il prototipo:

```json
{
  "ok": false,
  "error": "CONFLICT",
  "head": 13,
  "conflicts": [
    {
      "key": "nodes/n2/config/model",
      "changed_in": 13,
      "by": "agente-A",
      "their_intent": "classificatore meno costoso"
    }
  ],
  "next": "Niente è stato applicato. Rileggi la revisione 13, decidi se il tuo intento ha ancora senso e rimanda con base_revision 13."
}
```

Un errore da aggiungere, che il prototipo non ha: `ESCALATE`, quando lo stesso campo viene conteso più volte dagli stessi agenti. Senza, il perdente di un conflitto può ripartire dalla nuova base e sovrascrivere, l'altro fa lo stesso, e i due vanno avanti all'infinito.

## Quando due modifiche si toccano

Ogni operazione dichiara due insiemi di chiavi: ciò che scrive e ciò che dà per letto.

| Operazione | Scrive | Dà per letto |
|---|---|---|
| `set` su `n2.model` | `nodes/n2/config/model` | n2 esiste |
| `add_item` di `sentiment` su `n2.fields` | `nodes/n2/config/fields/sentiment` | n2 esiste |
| `set_input`: n3 legge `n2.urgency` | `nodes/n3/inputs/value` | n3 esiste, `nodes/n2/config/fields/urgency` |
| `add_node`, `remove_node` | tutto il nodo: `nodes/n5` | per `add_node`, i campi letti dai suoi `inputs` |
| `add_edge`, `set_edge`, `remove_edge` | l'arco e l'uscita che occupa: `edges/e4`, `ports/n3/no` | i due estremi esistono |
| `restore` | tutto il workflow | niente |

Due chiavi si toccano se sono uguali o se una contiene l'altra: cancellare `nodes/n5` tocca `nodes/n5/config/tone`.

Un batch collide con un commit arrivato dopo la sua base in due casi:

1. una chiave che il batch scrive o dà per letta tocca una chiave scritta da quel commit;
2. una chiave che il batch scrive tocca una chiave data per letta da quel commit.

Se non c'è collisione, il server riapplica il batch sulla head e valida l'intero grafo. Sono due difese indipendenti: se le chiavi non vedono una dipendenza, la vede il validatore, e il batch torna come `MERGE_INVALID`.

Il commit è una transazione per workflow con un compare-and-swap sulla head. È controllo di concorrenza ottimistico: nessun lock, quindi un agente che muore a metà non lascia niente da liberare.

## Ciclo di vita

- **Immutabili:** le revisioni, le prove di test (legate al contenuto della revisione), la revisione su cui gira ogni run.
- **Puntatori:** `head`, che avanza solo con un commit, e `live`, che si sposta solo con un deploy.

La sequenza per l'agente:

1. `read_spec`.
2. `edit` con l'intento completo. Con `dry_run` se vuole prima vedere l'esito.
3. Su `CONFLICT` o `MERGE_INVALID`: rilegge, ripianifica, rimanda.
4. `test` sulla revisione restituita. I connettori sono simulati: nessun messaggio vero su Slack.
5. `deploy` indicando la live che ha osservato.

Tre regole sul deploy:

- **Solo in avanti.** Il compare-and-swap da solo non basta. Se B perde la corsa e riprova con il nuovo valore atteso, pubblica una revisione che non contiene il lavoro di A e lo cancella in silenzio. Con una storia lineare il controllo è semplice: la revisione deve essere più avanti della live.
- **Il rollback è un commit.** Un `edit` con l'operazione `restore` crea una revisione nuova con il contenuto di una già pubblicata, e la si pubblica come le altre. La prova di test vale ancora, perché il contenuto è identico. Il costo: i commit arrivati dopo la revisione ripristinata vanno rifatti.
- **I run restano sulla loro revisione.** Un ticket fermo in Human approval può aspettare giorni: quando riparte, finisce sulla revisione con cui era entrato.

Spostare indietro il solo puntatore live sarebbe più rapido, ma la head conterrebbe ancora la modifica ritirata e il deploy successivo la riporterebbe in produzione. Con il rollback come commit, head e live non divergono e la regola «solo in avanti» non ha eccezioni.

## Casi di test

Tutti partono dalla revisione 12. Gli esiti sono l'output di `prototipo.py`, nei due ordini di arrivo.

| Caso | Arriva prima A | Arriva prima B | Stato finale |
|---|---|---|---|
| **T1** A cambia `n5.tone`, B cambia `n6.channel` | A 13, B 14 | B 13, A 14 | Entrambe le modifiche |
| **T2** A e B cambiano `n2.model` | A 13, B `CONFLICT` | B 13, A `CONFLICT` | Il modello di chi arriva prima |
| **T3** A cambia `n2.model`, B aggiunge `sentiment` a `n2.fields` | A 13, B 14 | B 13, A 14 | Entrambe le modifiche |
| **T4** A toglie n5, B cambia `n5.tone` | A 13, B `CONFLICT`: n5 non c'è più | B 13, A `CONFLICT`: n5 è cambiato dopo la lettura di A | Mai un nodo modificato e cancellato insieme |
| **T5** A toglie il ramo «no», B toglie il branch | A 13, B `CONFLICT`; B rilegge, ripianifica, 14 | B 13, A `CONFLICT`: il branch non c'è più | `n1→n2→n4→n6` in entrambi gli ordini |
| **T6** A toglie `topic` da `n2.fields`, B aggiunge un nodo che legge `topic` | A 13, B `CONFLICT` su `n2.fields.topic` | B 13, A `CONFLICT` sulla stessa chiave | La modifica di chi arriva prima |
| **T7** A inserisce Translate su e2, B inserisce Redact PII su e2 | A 13, B `CONFLICT` su e2 | B 13, A `CONFLICT` su e2 | Un solo inserimento |
| **T8** Corsa al deploy: A ha la 13, B la 14 | Live 13, B `LIVE_MOVED`, riprova, live 14 | Live 14, A `LIVE_MOVED`: la live contiene già la 13 | Live 14; il run in corso resta sulla 12 |
| **T9** A ripete la chiamata dopo un timeout | Stessa revisione 13, nessuna nuova | | Stessa chiave con contenuto diverso: `KEY_REUSED` |
| **Rollback** La 13 è in produzione ed è sbagliata | `restore` della 12 crea la 14, pubblicata con la prova della 12 | | Head 14 e live 14, con il contenuto della 12 |

Quattro note sui casi.

- **Il riquadro di destra nasce da due batch incompleti.** «Togli n5 con e4 ed e6» lascia il branch senza il ramo «no»: `INVALID_EDIT` già da solo. «Togli n3» lascia tre archi orfani: `INVALID_EDIT` già da solo. Nessuno dei due viene salvato. In T5 i due intenti sono completi: A dichiara che il ramo «no» finisce a `END`, B ricollega e2 a n4 e toglie ciò che resta irraggiungibile.
- **In T6 ogni batch è valido per conto suo.** `topic` non lo legge ancora nessuno, quindi toglierlo va bene, e aggiungere un nodo che lo legge va bene: è l'unione che non sta in piedi. Togliere `urgency`, invece, è invalido già da solo, perché n3 la legge.
- **In T7 il conflitto è voluto.** L'ordine tra Redact PII e Translate cambia cosa viene mandato al traduttore. Non lo deve scegliere il server.
- **T10, due varianti entrambe in produzione, non è un problema di concorrenza.** Il fork ingenuo duplica il trigger Zendesk e ogni ticket riceve due risposte. Le strade sono un trigger disgiunto, uno split di traffico sul puntatore live, o una decisione del proprietario.

## Tre varianti, un solo meccanismo

Il meccanismo è sempre lo stesso: batch riferito a una base, controllo delle collisioni, riapplicazione, validazione dell'intero grafo, revisione immutabile, puntatore spostato con compare-and-swap. Cambiano due manopole: quanto è fine l'insieme di ciò che si dà per letto, e su quale puntatore si integrano le modifiche.

| Variante | Cosa manda l'agente | Dove si integrano le modifiche | Quando conviene |
|---|---|---|---|
| **A. Spec intera con controllo di revisione** | Tutta la spec e la `base_revision` | Da nessuna parte: se la head è cambiata l'agente rilegge e rifà | Pochi agenti per workflow, collisioni rare, spec piccola |
| **B. Linea condivisa** (questa pagina) | Un batch di operazioni e la `base_revision` | A ogni commit, sulla head | Il caso generale, ed è quello della lavagna |
| **C. Un candidato per agente** | Un batch, che diventa una revisione privata | Al deploy, sulla live, con un nuovo test obbligatorio | Modifiche lunghe, test costosi, o la regola «pubblico solo il mio» |

La variante A è la B con «ho letto tutto il workflow» come unica chiave: T1 e T3 diventano conflitti. È un punto di partenza legittimo, e si passa alla B senza cambiare tool, perché la finezza del conflitto è una politica del server.

La variante C è la B senza `head`: la linea condivisa è la produzione stessa. Scopre i conflitti tardi e ritesta dopo ogni riallineamento. In cambio, il deploy di un agente non porta con sé commit altrui. Qui conviene che il server conservi l'intento: dopo una corsa persa l'agente lo ripresenta senza riscrivere le operazioni, e più intenti si possono preparare e testare insieme come un'unica release.

## Rispetto alla risposta data al colloquio

Restano validi: il grafo versionato con ID stabili, le operazioni riferite a una revisione, le revisioni immutabili, il compare-and-swap al deploy, la presenza in tempo reale.

Da correggere o aggiungere:

1. **«Se non si toccano le unisco» era l'intera domanda.** Va definito, come nella sezione sopra.
2. **La validazione è una condizione di ogni commit,** non un controllo prima del deploy. Così una revisione invalida non esiste.
3. **Una bozza per agente con test separati non prova niente sul grafo unito.** Il test va fatto sulla revisione esatta che si pubblica.
4. **Il compare-and-swap sulla live non basta.** Serve il vincolo «solo in avanti», e il rollback va fatto come commit.
5. **«Crea un nuovo workflow» duplica il trigger.**
6. **Avvisi e conferme sono un controllo per le persone.** Un agente LLM conferma qualsiasi cosa. Per gli agenti l'equivalente è l'errore strutturato, più `ESCALATE` quando due insistono sullo stesso campo.
7. **Liveblocks o un CRDT garantiscono che le copie convergano, non che il grafo sia valido.** Il loro posto è il canvas: presenza, cursori, posizione dei box, il testo di un prompt mentre lo si scrive. Non stanno sul percorso che porta in produzione. Il lato interfaccia, con Liveblocks e WebMCP, è in `interfaccia-liveblocks-webmcp.md`.
8. **Mancavano** l'idempotenza delle chiamate, l'agente che muore a metà, i run in corso, e la separazione dei permessi tra chi modifica e chi pubblica.

## Come si testa

Il workflow si testa sulla revisione esatta che va in produzione, con i connettori simulati. La prova è legata a quella revisione: se la revisione cambia, si ritesta.

Il tool si testa così:

1. I casi della lavagna come test tabellari, in tutti gli ordini di arrivo.
2. Una verifica su molti gruppi di batch concorrenti, con quattro invarianti: ogni revisione salvata è valida; nessuna scrittura accettata va persa; un rifiuto non lascia traccia; un retry non crea revisioni.
3. Guasti iniettati: risposta persa dopo il commit, retry, deploy concorrenti, rollback durante una corsa.
4. Una valutazione con agenti veri: davanti a un `CONFLICT`, l'agente rilegge e ripianifica, o ritenta identico?

## Dove si rompe

- **Contesa.** Ogni conflitto costa una rilettura e una ripianificazione. Su un workflow molto conteso chi manda batch grandi può non passare mai. Lì servono `ESCALATE` o una coda a scrittore unico per quel workflow.
- **Dipendenze nel testo libero.** Se un prompt nomina «urgency» in prosa, non la vedono né le chiavi né il validatore. La vede solo il test.
- **Linea condivisa.** Il deploy di B pubblica anche i commit di A che stanno sotto, e un commit valido ma scadente di A fa fallire i test di B. La regola è: un batch, un intento completo, e la head sempre pubblicabile. Se non è accettabile, si passa alla variante C.
- **Il validatore è il componente critico.** Ogni regola che manca è un buco.
- **Due modifiche compatibili possono dare un insieme che nessuno voleva.** Non è concorrenza: serve una revisione umana del diff prima del deploy.

## Cosa è verificato e cosa no

`prototipo.py` implementa `edit` con tutte le operazioni, `deploy`, l'idempotenza, i run agganciati alla revisione e il validatore. Esegue T1–T9 nei due ordini, il rollback, e 2.366 gruppi ordinati di due e tre agenti, controllando i quattro invarianti.

I controlli sono stati provati anche al contrario, rompendo una regola alla volta (`verifiche/prova_mutazioni.py`). Si accorgono di: collisioni spente, validazione saltata dopo il rebase, deploy senza compare-and-swap, deploy che torna indietro, prova di test non legata al contenuto, idempotenza assente.

Gli schemi JSON di questa pagina sono stati controllati con un validatore (`verifiche/controlla_schemi.py`): sono JSON Schema 2020-12 validi, il workflow di esempio li rispetta, e lo schema di `edit` accetta tutti i batch dei casi e rifiuta `edit({ spec })`.

Non è verificato:

- La concorrenza vera. Il prototipo esegue gli arrivi in sequenza e modella il punto di commit come già serializzato; non usa thread né un database.
- `test`, che nel prototipo è un segnaposto: percorre i due rami e controlla che arrivino in fondo.
- `dry_run`, `ESCALATE`, il fork e lo split di traffico, che sono descritti qui ma non implementati.

## Risposta parlata

«Parto dal riquadro di destra, perché il problema vero è lì. Ogni modifica da sola era sensata, il risultato unito è un grafo con archi che non portano da nessuna parte. Quindi non mi basta evitare che due agenti si sovrascrivano: una revisione invalida non deve poter essere salvata.

Per questo cambio quello che riceve `edit`. Invece della spec intera, l'agente manda un batch di operazioni sul grafo, con la revisione che ha letto e una chiave di idempotenza. Il batch è atomico e contiene l'intento completo: se tolgo il branch, nello stesso batch ricollego il classificatore all'approvazione.

Il server è l'unico punto di commit. Se nel frattempo è arrivato altro, controlla se le due modifiche toccano lo stesso campo, lo stesso arco, o un dato che l'altra legge. Se sì, mi torna un conflitto che dice cosa è cambiato, chi l'ha cambiato e cosa fare. Se no, riapplica il mio batch sull'ultima revisione, valida tutto il grafo e solo allora salva.

Le revisioni sono immutabili. I test girano sulla revisione esatta che va in produzione, e il deploy è un compare-and-swap sul puntatore live che va solo in avanti, così chi arriva secondo non cancella il primo. I ticket già fermi in approvazione finiscono sulla revisione con cui sono partiti.

Liveblocks lo tengo per quello che fa bene: presenza, cursori, layout. La correttezza sta nel commit.»
