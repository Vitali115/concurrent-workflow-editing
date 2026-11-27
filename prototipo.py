#!/usr/bin/env python3
"""Editing concorrente di un workflow: prototipo eseguibile.

Modello
  - revisioni immutabili su una linea condivisa (head);
  - l'agente manda un batch atomico di operazioni riferito a una revisione di partenza;
  - il server rifiuta il batch se collide con i commit arrivati dopo quella revisione,
    altrimenti lo riapplica sulla head e valida l'intero grafo prima di salvare;
  - il deploy sposta il puntatore live con un compare-and-swap, solo in avanti;
  - il rollback e' un commit come gli altri: ripristina il contenuto di una revisione
    gia' pubblicata, quindi head e live non divergono mai.

"Concorrenti" qui vuol dire: entrambi gli agenti hanno letto la revisione 12.
Il punto di commit e' serializzato, quindi ogni gruppo si riduce agli ordini di arrivo.

Uso
  python3 prototipo.py          esegue T1-T9 nei due ordini e la verifica esaustiva
  python3 prototipo.py --json   stampa il workflow di esempio
"""
import copy
import itertools
import json
import sys

END = "END"

# Il workflow della lavagna (a sinistra), revisione 12.
BASE = {
    "entry": "n1",
    "nodes": {
        "n1": {"type": "trigger", "name": "New support ticket", "config": {"source": "zendesk"}},
        "n2": {"type": "llm", "name": "Classify",
               "config": {"model": "gpt-4.1", "fields": ["urgency", "topic"]}},
        "n3": {"type": "branch", "name": "Urgent?",
               "inputs": {"value": {"node": "n2", "field": "urgency"}}},
        "n4": {"type": "human", "name": "Human approval", "config": {"required": True}},
        "n5": {"type": "llm", "name": "Draft reply", "config": {"tone": "angry"}},
        "n6": {"type": "output", "name": "Send", "config": {"channel": "slack"}},
    },
    "edges": {
        "e1": {"from": "n1", "to": "n2", "on": "next"},
        "e2": {"from": "n2", "to": "n3", "on": "next"},
        "e3": {"from": "n3", "to": "n4", "on": "yes"},
        "e4": {"from": "n3", "to": "n5", "on": "no"},
        "e5": {"from": "n4", "to": "n6", "on": "next"},
        "e6": {"from": "n5", "to": "n6", "on": "next"},
    },
}


# --------------------------------------------------------------------------
# Validazione dell'intero grafo: e' il cancello di ogni commit.
# --------------------------------------------------------------------------

def outlets(node_type):
    return {"branch": ("yes", "no"), "output": ()}.get(node_type, ("next",))


