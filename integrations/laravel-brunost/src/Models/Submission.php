<?php

namespace Brunost\Models;

use Illuminate\Database\Eloquent\Model;

class Submission extends Model
{
    protected $table = 'brunost_submissions';
    protected $primaryKey = 'submission_id';
    public $incrementing = false;
    protected $keyType = 'string';
    protected $guarded = [];
    protected $casts = ['metrics' => 'array'];

    public function contest()
    {
        return $this->belongsTo(Contest::class, 'contest_id');
    }
}
