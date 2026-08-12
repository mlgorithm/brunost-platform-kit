<?php

namespace Brunost\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Brunost\Models\CallbackReceipt;
use Brunost\Models\LeaderboardProjection;
use Brunost\Models\Submission;

class BrunostCallbackController
{
    public function __invoke(Request $request): JsonResponse
    {
        $expectedToken = (string) config('brunost.callback_token', '');
        if ($expectedToken && !hash_equals('Bearer ' . $expectedToken, (string) $request->header('Authorization'))) {
            return response()->json(['detail' => 'invalid callback bearer token'], 401);
        }
        $eventId = trim((string) $request->header('X-Brunost-Judge-Event-ID'));
        $timestamp = trim((string) $request->header('X-Brunost-Judge-Timestamp'));
        $signature = trim((string) $request->header('X-Brunost-Judge-Signature'));
        $expected = 'sha256=' . hash_hmac('sha256', "{$timestamp}.{$eventId}." . $request->getContent(), (string) config('brunost.callback_secret'));
        if (!$eventId || !$timestamp || !$signature || abs(time() - (int) $timestamp) > 300 || !hash_equals($expected, $signature)) {
            return response()->json(['detail' => 'invalid callback signature'], 401);
        }
        $payload = $request->json()->all();
        $submission = Submission::query()->find((string) data_get($payload, 'metadata.platform_submission_id'));
        if (!$submission) {
            return response()->json(['detail' => 'unknown submission'], 404);
        }
        if (!CallbackReceipt::createIfMissing($eventId, $submission->submission_id, $payload)) {
            return response()->json(['status' => 'duplicate', 'event_id' => $eventId]);
        }
        $submission->update(['status' => data_get($payload, 'status', 'failed'), 'score' => data_get($payload, 'score'), 'metrics' => data_get($payload, 'metrics', []), 'evaluation_id' => data_get($payload, 'evaluation_id', data_get($payload, 'execution_id'))]);
        LeaderboardProjection::query()->updateOrCreate(
            ['evaluation_id' => $submission->evaluation_id],
            ['contest_id' => $submission->contest_id, 'contestant_id' => $submission->contestant_id, 'task_ref' => $submission->task_ref, 'score' => $submission->score, 'visible' => (bool) data_get($submission->contest->policy, 'leaderboard_visible', false), 'metadata' => ['status' => $submission->status, 'metrics' => $submission->metrics]],
        );
        return response()->json(['status' => $submission->status, 'event_id' => $eventId]);
    }
}
