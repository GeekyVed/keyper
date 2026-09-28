# Security policy

## Supported version

The latest release on the `main` branch receives security fixes while Keyper
is in prototype status.

## Reporting a vulnerability

Do not open a public issue containing credentials, private RDP details, or a
working exploit. Use GitHub's private vulnerability reporting for this
repository instead. Include the affected command, version, impact, and a
minimal reproduction with all sensitive values removed.

## Intended use

Keyper is for explicitly authorized keyboard automation. It does not promise
that activity is hidden from the remote system: command history, PowerShell
logging, endpoint protection, RDS auditing, and screen recording may observe
everything it types.
