"""Rompe apposta una regola alla volta e controlla che i test del prototipo se ne accorgano."""
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import contextlib
import io

import prototipo as p

def attempt(label, fn, must_fail=True):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fn()
        failed, why = False, ""
    except AssertionError as e:
        failed, why = True, str(e)[:80]
    ok = failed == must_fail
    print(("ok   " if ok else "ERRORE"), label, ("-> " + why) if why else "")
    return ok

results = []
everything = lambda: (p.run_pairs(), p.run_right_frame(), p.run_t6_layers(), p.run_deploy(), p.run_retry(), p.run_exhaustive())
results.append(attempt("nessuna mutazione: tutto passa", everything, must_fail=False))

orig = p.related
p.related = lambda a, b: False
results.append(attempt("collisioni spente (ultimo che scrive vince)", p.run_exhaustive))
p.related = orig

validate = p.validate
orig_edit = p.Store._edit
def edit_without_merge_validation(self, agent, base, ops, intent):
    head_before = self.head
    if base == head_before:
        return orig_edit(self, agent, base, ops, intent)
    try:
        cand, W, R = p.apply_ops(self.revs[base], ops, False, self._released())
    except p.BadOp:
        return {"ok": False, "error": "INVALID_EDIT", "violations": []}
    if validate(cand):
        return {"ok": False, "error": "INVALID_EDIT", "violations": validate(cand)}
    for rev in range(base + 1, self.head + 1):
        c = self.log[rev]
        if any(p.related(m, t) for m in W | R for t in c["W"]) or any(p.related(m, t) for m in W for t in c["R"]):
            return {"ok": False, "error": "CONFLICT", "head": self.head, "conflicts": []}
    try:
        cand, W, R = p.apply_ops(self.revs[self.head], ops, False, self._released())
    except p.BadOp:
        return {"ok": False, "error": "MERGE_INVALID", "violations": []}
    self.head += 1
    self.revs[self.head] = cand
    self.log[self.head] = {"by": agent, "intent": intent, "W": W, "R": R, "ops": ops, "base": base}
    return {"ok": True, "revision": self.head, "rebased_over": []}
p.Store._edit = edit_without_merge_validation
results.append(attempt("niente validazione dopo il rebase, read set cieco sui riferimenti", p.run_exhaustive))
p.Store._edit = orig_edit

orig_deploy = p.Store.deploy
p.Store.deploy = lambda self, revision, expect_live, test_id=None: orig_deploy(self, revision, self.live, test_id)
results.append(attempt("deploy senza compare-and-swap", p.run_deploy))
p.Store.deploy = orig_deploy

def deploy_not_forward_only(self, revision, expect_live, test_id=None):
    if expect_live != self.live:
        return orig_deploy(self, revision, expect_live, test_id)
    self.live = revision
    return {"ok": True, "live": self.live}
p.Store.deploy = deploy_not_forward_only
results.append(attempt("deploy senza il vincolo solo-in-avanti e senza prova di test", p.run_deploy))
p.Store.deploy = orig_deploy

orig_digest = p.digest
p.digest = lambda spec: "uguale-per-tutti"
results.append(attempt("prova di test non legata al contenuto", p.run_deploy))
p.digest = orig_digest

orig_edit_pub = p.Store.edit
def edit_without_idempotency(self, agent, base_revision, ops, request_id, intent=""):
    return self._edit(agent, base_revision, ops, intent)
p.Store.edit = edit_without_idempotency
results.append(attempt("niente idempotenza", p.run_retry))
p.Store.edit = orig_edit_pub

print("tutte le mutazioni rilevate" if all(results) else "ATTENZIONE: qualche controllo non ha i denti")
