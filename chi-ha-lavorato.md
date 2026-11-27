# Chi ha lavorato a questa risposta

Questa risposta non l'ho scritta da solo. Qui c'è chi ha fatto cosa, con quali modelli e a quale effort, e come siamo arrivati al risultato.

## In breve

- **Io** ho fatto il colloquio, ho dato la prima risposta e ho deciso la direzione del lavoro.
- **Un assistente vocale** mi ha aiutato a riordinare quella prima risposta.
- **Un orchestratore** ha scritto il brief, ha convocato il consiglio, ha costruito il prototipo, ha fatto le verifiche e ha scritto i testi di questa repo.
- **Sei consulenti**, su quattro modelli diversi, hanno risposto allo stesso brief senza vedersi tra loro.
- **Un agente** ha pubblicato la repo.

I testi di questa repo li ha scritti l'orchestratore, tranne le risposte in `consiglio/risposte/`, che sono quelle dei modelli, parola per parola.

## Chi e cosa

| Ruolo | Modello | Effort | Durata | Costo | Cosa ha fatto |
|---|---|---|---|---|---|
| Assistente vocale | GPT-6.2 Sol | non noto | circa 10 minuti | non noto | Ha discusso con me la prima risposta. Non ha mai visto la lavagna |
| Orchestratore | Claude Fable 5.2 | xhigh | tutta la sessione | non noto | Brief, consiglio, prototipo, verifiche, sintesi, testi |
| Consulente 1 | GPT-6.2 Astra | predefinito | 2 min 37 s | 0,30 $ | Parere indipendente |
| Consulente 2 | Claude Opus 5.5 | predefinito | 2 min 43 s | 0,53 $ | Parere indipendente |
| Consulente 3 | Gemini 4 Neon | predefinito | 3 min 44 s | non noto | Parere indipendente |
| Consulente 4 | GPT-6.2 Sol | max | 11 min 48 s | 0,08 $ | Parere indipendente |
| Consulente 5 | Claude Fable 5.2 | predefinito | 2 min 37 s | 1,07 $ | Parere indipendente, senza conoscere la posizione dell'orchestratore |
| Consulente 6 | GPT-6.2 Astra | max | 8 min 44 s | 0,76 $ | Parere indipendente |
| Lettura delle documentazioni | sotto-agenti dell'orchestratore | non noto | meno di un minuto | non noto | Tre pagine ufficiali su Liveblocks e WebMCP |
| Pubblicazione | Claude Opus 5.5 | predefinito | 36 s | non noto | Ha creato la repo e caricato i file. Questa riga l'ha completata dopo l'orchestratore, con un secondo commit |

Durate e costi sono quelli riportati dall'app con cui ho avviato le chat. I sei consulenti sono costati in tutto 2,74 dollari, più Gemini.

## Cosa ho fatto io

- Ho sostenuto il colloquio. Lì ho risposto che lato interfaccia avrei usato Liveblocks, con i cursori degli altri e degli avvisi, e poi siamo scesi sul tool: il suo schema, quando lo si chiama, quando lo si testa.
- Con l'assistente vocale sono arrivato a una risposta più ordinata: grafo versionato, operazioni riferite a una revisione, una bozza per agente, compare-and-swap al deploy.
- Ho chiesto un consiglio di modelli diversi e ho scelto quali.
- Ho chiesto un secondo parere di Fable, indipendente, e il giudizio finale dell'orchestratore.
- Ho chiesto la pagina sul lato interfaccia, con Liveblocks e WebMCP.
- Ho chiesto di pubblicare tutto, compresa questa pagina.

## Come siamo arrivati alla risposta

1. **La lavagna.** L'assistente vocale non era riuscito a vederla e aveva lavorato su un grafo d'esempio inventato. L'orchestratore ha recuperato lo screenshot e ha notato due cose: il workflow vero, e il riquadro di destra, che mostra il grafo rotto dopo due modifiche concorrenti.
2. **Una posizione prima del consiglio.** L'orchestratore ha scritto la sua tesi prima di leggere le risposte, per non farsi trascinare.
3. **Lo stesso brief a tutti.** Il testo è in `consiglio/brief.md`. Contiene la lavagna trascritta, la mia risposta di partenza come base da superare, e dieci casi di test. I casi li ha scritti l'orchestratore: quelli dell'intervistatore nello screenshot non si vedono.
4. **Il disaccordo.** I consulenti non concordavano su dove integrare le modifiche, né sull'esito del caso del riquadro di destra.
5. **Il prototipo.** Invece di scegliere una tabella scritta a mano, l'orchestratore ha fissato le regole in `prototipo.py` e ha fatto girare i casi nei due ordini di arrivo.
6. **Le verifiche al contrario.** Ha rotto apposta una regola alla volta per controllare che i test se ne accorgessero. Lo script è `verifiche/prova_mutazioni.py`.
7. **Gli ultimi due pareri.** Astra a effort max e il Fable indipendente sono arrivati dopo. Hanno portato il rollback come commit, i permessi separati e un caso di test più semplice, e il prototipo è stato aggiornato.
8. **Il lato interfaccia.** Scritto per ultimo, dopo aver letto le documentazioni di Liveblocks e di WebMCP.

