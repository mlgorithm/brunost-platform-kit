# Compatibility policy

The Platform Kit is the shared application boundary used by Premium and other
Brunost editions. It deliberately owns identity, contest/task projections,
signed callback handling, and policy adapters; the open-source Judge owns
execution, worker leases, artifacts, and result delivery.

## Supported line

| Component | Supported line |
| --- | --- |
| Platform Kit | `0.3.x` |
| Brunost Judge | `1.3.x` and later `1.x` releases |
| Task/evaluation/result contracts | the dependency-free models exported by `brunost_platform.contracts` |
| Callback result schema | `ResultEnvelope` via `normalize_result()` |

The Platform Kit deliberately has no runtime dependency on a particular Judge
Python package. It uses the versioned HTTP boundary, so it can be installed in
an existing Python/Django/FastAPI application or used alongside a separately
deployed Judge. If an application independently installs the Judge SDK, the
gateway can use it; the dependency-free HTTP transport remains the portable
default. Premium may pin this repository to a reviewed Platform Kit commit.

## Upgrade rule

1. Run the Platform Kit test suite and contract checks.
2. Run the matching Judge conformance and callback tests.
3. Update the Premium pin only after both repositories pass.
4. Roll out the Judge first, verify `/readyz`, then roll out Premium.

Backward-compatible additions are allowed within a major line. Breaking
changes require a new contract/schema version and a migration note.

The typed API is additive. `HttpJudgeGateway.register_task(**fields)` and
`HttpJudgeGateway.submit_evaluation(**fields)` continue to work for existing
applications; new applications should pass `TaskRegistration` and
`EvaluationRequest` objects. Both forms produce the Judge 1.3.x wire payload.
