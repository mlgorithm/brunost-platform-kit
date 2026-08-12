# laravel-brunost

Composer package for Laravel competition platforms. It provides migrations,
Eloquent projections, a Judge HTTP client, callback verification, and routes
for the platform-owned contest/submission lifecycle.

```bash
composer require mlgorithm/laravel-brunost
php artisan vendor:publish --tag=brunost-migrations
php artisan migrate
```

The package accepts a content-addressed `submission_artifact_id`. Applications
can call `JudgeClient::uploadArtifact($directory)` and then `submit(...)`; the
Judge remains responsible for sandbox execution and scoring. Callback delivery
is signed, bearer-token protected, and deduplicated by the unique event ID.
The package also exposes a contest leaderboard endpoint that applies
visibility and best-attempt policy from the contest record.