## Dove i consulenti non erano d'accordo

| Questione | Posizioni | Come è stata chiusa |
|---|---|---|
| Dove si integrano le modifiche | Linea condivisa: Opus, Sol, Fable. Un candidato per agente: Astra (a entrambi gli effort), Gemini | Non a maggioranza. L'orchestratore ha scelto la linea condivisa perché l'esercizio della lavagna è un solo workflow che riceve azioni concorrenti. L'altra resta come variante, con lo stesso meccanismo |
| Esito del caso del riquadro di destra | Per Opus il secondo arrivato passa. Per gli altri va in conflitto | Dal prototipo: va in conflitto. L'esito di Opus non regge con le sue stesse regole: dopo la modifica del primo, il branch ha un arco che il secondo non ha mai visto |
| Togliere un nodo cancella i suoi archi? | A cascata: Fable. Espliciti: gli altri, con Opus che lascia la scelta a chi chiama | Espliciti: chi toglie un nodo dice dove vanno i collegamenti |
| Rollback | Spostare indietro il puntatore: tutti gli altri, e la prima versione dell'orchestratore. Un nuovo commit: Astra max | Un nuovo commit. Il difetto dell'altra strada l'ha trovato il Fable ed è stato riprodotto nel prototipo |
| Confronto sul valore o sulla cronologia | Sul valore: Opus, Astra max. Sulla cronologia: Astra, Sol | Sulla cronologia: un valore cambiato e poi rimesso com'era resta una modifica |

## Cosa ha portato ciascuno

| Consulente | Adottato | Non adottato, o da correggere |
|---|---|---|
| Astra | Due test verdi su bozze separate non provano niente sul grafo unito. L'intento va mandato intero | Il candidato per agente come linea principale |
| Opus 5.5 | Deploy solo in avanti. Il fork duplica il trigger. Le dipendenze di dati dichiarate in `inputs` | Le scritture identiche trattate come nulla di fatto. Il suo esito sul riquadro di destra |
| Gemini 4 Neon | Posizione e direzione fuori dalla spec. La coda a scrittore unico sotto forte contesa | Un tool separato per il riallineamento. Il suo deploy non controlla che la revisione discenda dalla live |
| Sol max | Le uscite dei nodi come chiavi di conflitto. Lo stop esplicito di un ramo. Validità di struttura e prova di comportamento come due cose distinte | Il contatore di attivazioni: adottato, poi reso inutile dal rollback come commit |
| Fable indipendente | La conferma non è un controllo per un LLM. Il rollback che riporta online la modifica ritirata. `ESCALATE`. La finezza del conflitto come politica del server | La cancellazione a cascata degli archi |
| Astra max | Il rollback come commit. I permessi separati tra chi modifica e chi pubblica. Un caso T6 più semplice | Conservare l'intento sul server e comporre più intenti in una release: descritto, solo per la variante con un candidato per agente |

## Errori e correzioni

- **L'assistente vocale ha lavorato senza la lavagna.** La risposta di partenza era costruita su un grafo inventato.
- **Un consulente in più, per un malinteso.** Avevo dettato «Astra a max». L'orchestratore ha capito «Sol max» e ha lanciato GPT-6.2 Sol. Quando l'ho corretto è partito anche Astra max. Il parere di Sol è stato tenuto.
- **La prima versione della risposta era meno pulita.** Aveva un contatore di attivazioni e un rollback che spostava indietro il puntatore. Sono stati tolti dopo gli ultimi due pareri.
- **I controlli sono passati al primo colpo,** e questo da solo non provava niente. Per questo sono stati provati al contrario.

## Cosa è verificato e cosa è giudizio

**Verificato eseguendo:** gli esiti dei casi T1–T9 nei due ordini, il rollback, 2.366 gruppi di due e tre agenti con quattro invarianti, sei regole rotte apposta e tutte rilevate, la validità dei due JSON Schema e la loro coerenza con il prototipo, il fatto che il grafo rotto della lavagna rispetta lo schema.

**Controllato sulle documentazioni:** le regole di risoluzione dei conflitti di Liveblocks, il pacchetto per React Flow, l'API di WebMCP in Chrome e il suo stato.

**Giudizio, non prova:** la scelta della linea condivisa rispetto al candidato per agente, gli archi espliciti rispetto alla cascata, tutto il design del lato interfaccia.

**Non verificato:** la concorrenza vera, perché il prototipo esegue gli arrivi in sequenza, senza thread né database. I casi di test dell'intervistatore, che non conosco.
