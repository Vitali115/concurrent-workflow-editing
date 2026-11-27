# Il brief dato ai consulenti

Tutti e sei hanno ricevuto questo testo, e nient'altro: nessuno conosceva le risposte degli altri né la posizione dell'orchestratore. Ai primi quattro la prima riga diceva «uno di quattro consulenti», agli ultimi due «uno di più consulenti». Qui è stato tolto solo il percorso locale dello screenshot.

La «baseline» citata nel brief è la risposta a cui ero arrivato prima del consiglio. I dieci casi di test li ha scritti l'orchestratore: quelli dell'intervistatore nello screenshot non si vedono.

---

Sei uno di quattro consulenti indipendenti (gli altri sono modelli diversi) a cui chiedo un parere di design. Non coordinarti con nessuno, non avviare altre chat né sub-agenti, non scrivere né modificare file: la risposta va tutta nel tuo messaggio finale. Mi serve il TUO parere, non una riformulazione del mio: se pensi che la baseline qui sotto sia sbagliata o ingenua, dillo.

## Contesto

Un candidato ha fatto un colloquio tecnico per una piattaforma di workflow agentici. Gli hanno mostrato una lavagna Excalidraw intitolata:

«Concurrent workflow editing · test cases — Each group starts from the example workflow (same version). Actions in a group are concurrent.»

Deve tornare a breve dall'intervistatore con la sua risposta migliore. Lo screenshot della lavagna è in `work/grafo-colloquio.png`: guardalo se puoi leggere immagini. Sotto c'è comunque la trascrizione completa, quindi non è indispensabile.

### Workflow di esempio (a sinistra: quello «giusto», la versione di partenza)

- n1 · Trigger · «New support ticket» · source: zendesk
- n2 · LLM step · «Classify (LLM)» · model: gpt-4.1 · fields: urgency, topic
- n3 · Branch · «Urgent?»
- n4 · Human · «Human approval» · required: true
- n5 · LLM step · «Draft reply (LLM)» · tone: angry
- n6 · Output · «Send» · channel: slack
- Archi: e1 n1→n2 · e2 n2→n3 · e3 n3→n4 (yes) · e4 n3→n5 (no) · e5 n4→n6 · e6 n5→n6

### Riquadro «WORKFLOW» (a destra): lo stato dopo modifiche concorrenti

