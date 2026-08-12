<?php

return [
    'judge_url' => env('BRUNOST_JUDGE_URL', 'http://127.0.0.1:8787'),
    'judge_token' => env('BRUNOST_JUDGE_API_TOKEN'),
    'callback_secret' => env('BRUNOST_JUDGE_CALLBACK_SECRET'),
    'callback_token' => env('BRUNOST_PLATFORM_CALLBACK_TOKEN'),
];
