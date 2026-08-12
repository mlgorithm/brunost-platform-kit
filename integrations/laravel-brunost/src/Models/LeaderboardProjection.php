<?php

namespace Brunost\Models;

use Illuminate\Database\Eloquent\Model;

class LeaderboardProjection extends Model
{
    protected $table = 'brunost_leaderboard';
    protected $primaryKey = 'evaluation_id';
    public $incrementing = false;
    protected $keyType = 'string';
    protected $guarded = [];
    protected $casts = ['visible' => 'boolean', 'metadata' => 'array'];
}
