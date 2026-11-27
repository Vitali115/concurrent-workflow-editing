"""Controlla i blocchi JSON di risposta-colloquio.md contro il prototipo.

Richiede jsonschema:  pip install -r verifiche/requirements.txt
"""
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import copy
import json
import re

import prototipo as p
from jsonschema import Draft202012Validator

md = open(os.path.join(ROOT, "risposta-colloquio.md"), encoding="utf-8").read()
blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", md, re.S)]
print("blocchi JSON ben formati:", len(blocks))

example = next(b for b in blocks if "entry" in b and "$schema" not in b)
schema = next(b for b in blocks if b.get("$id") == "urn:workflow:spec:v1")
tool = next(b for b in blocks if b.get("name") == "edit")
conflict = next(b for b in blocks if b.get("error") == "CONFLICT")

Draft202012Validator.check_schema(schema)
Draft202012Validator.check_schema(tool["input_schema"])
print("i due schemi sono JSON Schema 2020-12 validi")

assert example == p.BASE, "il workflow nel documento non coincide con quello del prototipo"
print("il workflow del documento e' identico a quello che esegue il prototipo")

wf = Draft202012Validator(schema)
assert not list(wf.iter_errors(example)), list(wf.iter_errors(example))
print("il workflow di esempio rispetta lo schema")

# Il riquadro di destra: unione senza controllo di 'togli n5,e4,e6' e 'togli n3'.
broken = copy.deepcopy(p.BASE)
for n in ("n3", "n5"): del broken["nodes"][n]
for e in ("e4", "e6"): del broken["edges"][e]
schema_errors = list(wf.iter_errors(broken))
print("riquadro di destra: errori di schema =", len(schema_errors), "| violazioni del validatore =", len(p.validate(broken)))
assert not schema_errors and p.validate(broken)

# Ogni revisione che il prototipo salva deve rispettare lo schema; ogni batch deve rispettare lo schema del tool.
tv = Draft202012Validator(tool["input_schema"])
batches = [c[2] for c in p.CASES] + [c[3] for c in p.CASES]
for i, ops in enumerate(batches):
    call = {"workflow_id": "wf-support", "base_revision": 12, "ops": ops, "intent": "x", "request_id": "r%d" % i}
    errs = list(tv.iter_errors(call))
    assert not errs, (i, [e.message for e in errs][:2])
    st = p.Store(p.BASE)
    r = st.edit("A", 12, ops, "k")
    assert r["ok"] and not list(wf.iter_errors(st.revs[st.head])), i
print("i %d batch dei casi rispettano lo schema di edit; le revisioni che producono rispettano lo schema del workflow" % len(batches))

# L'operazione restore rispetta lo schema.
assert not list(tv.iter_errors({"workflow_id": "w", "base_revision": 13, "intent": "ritiro la 13", "request_id": "r", "ops": [{"op": "restore", "revision": 12}]}))
print("lo schema di edit accetta restore")

# Lo schema del tool deve rifiutare la vecchia chiamata edit({spec}) e un'operazione sconosciuta.
assert list(tv.iter_errors({"spec": example}))
assert list(tv.iter_errors({"workflow_id": "w", "base_revision": 12, "intent": "x", "request_id": "r", "ops": [{"op": "replace_all"}]}))
assert list(tv.iter_errors({"workflow_id": "w", "base_revision": 12, "intent": "x", "request_id": "r", "ops": [{"op": "set_edge", "id": "e2"}]}))
print("lo schema di edit rifiuta edit({spec}), un'operazione sconosciuta e un set_edge vuoto")

# L'esempio di CONFLICT nel documento deve essere quello che restituisce il prototipo.
st = p.Store(p.BASE)
st.edit("agente-A", 12, [{"op": "set", "node": "n2", "key": "model", "value": "model-x"}], "a", "classificatore meno costoso")
real = st.edit("agente-B", 12, [{"op": "set", "node": "n2", "key": "model", "value": "model-y"}], "b", "x")
norm = lambda s: s.replace("e'", "è")
assert {k: v for k, v in conflict.items() if k != "next"} == {k: v for k, v in real.items() if k != "next"}
assert conflict["next"] == norm(real["next"]), (conflict["next"], real["next"])
print("l'esempio di CONFLICT coincide con l'output del prototipo")
