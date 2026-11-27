# Lato interfaccia: Liveblocks e WebMCP

`risposta-colloquio.md` mette la correttezza nel commit lato server. Questa pagina dice cosa resta all'interfaccia e con cosa la costruirei.

È uno schizzo di design. Niente di ciò che c'è qui è stato implementato o provato dal prototipo. I nomi delle API sono stati controllati sulle documentazioni ufficiali il 27 novembre 2026; le fonti sono in fondo.

## Il principio

L'interfaccia serve a due cose: rendere rari i conflitti, perché ognuno vede dove stanno lavorando gli altri, e rendere leggibili quelli che capitano. Non decide cosa viene salvato. Una modifica fatta dal canvas passa dallo stesso `edit` che usano gli agenti e riceve gli stessi esiti.

## Cosa farei con Liveblocks

Una stanza per workflow.

| Bisogno | Con cosa | Nota |
|---|---|---|
| Vedere chi c'è e su quale nodo lavora | Presence e il componente `Cursors` | Le API di presenza permettono di mostrare un cursore anche per un agente |
| Posizione dei box | Storage | Qui «vince l'ultima modifica» è la regola giusta |
| Bozza condivisa sul canvas, prima di salvare | `useLiveblocksFlow` di `@liveblocks/react-flow`, che tiene nodi e archi in Storage | Più persone danno forma alla stessa bozza |
| Discutere un conflitto | Thread di commenti fissati sul canvas | |
| Aggiornare tutti dopo un commit | Il server aggiorna la stanza con `mutateFlow`, l'API lato server dello stesso pacchetto | Chi ha il canvas aperto vede la nuova revisione senza ricaricare |

Di `mutateFlow` ho verificato che esiste e a cosa serve, non l'elenco completo dei suoi metodi.

## Cosa Liveblocks non fa

La regola documentata per Storage è: vince l'ultima modifica arrivata al server, chiave per chiave. I conflitti si risolvono per chiave, non per struttura. Ne seguono due cose.

- **Stesso campo.** Uno dei due valori sparisce. È una risoluzione automatica: chi ha perso non riceve un errore.
- **Chiavi diverse.** Entrambe le modifiche restano, anche quando insieme rompono il grafo. Se uno toglie n5 con i suoi archi e l'altro toglie n3, il risultato è il riquadro di destra della lavagna.

Per una bozza è il comportamento giusto: mentre si disegna si passa per forza da stati incompleti. Per questo la bozza nel canvas non è una revisione. Lo diventa solo passando da `edit`.

## Il ponte tra canvas e commit

«Salva» calcola le operazioni che separano la bozza dalla revisione da cui era partita e le manda come un solo `edit`, con quella revisione come base. Gli esiti sono gli stessi degli agenti, mostrati a una persona.

| Esito | Cosa mostra l'interfaccia |
|---|---|
| `INVALID_EDIT` | Evidenzia archi orfani e uscite scoperte. «Salva» resta bloccato finché la bozza non è completa |
| `CONFLICT` | Evidenzia i nodi contesi e dice chi li ha cambiati, in quale revisione e con quale intento. Le scelte: tenere la loro, riapplicare la mia sulla nuova revisione, aprire un thread |
| `MERGE_INVALID` | Mostra insieme le due modifiche che non stanno in piedi |
| `LIVE_MOVED`, al deploy | Mostra cosa è entrato in produzione nel frattempo |
| `ESCALATE` | Ferma i due contendenti e chiede al proprietario del workflow |

Avvisi e conferme restano, per le persone:

- un avviso quando la revisione cambia sotto la bozza;
- una conferma al deploy, con il diff tra la produzione e ciò che si pubblica e gli autori di ogni modifica;
- un avviso su «crea una variante»: due workflow con lo stesso trigger rispondono due volte allo stesso ticket.

Per un agente la conferma non è un controllo, perché un LLM conferma qualsiasi cosa. Il suo equivalente è l'errore strutturato.

## Cosa farei con WebMCP

WebMCP è l'API con cui una pagina web registra dei tool che un agente nel browser può chiamare. In Chrome si usa `document.modelContext.registerTool`, con nome, descrizione, schema di input e una funzione `execute`.

Qui serve a una cosa: l'editor espone all'agente del browser gli stessi quattro tool, con lo stesso schema, invece di farlo cliccare sul canvas.

```js
await document.modelContext.registerTool({
  name: "edit",
  description: "Applica al workflow un batch atomico di operazioni: o tutte o nessuna.",
  inputSchema: EDIT_INPUT_SCHEMA, // lo stesso schema di risposta-colloquio.md
  annotations: { untrustedContentHint: true },
  async execute(input, signal) {
    const res = await fetch(`/api/workflows/${input.workflow_id}/edit`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
      signal,
    });
    return JSON.stringify(await res.json()); // OK, CONFLICT, INVALID_EDIT: come per ogni altro chiamante
  },
});
```

Le annotazioni che userei:

| Tool | Annotazione | Perché |
|---|---|---|
| `read_spec` | `readOnlyHint`, `untrustedContentHint` | Legge soltanto, e ciò che restituisce contiene testo scritto da altri |
| `edit` | `untrustedContentHint` | Un errore di conflitto riporta l'intento scritto da un altro agente |
| `test` | nessuna | |
| `deploy` | `consequentialHint` | Cambia la produzione: browser e agente possono imporre una conferma dell'utente |

Tre conseguenze.

- **Un contratto, tre porte.** Il pulsante del canvas, l'agente lato server e l'agente nel browser chiamano gli stessi tool. Il server applica a tutti gli stessi controlli.
- **L'agente nel browser lavora dentro la sessione di chi è davanti allo schermo.** `execute` è codice della pagina e chiama il backend come lo chiama l'interfaccia. Con la presenza di Liveblocks, la persona vede sul canvas ciò che l'agente sta facendo.
- **L'intento di un altro agente è testo scritto da altri.** Va trattato come dato, non come istruzione. Vale per tutte e tre le porte.

Il limite: Chrome indica WebMCP come origin trial e avverte che è in discussione e può cambiare. È quindi una porta in più, mai l'unica.

## Fonti

- Liveblocks, «How conflict resolution works in Liveblocks Sync»: https://liveblocks.io/docs/guides/how-conflict-resolution-works-in-liveblocks-sync
- Liveblocks, «Multiplayer SDK for React Flow»: https://liveblocks.io/blog/multiplayer-sdk-for-react-flow-realtime-collaboration-between-humans-and-agents
- Chrome for Developers, «WebMCP Imperative API», aggiornata il 26 novembre 2026: https://developer.chrome.com/docs/ai/webmcp/imperative-api