def validate(spec):
    """Restituisce la lista delle violazioni; lista vuota = grafo valido."""
    nodes, edges, out = spec["nodes"], spec["edges"], []
    entry = spec["entry"]
    if entry not in nodes or nodes[entry]["type"] != "trigger":
        out.append(("BAD_ENTRY", entry, "entry deve essere un nodo trigger esistente"))

    ports = {}
    for eid, e in sorted(edges.items()):
        if e["from"] not in nodes:
            out.append(("DANGLING_EDGE", eid, "%s parte da %s, che non esiste" % (eid, e["from"])))
        else:
            if e["on"] not in outlets(nodes[e["from"]]["type"]):
                out.append(("BAD_PORT", eid, "%s non ha un'uscita '%s'" % (e["from"], e["on"])))
            if (e["from"], e["on"]) in ports:
                out.append(("DUPLICATE_PORT", eid, "l'uscita %s.%s ha gia' l'arco %s"
                            % (e["from"], e["on"], ports[(e["from"], e["on"])])))
            ports[(e["from"], e["on"])] = eid
        if e["to"] != END and e["to"] not in nodes:
            out.append(("DANGLING_EDGE", eid, "%s arriva a %s, che non esiste" % (eid, e["to"])))

    for nid, n in sorted(nodes.items()):
        for port in outlets(n["type"]):
            if (nid, port) not in ports:
                out.append(("MISSING_OUTLET", nid, "l'uscita %s.%s non va da nessuna parte" % (nid, port)))

    succ = dict((nid, []) for nid in nodes)
    for e in edges.values():
        if e["from"] in nodes and e["to"] in nodes:
            succ[e["from"]].append(e["to"])

    def reach(skip=None):
        seen, stack = set(), [entry] if entry in nodes and entry != skip else []
        while stack:
            cur = stack.pop()
            if cur in seen or cur == skip:
                continue
            seen.add(cur)
            stack.extend(succ[cur])
        return seen

    reachable = reach()
    for nid in sorted(nodes):
        if nid not in reachable:
            out.append(("UNREACHABLE_NODE", nid, "%s non e' raggiungibile da %s" % (nid, entry)))

    color = {}

    def has_cycle(nid):
        color[nid] = 1
        for nxt in succ[nid]:
            if color.get(nxt) == 1 or (nxt not in color and has_cycle(nxt)):
                return True
        color[nid] = 2
        return False

    if any(nid not in color and has_cycle(nid) for nid in sorted(nodes)):
        out.append(("CYCLE", "-", "il grafo contiene un ciclo"))

    # Dataflow: ogni campo letto deve esistere ed essere prodotto a monte su ogni percorso.
    for nid, n in sorted(nodes.items()):
        for name, ref in sorted(n.get("inputs", {}).items()):
            src = nodes.get(ref["node"])
            label = "%s.inputs.%s legge %s.%s" % (nid, name, ref["node"], ref["field"])
            if src is None or ref["field"] not in src.get("config", {}).get("fields", []):
                out.append(("MISSING_INPUT", nid, label + ", che non esiste"))
            elif ref["node"] == nid or (nid in reachable and nid in reach(skip=ref["node"])):
                out.append(("INPUT_NOT_UPSTREAM", nid, label + ", che non e' a monte su ogni percorso"))
    return out


# --------------------------------------------------------------------------
# Operazioni: ognuna dichiara cosa scrive (W) e cosa da' per letto (R).
# --------------------------------------------------------------------------

class BadOp(Exception):
    pass


def apply_ops(spec, ops, track_refs=True, released=None):
    """Applica il batch a una copia. Restituisce (nuova_spec, W, R).

    released: le revisioni gia' state in produzione, le sole che restore puo' ripristinare.
    """
    s, W, R = copy.deepcopy(spec), set(), set()

    def node(i, nid):
        if nid not in s["nodes"]:
            raise BadOp("op %d: il nodo %s non esiste" % (i, nid))
        return s["nodes"][nid]

    def edge(i, eid):
        if eid not in s["edges"]:
            raise BadOp("op %d: l'arco %s non esiste" % (i, eid))
        return s["edges"][eid]

    def exists(nid):
        if nid != END:
            R.add("nodes/%s/@" % nid)

    def reads(ref):
        if track_refs:
            R.add("nodes/%s/config/fields/%s" % (ref["node"], ref["field"]))

    for i, op in enumerate(ops):
        kind = op["op"]
        if kind == "set":
            n = node(i, op["node"])
            exists(op["node"])
            W.add("nodes/%s/config/%s" % (op["node"], op["key"]))
            n.setdefault("config", {})[op["key"]] = op["value"]
        elif kind in ("add_item", "remove_item"):
            n = node(i, op["node"])
            exists(op["node"])
            W.add("nodes/%s/config/%s/%s" % (op["node"], op["key"], op["item"]))
            items = n.setdefault("config", {}).setdefault(op["key"], [])
            if kind == "add_item" and op["item"] not in items:
                items.append(op["item"])
            if kind == "remove_item" and op["item"] in items:
                items.remove(op["item"])
        elif kind == "set_input":
            n = node(i, op["node"])
            exists(op["node"])
            W.add("nodes/%s/inputs/%s" % (op["node"], op["name"]))
            reads(op["ref"])
            n.setdefault("inputs", {})[op["name"]] = dict(op["ref"])
        elif kind == "add_node":
            if op["id"] in s["nodes"]:
                raise BadOp("op %d: il nodo %s esiste gia'" % (i, op["id"]))
            W.add("nodes/%s" % op["id"])
            s["nodes"][op["id"]] = copy.deepcopy(op["node"])
            for ref in op["node"].get("inputs", {}).values():
                reads(ref)
        elif kind == "remove_node":      # nessuna cancellazione a cascata degli archi
            node(i, op["id"])
            W.add("nodes/%s" % op["id"])
            del s["nodes"][op["id"]]
        elif kind == "add_edge":
            if op["id"] in s["edges"]:
                raise BadOp("op %d: l'arco %s esiste gia'" % (i, op["id"]))
            e = dict(op["edge"])
            e.setdefault("on", "next")
            W.update(["edges/%s" % op["id"], "ports/%s/%s" % (e["from"], e["on"])])
            exists(e["from"])
            exists(e["to"])
            s["edges"][op["id"]] = e
        elif kind == "set_edge":
            e = edge(i, op["id"])
            W.update(["edges/%s" % op["id"], "ports/%s/%s" % (e["from"], e["on"])])
            for k in ("from", "to", "on"):
                if k in op:
                    e[k] = op[k]
            W.add("ports/%s/%s" % (e["from"], e["on"]))
            exists(e["from"])
            exists(e["to"])
        elif kind == "remove_edge":
            e = edge(i, op["id"])
            W.update(["edges/%s" % op["id"], "ports/%s/%s" % (e["from"], e["on"])])
            del s["edges"][op["id"]]
        elif kind == "restore":          # rollback: riscrive tutto, quindi collide con qualsiasi commit
            if not released or op["revision"] not in released:
                raise BadOp("op %d: la revisione %s non e' mai stata in produzione" % (i, op["revision"]))
            s = copy.deepcopy(released[op["revision"]])
            W.update(["entry", "nodes", "edges", "ports"])
        else:
            raise BadOp("op %d: operazione sconosciuta '%s'" % (i, kind))
    return s, W, R


