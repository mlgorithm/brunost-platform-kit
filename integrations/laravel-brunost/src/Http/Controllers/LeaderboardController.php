<?php

namespace Brunost\Http\Controllers;

use Brunost\Models\Contest;
use Brunost\Models\LeaderboardProjection;
use Illuminate\Http\JsonResponse;

class LeaderboardController
{
    public function __invoke(string $contestId): JsonResponse
    {
        $contest = Contest::query()->where('contest_id', $contestId)->firstOrFail();
        if (!data_get($contest->policy, 'leaderboard_visible', false)) {
            return response()->json([]);
        }
        $rows = LeaderboardProjection::query()->where('contest_id', $contest->id)->where('visible', true)->orderByDesc('score')->orderBy('contestant_id')->orderBy('task_ref')->get();
        $best = [];
        foreach ($rows as $row) {
            $key = $row->contestant_id . ':' . $row->task_ref;
            if (data_get($contest->policy, 'best_attempt', true) && isset($best[$key])) {
                continue;
            }
            $best[$key] = $row;
        }
        $output = [];
        foreach (array_values($best) as $rank => $row) {
            $output[] = ['rank' => $rank + 1, 'contestant_id' => $row->contestant_id, 'task_ref' => $row->task_ref, 'score' => $row->score, 'metadata' => $row->metadata];
        }
        return response()->json($output);
    }
}
