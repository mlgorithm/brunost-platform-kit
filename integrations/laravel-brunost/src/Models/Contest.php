<?php

namespace Brunost\Models;

use Illuminate\Database\Eloquent\Model;

class Contest extends Model
{
    protected $table = 'brunost_contests';
    protected $guarded = [];
    protected $casts = ['task_refs' => 'array', 'policy' => 'array'];

    public function submissions()
    {
        return $this->hasMany(Submission::class, 'contest_id');
    }
}