def digest(spec):
    """Impronta del contenuto: due revisioni con lo stesso grafo hanno la stessa impronta."""
    return json.dumps(spec, sort_keys=True)


def related(a, b):
    """Due chiavi si toccano se sono uguali o una contiene l'altra."""
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


# --------------------------------------------------------------------------
# Il server: revisioni, puntatori, idempotenza.
# --------------------------------------------------------------------------

class Store:
    def __init__(self, spec, revision=12, track_refs=True):
        self.revs = {revision: copy.deepcopy(spec)}
        self.head = revision
        self.log = {}                      # revisione -> chi, intento, W, R
        self.live = revision
        self.was_live = set([revision])
        self.tests = {}
        self.idem = {}
        self.runs = {}
        self.track_refs = track_refs

    def read_spec(self, revision=None):
        revision = self.head if revision is None else revision
        return {"revision": revision, "head": self.head, "live": self.live,
                "spec": copy.deepcopy(self.revs[revision])}

    def _released(self):
        return dict((rev, self.revs[rev]) for rev in self.was_live)

    def edit(self, agent, base_revision, ops, request_id, intent=""):
        payload = json.dumps([base_revision, ops], sort_keys=True)
        if request_id in self.idem:
            old_payload, old_result = self.idem[request_id]
            if old_payload != payload:
                return {"ok": False, "error": "KEY_REUSED",
                        "next": "Stessa request_id con contenuto diverso: usa una nuova request_id."}
            return dict(old_result, replayed=True)
        result = self._edit(agent, base_revision, ops, intent)
        if result["ok"]:
            self.idem[request_id] = (payload, result)
        return result

    def _edit(self, agent, base, ops, intent):
        if base not in self.revs:
            return {"ok": False, "error": "REV_NOT_FOUND", "head": self.head,
                    "next": "Chiama read_spec e riparti dalla head."}
        # 1. Il batch deve stare in piedi da solo, sulla revisione che l'agente ha letto.
        try:
            candidate, W, R = apply_ops(self.revs[base], ops, self.track_refs, self._released())
        except BadOp as exc:
            return {"ok": False, "error": "INVALID_EDIT", "violations": [("BAD_OP", "-", str(exc))],
                    "next": "Correggi il batch e rimandalo. Niente e' stato applicato."}
        violations = validate(candidate)
        if violations:
            return {"ok": False, "error": "INVALID_EDIT", "violations": violations,
                    "next": "Il batch lascia il grafo invalido: completa l'intento nello stesso batch. "
                            "Niente e' stato applicato."}
        # 2. Collisione con i commit arrivati dopo la base.
        conflicts = []
        for rev in range(base + 1, self.head + 1):
            c = self.log[rev]
            hits = sorted(set(
                [mine for mine in W | R for theirs in c["W"] if related(mine, theirs)] +
                [mine for mine in W for theirs in c["R"] if related(mine, theirs)]))
            for key in hits:
                conflicts.append({"key": key, "changed_in": rev, "by": c["by"], "their_intent": c["intent"]})
        if conflicts:
            return {"ok": False, "error": "CONFLICT", "head": self.head, "conflicts": conflicts,
                    "next": "Niente e' stato applicato. Rileggi la revisione %d, decidi se il tuo intento "
                            "ha ancora senso e rimanda con base_revision %d." % (self.head, self.head)}
        # 3. Rebase sulla head e validazione dell'intero grafo risultante.
        rebased_over = list(range(base + 1, self.head + 1))
        if rebased_over:
            try:
                candidate, W, R = apply_ops(self.revs[self.head], ops, self.track_refs, self._released())
                violations = validate(candidate)
            except BadOp as exc:
                violations = [("BAD_OP", "-", str(exc))]
            if violations:
                return {"ok": False, "error": "MERGE_INVALID", "head": self.head,
                        "violations": violations, "rebased_over": rebased_over,
                        "next": "Da solo il tuo batch era valido, insieme alle revisioni %s no. "
                                "Rileggi la head e riformula." % rebased_over}
        # 4. Commit. In produzione: una transazione con compare-and-swap sulla head.
        self.head += 1
        self.revs[self.head] = candidate
        self.log[self.head] = {"by": agent, "intent": intent, "W": W, "R": R, "ops": ops, "base": base}
        return {"ok": True, "revision": self.head, "rebased_over": rebased_over}

    def test(self, revision):
        """Segnaposto: esegue i due percorsi (urgente / non urgente) sulla revisione esatta."""
        spec, passed = self.revs[revision], True
        for urgent in (True, False):
            cur, steps = spec["entry"], 0
            while cur != END and spec["nodes"][cur]["type"] != "output" and steps < 100:
                want = ("yes" if urgent else "no") if spec["nodes"][cur]["type"] == "branch" else "next"
                nxt = [e["to"] for e in spec["edges"].values() if e["from"] == cur and e["on"] == want]
                if not nxt:
                    passed = False
                    break
                cur, steps = nxt[0], steps + 1
        test_id = "test-%d" % (len(self.tests) + 1)
        self.tests[test_id] = {"revision": revision, "digest": digest(spec), "passed": passed}
        return {"test_id": test_id, "revision": revision, "passed": passed}

    def deploy(self, revision, expect_live, test_id=None):
        """Compare-and-swap sul puntatore live. Va solo in avanti."""
        if expect_live != self.live:
            return {"ok": False, "error": "LIVE_MOVED", "live": self.live,
                    "live_contains_your_revision": revision <= self.live,
                    "next": "La produzione e' cambiata. Se contiene gia' la tua revisione hai finito; "
                            "altrimenti riprova indicando la live attuale."}
        if revision <= self.live:
            return {"ok": False, "error": "NOT_FORWARD", "live": self.live,
                    "next": "Questa revisione non e' piu' avanti della live: pubblicarla annullerebbe "
                            "lavoro altrui. Per tornare indietro fai un edit con l'operazione restore."}
        t = self.tests.get(test_id)
        if not t or not t["passed"] or t["digest"] != digest(self.revs[revision]):
            return {"ok": False, "error": "TEST_REQUIRED",
                    "next": "Serve un test passato sul contenuto esatto della revisione %d." % revision}
        self.live = revision
        self.was_live.add(revision)
        return {"ok": True, "live": self.live}

    def start_run(self, run_id):
        self.runs[run_id] = self.live               # il run resta su questa revisione fino alla fine
        return self.runs[run_id]