Restano n1, n2, n4, n6 e gli archi e1, e2, e3 (yes), e5. Sono spariti n3, n5, e4, e6. e2 parte da n2 e finisce nel vuoto; e3 «yes» parte dal punto in cui stava n3 e arriva a n4. Cioè: ogni modifica presa da sola era plausibile, il risultato unito è un grafo rotto (archi orfani, un'etichetta di ramo senza più il branch).

### Appunti a mano sulla lavagna (il punto di partenza del tool)

```
{ { nome, versione, posizione, direzione, tipo, parti variabili } }

read_spec()

edit({ spec })
```

Cioè due tool: lettura dell'intera spec e scrittura dell'intera spec.

### La domanda dell'intervistatore

Due o più agenti LLM partono dalla stessa versione e vogliono modificare lo stesso workflow in parallelo, e poi renderlo effettivo (deploy). Come disegni il tool, o i tipi di tool, con cui gli agenti modificano il workflow, in modo che non si sovrascrivano e che in produzione vada solo qualcosa di valido? L'intervistatore è sceso su quattro punti: lo schema del workflow (JSON Schema), lo schema del tool, quando l'agente lo chiama, quando e come lo si testa. Il titolo della lavagna dice che l'esercizio è guidato dai casi di test: gruppi di azioni concorrenti che partono dalla stessa versione.

### Cosa ha già detto il candidato (baseline da superare, non da ripetere)

- Lato interfaccia: presenza in tempo reale stile Liveblocks (cursori, avviso «un altro agente sta modificando questo workflow dalla revisione 12»), più avvisi e conferme.
- Workflow come grafo versionato in JSON: `revision`, `entry`, `nodes` (ID stabili, `toolRef` versionato), `edges` (`from`, `to`, `on`). JSON Schema per la forma, controlli lato backend per riferimenti e compatibilità.
- Edit: il tool riceve la revisione di partenza e le operazioni sul grafo. Le modifiche che «non si toccano» si uniscono e poi si valida; se toccano lo stesso parametro o una rompe una dipendenza dell'altra, conflitto.
- Una bozza per agente; ciascuno prova la propria bozza indicando la revisione esatta.
- Deploy: compare-and-swap sulla revisione live («attiva X solo se la live è ancora la 12»); le revisioni validate sono immutabili.
- Se vogliono due cose diverse in produzione: «crea un nuovo workflow da questa bozza».

## Cosa ti chiedo

Il design che difenderesti tu davanti a un intervistatore senior, abbastanza concreto da poter essere implementato. Rispondi con queste sezioni, in quest'ordine:

1. **Tesi** (massimo 5 righe): l'idea portante e perché è quella giusta.

2. **Superficie dei tool**: il minor numero di tool che regge. Per ciascuno: nome, quando l'agente lo chiama, input (JSON Schema compatto o tipo TypeScript), risultato di successo, risultati di errore. Gli errori contano: li legge un LLM che deve capire cosa fare dopo senza un umano.

3. **Semantica di concorrenza**: definisci con precisione «si toccano». Cosa viene confrontato (revisione globale, versione per entità, read set, precondizioni, altro), dove avviene la serializzazione, cosa viene garantito e cosa no.

4. **Casi di test**: per ciascuno, esito per A, esito per B, stato finale. Tutti partono dalla revisione 12 del workflow di esempio.
   - T1 Nodi diversi: A imposta n5.tone = "friendly"; B imposta n6.channel = "email".
   - T2 Stesso campo: A imposta n2.model = "model-x"; B imposta n2.model = "model-y".
   - T3 Stesso nodo, campi diversi: A cambia n2.model; B aggiunge "sentiment" a n2.fields.
   - T4 Modifica contro cancellazione: A cancella n5 (con e4 ed e6); B imposta n5.tone = "friendly".
   - T5 Il caso del riquadro di destra: A elimina il ramo «no» (cancella n5, e4, e6); B elimina il branch n3 per mandare tutto in approvazione umana. Come si evita lo stato rotto, e cosa vede ciascuno?
   - T6 Dipendenza semantica senza sovrapposizione: A toglie "urgency" da n2.fields; B modifica la condizione di n3 (che legge urgency) o aggiunge un nodo che la usa.
   - T7 Inserimenti concorrenti nello stesso punto: A inserisce «Translate» tra n2 e n3; B inserisce «Redact PII» tra n2 e n3. Entrambi riscrivono e2.
   - T8 Corsa al deploy: A e B hanno ciascuno una revisione validata derivata dalla 12 e chiamano deploy nello stesso istante. Che succede ai run già in corso sulla 12?
   - T9 Agente inaffidabile: A ripete la stessa chiamata dopo un timeout (la prima era andata a buon fine); oppure A apre una bozza o prende un lock e muore.
   - T10 Intenti divergenti: A e B vogliono entrambi la propria variante in produzione.

5. **Ciclo di vita**: bozza → validazione → test run → deploy → run in corso → rollback. Cosa è immutabile e cosa è un puntatore. Quando l'agente chiama quale tool. Come testeresti il tool stesso (proprietà o invarianti da verificare sotto concorrenza).

6. **Dove si rompe** il tuo design e quanto costa. Poi la **migliore alternativa di una famiglia diversa** che hai scartato (per esempio: scrittura dell'intera spec con CAS, CRDT o live storage, lock o lease pessimistici, branch per agente con merge, coda a scrittore unico) e la condizione precisa in cui vincerebbe lei.

7. **Critica alla baseline**: cosa è sbagliato, vago o mancante. Dove sta il posto giusto di Liveblocks o di un CRDT in questo problema, e dove no.

8. **Risposta parlata**: 60–90 secondi in italiano, che il candidato può dire così com'è.

## Vincoli

- Scrivi in italiano; i termini tecnici in inglese vanno bene.
- Massimo circa 1400 parole, schemi esclusi. Niente preamboli e niente riassunto finale.
- Dove non sei sicuro, dillo in chiaro invece di riempire.
- Non serve cercare sul web, salvo per verificare un fatto specifico su cui poggia un tuo argomento.
