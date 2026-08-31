# Changelog

## 0.3.0

- Make the package independently installable: the core uses the Judge HTTP
  contract and no longer asks the package resolver for an unpublished Judge
  distribution.
- Align CLI, task wizard, generated templates, and task scaffolds with the
  four public families: `coding`, `model`, `quiz`, and `optimization`.
- Generate Judge-valid starter manifests and required public/private assets for
  each family.
- Replace contest-format labels in the Judge-facing UI with portable task
  family and package-profile terminology.

## 0.2.0

- Introduced the framework-neutral gateway, reference UI, and generated
  FastAPI/Node/minimal application templates.
