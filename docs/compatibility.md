# Compatibility policy

The Platform Kit is the shared application boundary used by Premium and other
Brunost editions. It deliberately owns identity, contest/task projections,
signed callback handling, and policy adapters; the open-source Judge owns
execution, worker leases, artifacts, and result delivery.

## Supported line

| Component | Supported line |
| --- | --- |
| Platform Kit | `0.2.x` |
| Brunost Judge | `1.3.x` and later `1.x` releases |
| Callback result schema | the version exported by `brunost_platform_kit.contracts` |

The optional `judge` extra is constrained to `brunost-judge>=1.3,<2`. This is
intentional: applications must not silently install the obsolete pre-1.0 SDK.
Premium may use the HTTP boundary and still pins this repository to a reviewed
Platform Kit commit.

## Upgrade rule

1. Run the Platform Kit test suite and contract checks.
2. Run the matching Judge conformance and callback tests.
3. Update the Premium pin only after both repositories pass.
4. Roll out the Judge first, verify `/readyz`, then roll out Premium.

Backward-compatible additions are allowed within a major line. Breaking
changes require a new contract/schema version and a migration note.
