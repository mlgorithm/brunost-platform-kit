# Open-source standalone and Brunost Premium

The Platform Kit is the shared application boundary around Brunost Judge. It
does not replace an existing Brunost frontend or user database. A country can
run the generated reference application as a complete contest website, while
Brunost Premium can use the same APIs from its current UI.

## What is shared

| Capability | Owner | Standalone | Premium |
| --- | --- | --- | --- |
| Sandboxed execution, scoring, workers, artifacts | Brunost Judge | shared | shared |
| Contest identity, task membership, registration | Platform Kit contract | shared | shared |
| Signed callbacks and result projection | Platform Kit contract | shared | shared |
| Login, courses, organizations, email, analytics | embedding platform | local adapter | Brunost private modules |
| Global/public task library | Platform UI capability | hidden by default | enabled when configured |

The Judge remains a separate service. Submissions cross the boundary as
content-addressed artifacts, and results return through signed callbacks. The
existing Brunost UI can therefore remain unchanged while its backend switches
to the same gateway and contract in a staged migration.

## Standalone profile

`BRUNOST_PLATFORM_EDITION=standalone` is the default. It is designed for a
country operator who wants to install a contest website without writing
integration code:

- the bootstrap account is `admin`;
- later self-registered accounts are `student`;
- only administrators create or manage contests;
- tasks are created from a contest workspace;
- the global task-library pages are not shown and direct access returns 404;
- Judge APIs remain available to integrations and deployment tooling.

This is a UI and policy profile, not a second Judge implementation. Developers
can enable optional capabilities without forking the core.

## Premium profile

`BRUNOST_PLATFORM_EDITION=advanced` enables the broader profile. Organizer,
teacher, contest-creator, and owner projections may create contests, and the
global task library and course hooks are available. Premium should still keep
its own authentication, user records, courses, and product UI. It calls
`PlatformApplication` or the HTTP gateway rather than copying contest logic.

For a private identity provider, use `ExternalIdentityAdapter`:

```python
from brunost_platform.identity import ExternalIdentityAdapter

identity = ExternalIdentityAdapter(lambda request: {
    "sub": request.user.id,
    "email": request.user.email,
    "display_name": request.user.name,
    "roles": request.user.roles,
    "organization_id": request.user.organization_id,
})
principal = identity.resolve(request)
```

Only the opaque subject and authorization projection cross into the contest
core. Passwords, sessions, and provider tokens stay private.

## Configuration and extension

```bash
BRUNOST_PLATFORM_EDITION=standalone
BRUNOST_PLATFORM_FEATURES=
```

For a custom profile, use comma-separated capability names such as
`task.global-library`, `courses`, or `contest.user-created`. The policy is
intentionally additive: enabling a feature exposes the existing API/UI seam;
it does not delete or fork the Judge implementation.

The recommended migration is:

1. Run the standalone reference UI against a local Judge.
2. Keep Brunost users and sessions in the existing platform.
3. Map the current user to an `ExternalPrincipal` and send the same contest and
   submission requests through the SDK/gateway.
4. Enable advanced capabilities only where Premium product policy allows them.
5. Compare callback and leaderboard projections before switching production
   traffic.

