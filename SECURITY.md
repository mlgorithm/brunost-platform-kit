# Security policy

Report suspected vulnerabilities privately to the Brunost maintainers before
opening a public issue. Do not include production credentials, private task
assets, or unredacted contestant submissions in reports.

The Platform Kit does not execute untrusted submissions. It forwards immutable
requests to Brunost Judge and should treat callbacks as untrusted input until
their signature, timestamp, and idempotency key are verified.
