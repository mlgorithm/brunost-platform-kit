<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('brunost_contests', function (Blueprint $table) {
            $table->id(); $table->string('contest_id')->unique(); $table->string('name'); $table->json('task_refs'); $table->string('status')->default('draft'); $table->json('policy')->nullable(); $table->timestamps();
        });
        Schema::create('brunost_submissions', function (Blueprint $table) {
            $table->string('submission_id')->primary(); $table->foreignId('contest_id')->constrained('brunost_contests'); $table->string('contestant_id'); $table->string('task_ref'); $table->string('artifact_id', 128); $table->string('evaluation_id')->nullable(); $table->string('status')->default('queued'); $table->double('score')->nullable(); $table->json('metrics')->nullable(); $table->timestamps();
        });
        Schema::create('brunost_callback_receipts', function (Blueprint $table) {
            $table->id(); $table->string('event_id')->unique(); $table->string('submission_id'); $table->json('payload'); $table->timestamps();
        });
        Schema::create('brunost_leaderboard', function (Blueprint $table) {
            $table->string('evaluation_id')->primary(); $table->foreignId('contest_id')->constrained('brunost_contests'); $table->string('contestant_id'); $table->string('task_ref'); $table->double('score')->nullable(); $table->boolean('visible')->default(false); $table->json('metadata')->nullable(); $table->timestamps();
            $table->index(['contest_id', 'visible', 'score']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('brunost_leaderboard'); Schema::dropIfExists('brunost_callback_receipts'); Schema::dropIfExists('brunost_submissions'); Schema::dropIfExists('brunost_contests');
    }
};
