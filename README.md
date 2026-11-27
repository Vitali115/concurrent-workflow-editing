# Editing concorrente di un workflow tra agenti

Risposta a un esercizio di colloquio. Due o più agenti LLM partono dalla stessa revisione di un workflow, lo modificano in parallelo e poi lo vogliono in produzione. Come si disegna il tool con cui lo modificano, perché non si sovrascrivano e perché in produzione vada solo qualcosa di valido?

## La risposta in breve

- Il tool non riscrive la spec intera. Manda un batch atomico di operazioni sul grafo, riferito alla revisione che l'agente ha letto.
- Il server è l'unico punto di commit. Rifiuta il batch se collide con ciò che è arrivato nel frattempo. Altrimenti lo riapplica sull'ultima revisione e salva solo se l'intero grafo è valido.
- Le revisioni sono immutabili. La produzione è un puntatore che si sposta con un compare-and-swap, solo in avanti e solo su una revisione testata.
- L'interfaccia rende i conflitti rari e leggibili. La correttezza sta nel commit.

## Cosa c'è qui

| File | Contenuto |
|---|---|
| [`risposta-colloquio.md`](risposta-colloquio.md) | La risposta: schema del workflow, i quattro tool, quando due modifiche si toccano, i casi di test, la versione parlata |
| [`interfaccia-liveblocks-webmcp.md`](interfaccia-liveblocks-webmcp.md) | Il lato interfaccia: cosa farei con Liveblocks e con WebMCP |
| [`prototipo.py`](prototipo.py) | Il meccanismo, eseguibile, con i casi di test |
| [`chi-ha-lavorato.md`](chi-ha-lavorato.md) | Chi ha fatto cosa: i modelli usati, l'effort, i disaccordi e come sono stati chiusi |
| [`consiglio/`](consiglio/) | Il brief dato a sei consulenti e le loro risposte integrali |
| [`verifiche/`](verifiche/) | Gli script che controllano il prototipo e gli schemi |

## Rieseguire

Serve Python 3.9 o successivo. Il prototipo non ha dipendenze.

```sh
python3 prototipo.py                      # i casi di test, nei due ordini di arrivo
python3 verifiche/prova_mutazioni.py      # rompe una regola alla volta: i test devono accorgersene
pip install -r verifiche/requirements.txt
python3 verifiche/controlla_schemi.py     # gli schemi JSON della risposta contro il prototipo
```

## Limiti dichiarati

- Il prototipo esegue gli arrivi in sequenza e modella il punto di commit come già serializzato. Non usa thread né un database: la concorrenza vera non è verificata.
- I casi di test non sono quelli dell'intervistatore, che non conosco: li ha scritti l'orchestratore descritto in `chi-ha-lavorato.md`.
- Il lato interfaccia è uno schizzo di design, non implementato.
- Lo screenshot della lavagna non è incluso, perché è materiale dell'intervistatore. Il workflow è trascritto in `risposta-colloquio.md`.