# --------------------------------------------------------------------------
# I batch dei casi di test.
# --------------------------------------------------------------------------

def insert_after_n2(node_id, edge_id, name):
    return [{"op": "add_node", "id": node_id, "node": {"type": "llm", "name": name, "config": {}}},
            {"op": "set_edge", "id": "e2", "to": node_id},
            {"op": "add_edge", "id": edge_id, "edge": {"from": node_id, "to": "n3"}}]


REMOVE_NO_BRANCH = [                       # togli il ramo "no" e dichiara che finisce li'
    {"op": "remove_edge", "id": "e4"}, {"op": "remove_edge", "id": "e6"},
    {"op": "remove_node", "id": "n5"},
    {"op": "add_edge", "id": "e7", "edge": {"from": "n3", "to": END, "on": "no"}}]
REMOVE_BRANCH = [                          # togli il branch: tutto passa dall'approvazione umana
    {"op": "set_edge", "id": "e2", "to": "n4"},
    {"op": "remove_edge", "id": "e3"}, {"op": "remove_edge", "id": "e4"},
    {"op": "remove_edge", "id": "e6"},
    {"op": "remove_node", "id": "n5"}, {"op": "remove_node", "id": "n3"}]

CASES = [
    ("T1", "nodi diversi",
     [{"op": "set", "node": "n5", "key": "tone", "value": "friendly"}],
     [{"op": "set", "node": "n6", "key": "channel", "value": "email"}], ("OK", "OK")),
    ("T2", "stesso campo",
     [{"op": "set", "node": "n2", "key": "model", "value": "model-x"}],
     [{"op": "set", "node": "n2", "key": "model", "value": "model-y"}], ("OK", "CONFLICT")),
    ("T3", "stesso nodo, campi diversi",
     [{"op": "set", "node": "n2", "key": "model", "value": "model-x"}],
     [{"op": "add_item", "node": "n2", "key": "fields", "item": "sentiment"}], ("OK", "OK")),
    ("T4", "modifica contro cancellazione",
     REMOVE_NO_BRANCH,
     [{"op": "set", "node": "n5", "key": "tone", "value": "friendly"}], ("OK", "CONFLICT")),
    ("T5", "riquadro di destra, intenti completi",
     REMOVE_NO_BRANCH, REMOVE_BRANCH, ("OK", "CONFLICT")),
    ("T6", "dipendenza di dati senza sovrapposizione",      # topic non lo legge ancora nessuno
     [{"op": "remove_item", "node": "n2", "key": "fields", "item": "topic"}],
     [{"op": "add_node", "id": "n7", "node": {"type": "llm", "name": "Route by topic", "config": {},
                                              "inputs": {"t": {"node": "n2", "field": "topic"}}}},
      {"op": "set_edge", "id": "e5", "to": "n7"},
      {"op": "add_edge", "id": "e8", "edge": {"from": "n7", "to": "n6"}}], ("OK", "CONFLICT")),
    ("T7", "due inserimenti sullo stesso arco",
     insert_after_n2("nT", "eT", "Translate"),
     insert_after_n2("nR", "eR", "Redact PII"), ("OK", "CONFLICT")),
]


