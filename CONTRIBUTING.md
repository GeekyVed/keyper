# Contributing

Small, reviewable pull requests are welcome.

## Local checks

Run the same dependency-free checks used by CI:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m py_compile rdpiano
bash -n install.sh
```

If you change the PowerShell protocol, add a regression test that verifies the
payload round trip and generated command structure. Never test keyboard output
against an unapproved target window.

## Scope

RDPiano intentionally stays visible, user-initiated, and auditable. Changes
that add stealth, evade monitoring, capture credentials, remove target-window
guards, or operate without explicit user action are out of scope.
