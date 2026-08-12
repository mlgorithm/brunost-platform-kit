<?php

namespace Brunost\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\QueryException;

class CallbackReceipt extends Model
{
    protected $table = 'brunost_callback_receipts';
    protected $guarded = [];
    protected $casts = ['payload' => 'array'];

    public static function createIfMissing(string $eventId, string $submissionId, array $payload): bool
    {
        try {
            return static::query()->firstOrCreate(['event_id' => $eventId], ['submission_id' => $submissionId, 'payload' => $payload])->wasRecentlyCreated;
        } catch (QueryException $exception) {
            // Two callback deliveries may race between SELECT and INSERT. The
            // unique event_id index makes the losing delivery a safe duplicate.
            if (in_array((string) $exception->getCode(), ['23000', '23505'], true)) {
                return false;
            }
            throw $exception;
        }
    }
}
