<?php

namespace Brunost;

use Illuminate\Support\ServiceProvider;

class BrunostServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->mergeConfigFrom(__DIR__ . '/../config/brunost.php', 'brunost');
        $this->app->singleton(JudgeClient::class, fn () => new JudgeClient(
            config('brunost.judge_url'),
            config('brunost.judge_token'),
        ));
    }

    public function boot(): void
    {
        $this->publishes([
            __DIR__ . '/../config/brunost.php' => config_path('brunost.php'),
            __DIR__ . '/../database/migrations' => database_path('migrations'),
        ], 'brunost-migrations');
        $this->loadRoutesFrom(__DIR__ . '/../routes/api.php');
        $this->loadMigrationsFrom(__DIR__ . '/../database/migrations');
    }
}