def code(result):
    return "OK->%d" % result["revision"] if result["ok"] else result["error"]


def topology(spec):
    parts = []
    for eid in sorted(spec["edges"]):
        e = spec["edges"][eid]
        parts.append("%s%s>%s" % (e["from"], "" if e["on"] == "next" else "-" + e["on"], e["to"]))
    return " ".join(parts)


def changes(spec):
    out = []
    for nid in sorted(spec["nodes"]):
        base_cfg = BASE["nodes"].get(nid, {}).get("config", {})
        for key, value in sorted(spec["nodes"][nid].get("config", {}).items()):
            if base_cfg.get(key) != value:
                out.append("%s.%s=%s" % (nid, key, json.dumps(value)))
    return ", ".join(out) or "-"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_pairs():
    print("== Casi a coppie: entrambi leggono la 12, poi arrivano in un ordine o nell'altro ==")
    for name, title, a_ops, b_ops, expected in CASES:
        print("\n%s  %s" % (name, title))
        for first, second, f_ops, s_ops in (("A", "B", a_ops, b_ops), ("B", "A", b_ops, a_ops)):
            st = Store(BASE)
            r1 = st.edit(first, 12, f_ops, name + first, "intento di " + first)
            r2 = st.edit(second, 12, s_ops, name + second, "intento di " + second)
            got = (r1["error"] if not r1["ok"] else "OK", r2["error"] if not r2["ok"] else "OK")
            check(got == expected, "%s (%s prima): atteso %s, ottenuto %s" % (name, first, expected, got))
            check(all(validate(s) == [] for s in st.revs.values()), name + ": revisione invalida salvata")
            print("  %s prima: %s %-8s %s %-9s | head %d | %s | %s" % (
                first, first, code(r1), second, code(r2), st.head,
                topology(st.revs[st.head]), changes(st.revs[st.head])))
            if not r2["ok"]:
                keys = sorted(set(c["key"] for c in r2.get("conflicts", [])))
                print("           %s vede: %s" % (second, ", ".join(keys)))


