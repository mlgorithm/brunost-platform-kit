<?php

use Brunost\Http\Controllers\BrunostCallbackController;
use Brunost\Http\Controllers\LeaderboardController;
use Illuminate\Support\Facades\Route;

Route::post('/brunost/judge/callback', BrunostCallbackController::class)->name('brunost.judge.callback');
Route::get('/brunost/contests/{contestId}/leaderboard', LeaderboardController::class)->name('brunost.leaderboard');