def run_right_frame():
    print("\n== Il riquadro di destra ==")
    partial_a = [{"op": "remove_edge", "id": "e4"}, {"op": "remove_edge", "id": "e6"},
                 {"op": "remove_node", "id": "n5"}]
    partial_b = [{"op": "remove_node", "id": "n3"}]
    merged = apply_ops(apply_ops(BASE, partial_a)[0], partial_b)[0]
    check(sorted(merged["nodes"]) == ["n1", "n2", "n4", "n6"], "nodi diversi dalla lavagna")
    check(sorted(merged["edges"]) == ["e1", "e2", "e3", "e5"], "archi diversi dalla lavagna")
    print("  unione senza controllo: nodi %s, archi %s" % (sorted(merged["nodes"]), sorted(merged["edges"])))
    for violation in validate(merged):
        print("    %s: %s" % (violation[0], violation[2]))
    st = Store(BASE)
    ra = st.edit("A", 12, partial_a, "pa")
    rb = st.edit("B", 12, partial_b, "pb")
    check(ra.get("error") == "INVALID_EDIT" and rb.get("error") == "INVALID_EDIT" and st.head == 12,
          "i batch incompleti dovevano essere rifiutati")
    print("  con il server: A %s (%s), B %s (%s), head resta %d" % (
        ra["error"], ", ".join(sorted(set(v[0] for v in ra["violations"]))),
        rb["error"], ", ".join(sorted(set(v[0] for v in rb["violations"]))), st.head))
    # Intenti completi: A arriva prima, B va in conflitto, rilegge e ripianifica sulla 13.
    st = Store(BASE)
    st.edit("A", 12, REMOVE_NO_BRANCH, "ca", "fermo i ticket non urgenti")
    rb = st.edit("B", 12, REMOVE_BRANCH, "cb", "tutto in approvazione umana")
    check(rb.get("error") == "CONFLICT", "B doveva andare in conflitto")
    replan = [{"op": "set_edge", "id": "e2", "to": "n4"}, {"op": "remove_edge", "id": "e3"},
              {"op": "remove_edge", "id": "e7"}, {"op": "remove_node", "id": "n3"}]
    rb2 = st.edit("B", st.head, replan, "cb2", "tutto in approvazione umana")
    check(rb2["ok"] and topology(st.revs[st.head]) == "n1>n2 n2>n4 n4>n6", "ripianificazione di B fallita")
    print("  intenti completi: A OK->13, B CONFLICT, B rilegge e ripianifica: %s | %s" % (
        code(rb2), topology(st.revs[st.head])))


def run_t6_layers():
    print("\n== T6: i due livelli di difesa ==")
    st = Store(BASE)
    alone = st.edit("A", 12, [{"op": "remove_item", "node": "n2", "key": "fields", "item": "urgency"}], "t6")
    check(alone.get("error") == "INVALID_EDIT", "togliere urgency da solo doveva essere invalido")
    print("  togliere urgency e basta: %s (%s)" % (alone["error"], alone["violations"][0][2]))
    _, _, a_ops, b_ops, _ = [c for c in CASES if c[0] == "T6"][0]
    for first, second, f_ops, s_ops in (("A", "B", a_ops, b_ops), ("B", "A", b_ops, a_ops)):
        st = Store(BASE, track_refs=False)        # il read set non vede la dipendenza
        st.edit(first, 12, f_ops, "x1")
        r2 = st.edit(second, 12, s_ops, "x2")
        check(r2.get("error") == "MERGE_INVALID", "il validatore doveva fermare il secondo commit")
        print("  senza read set sui riferimenti, %s prima: %s %s (%s)" % (
            first, second, r2["error"], r2["violations"][0][2]))


def run_deploy():
    print("\n== T8: corsa al deploy ==")
    a_ops, b_ops = CASES[0][2], CASES[0][3]
    for winner in ("A", "B"):
        st = Store(BASE)
        st.start_run("ticket-in-approvazione")
        ra = st.edit("A", 12, a_ops, "da")
        rb = st.edit("B", 12, b_ops, "db")
        ta, tb = st.test(ra["revision"]), st.test(rb["revision"])
        seen = st.live                           # entrambi hanno visto live = 12
        calls = {"A": (ra["revision"], ta["test_id"]), "B": (rb["revision"], tb["test_id"])}
        loser = "B" if winner == "A" else "A"
        d1 = st.deploy(calls[winner][0], seen, calls[winner][1])
        d2 = st.deploy(calls[loser][0], seen, calls[loser][1])
        check(d1["ok"] and d2.get("error") == "LIVE_MOVED", "doveva passare un solo deploy")
        line = "  %s vince: live %d | %s LIVE_MOVED (la live contiene gia' la sua: %s)" % (
            winner, st.live, loser, d2["live_contains_your_revision"])
        d3 = st.deploy(calls[loser][0], st.live, calls[loser][1])
        line += " | riprova: %s" % ("OK, live %d" % st.live if d3["ok"] else d3["error"])
        check(st.live == 14, "la live doveva finire sulla 14")
        check(st.runs["ticket-in-approvazione"] == 12, "il run in corso doveva restare sulla 12")
        print(line + " | run in corso sulla %d" % st.runs["ticket-in-approvazione"])

    st = Store(BASE)
    ra = st.edit("A", 12, a_ops, "dx")
    proof_12 = st.test(12)                       # la prova della 12, di quando era andata in produzione
    no_test = st.deploy(ra["revision"], st.live, proof_12["test_id"])
    check(no_test.get("error") == "TEST_REQUIRED", "serviva un test sul contenuto esatto")
    print("  test fatto su un'altra revisione: %s" % no_test["error"])

    print("\n== Rollback come commit ==")
    st.deploy(13, 12, st.test(13)["test_id"])    # la 13 va in produzione e si rivela sbagliata
    stale = st.edit("C", 12, [{"op": "restore", "revision": 12}], "rs", "ritiro la 13")
    check(stale.get("error") == "CONFLICT", "un restore da una base vecchia deve andare in conflitto")
    back = st.edit("C", st.head, [{"op": "restore", "revision": 12}], "rb", "ritiro la 13")
    check(back["ok"] and st.revs[back["revision"]] == BASE, "il restore doveva ridare il contenuto della 12")
    again = st.deploy(back["revision"], 13, proof_12["test_id"])   # stesso contenuto: la prova vale ancora
    check(again["ok"] and st.live == 14 and st.head == 14, "dopo il restore head e live devono coincidere")
    old = st.deploy(13, 12, None)
    check(old.get("error") == "LIVE_MOVED", "una richiesta vecchia non deve passare")
    never = st.edit("C", st.head, [{"op": "restore", "revision": 99}], "rn")
    check(never.get("error") == "INVALID_EDIT", "si ripristina solo una revisione gia' pubblicata")
    print("  restore della 12: nuova revisione %d con lo stesso contenuto, pubblicata con la prova della 12" % back["revision"])
    print("  head %d = live %d: il prossimo deploy non puo' riportare la modifica ritirata" % (st.head, st.live))
    print("  restore da una base vecchia: %s | richiesta di deploy vecchia: %s | restore di una revisione mai pubblicata: %s" % (
        stale["error"], old["error"], never["error"]))


def run_retry():
    print("\n== T9: agente inaffidabile ==")
    st = Store(BASE)
    ops = insert_after_n2("nT", "eT", "Translate")
    first = st.edit("A", 12, ops, "retry-1")
    again = st.edit("A", 12, ops, "retry-1")
    check(again.get("revision") == first["revision"] and st.head == 13 and again.get("replayed"),
          "il retry non deve creare una seconda revisione")
    other = st.edit("A", 12, CASES[0][2], "retry-1")
    check(other.get("error") == "KEY_REUSED", "stessa chiave con contenuto diverso va rifiutata")
    nxt = st.edit("B", 12, CASES[0][3], "b-1")
    check(nxt["ok"], "B deve poter continuare")
    print("  stessa chiamata ripetuta: stessa revisione %d, head %d | chiave riusata con altro "
          "contenuto: %s | B continua: %s" % (first["revision"], 13, other["error"], code(nxt)))


def effect_holds(spec, op):
    """L'effetto di un'operazione accettata si vede ancora nello stato finale?"""
    try:
        return _effect_holds(spec, op)
    except KeyError:                         # il nodo o l'arco su cui aveva scritto non c'e' piu'
        return False


def _effect_holds(spec, op):
    kind, nodes, edges = op["op"], spec["nodes"], spec["edges"]
    if kind == "restore":
        return True
    if kind == "set":
        return nodes[op["node"]]["config"][op["key"]] == op["value"]
    if kind == "add_item":
        return op["item"] in nodes[op["node"]]["config"][op["key"]]
    if kind == "remove_item":
        return op["item"] not in nodes[op["node"]]["config"][op["key"]]
    if kind == "set_input":
        return nodes[op["node"]]["inputs"][op["name"]] == op["ref"]
    if kind == "add_node":
        return op["id"] in nodes
    if kind == "remove_node":
        return op["id"] not in nodes
    if kind == "add_edge":
        return op["id"] in edges
    if kind == "set_edge":
        return all(edges[op["id"]][k] == op[k] for k in ("from", "to", "on") if k in op)
    return op["id"] not in edges             # remove_edge


def run_exhaustive():
    print("\n== Verifica esaustiva ==")
    pool = []
    for case in CASES:
        pool.extend([case[2], case[3]])
    pool.append([{"op": "remove_item", "node": "n2", "key": "fields", "item": "urgency"}])
    pool.append([{"op": "remove_node", "id": "n3"}])
    pool.append([{"op": "set", "node": "n4", "key": "required", "value": False}])
    unique = []
    for batch in pool:
        if batch not in unique:
            unique.append(batch)
    groups = accepted_total = 0
    for size in (2, 3):
        for combo in itertools.permutations(range(len(unique)), size):
            st, accepted = Store(BASE), []
            for position, index in enumerate(combo):
                result = st.edit("agente%d" % position, 12, unique[index], "k%d" % position)
                if result["ok"]:
                    accepted.append(unique[index])
                    replay = st.edit("agente%d" % position, 12, unique[index], "k%d" % position)
                    check(replay.get("revision") == result["revision"], "il retry ha creato una revisione")
            check(st.head == 12 + len(accepted), "una chiamata rifiutata ha lasciato traccia")
            check(all(validate(s) == [] for s in st.revs.values()), "revisione invalida salvata")
            final = st.revs[st.head]
            check(all(effect_holds(final, op) for batch in accepted for op in batch),
                  "una scrittura accettata e' andata persa: %s" % (combo,))
            groups += 1
            accepted_total += len(accepted)
    print("  %d batch distinti, %d gruppi ordinati da 2 e da 3 agenti, %d commit accettati" % (
        len(unique), groups, accepted_total))
    print("  ogni revisione salvata e' valida; nessuna scrittura accettata e' andata persa;")
    print("  un rifiuto non lascia traccia; un retry non crea revisioni")


if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(BASE, indent=2))
        sys.exit(0)
    check(validate(BASE) == [], "il workflow di esempio deve essere valido")
    run_pairs()
    run_right_frame()
    run_t6_layers()
    run_deploy()
    run_retry()
    run_exhaustive()
    print("\nTutti i controlli sono passati.")
