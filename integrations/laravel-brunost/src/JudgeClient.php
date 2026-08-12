<?php

namespace Brunost;

use Illuminate\Support\Facades\Http;

class JudgeClient
{
    public function __construct(private readonly string $baseUrl, private readonly ?string $token = null) {}

    private function request(string $method, string $path, array $payload = []): array
    {
        $request = Http::baseUrl(rtrim($this->baseUrl, '/'))->acceptJson();
        if ($this->token) {
            $request = $request->withToken($this->token);
        }
        return $request->{$method}($path, $payload)->throw()->json();
    }

    public function submit(string $taskRef, string $submissionArtifactId, string $idempotencyKey, array $metadata = [], ?string $callbackUrl = null, ?string $callbackToken = null): array
    {
        return $this->request('post', '/v1/evaluations', [
            'task_ref' => $taskRef,
            'submission_artifact_id' => $submissionArtifactId,
            'idempotency_key' => $idempotencyKey,
            'metadata' => $metadata,
            'callback_url' => $callbackUrl,
            'callback_token' => $callbackToken,
        ]);
    }

    public function uploadArtifact(string $directory): array
    {
        $archive = new \PharData(tempnam(sys_get_temp_dir(), 'brunost-') . '.tar');
        $archive->buildFromDirectory($directory);
        $tarPath = $archive->getPath();
        $gzipPath = $archive->compress(\Phar::GZ)->getPath();
        $bytes = file_get_contents($gzipPath);
        if ($bytes === false) {
            throw new \RuntimeException('could not read packaged submission');
        }
        $artifactId = hash('sha256', $bytes);
        $request = Http::baseUrl(rtrim($this->baseUrl, '/'))->acceptJson()->withBody($bytes, 'application/gzip');
        if ($this->token) {
            $request = $request->withToken($this->token);
        }
        $request->put('/v1/artifacts/' . $artifactId)->throw();
        @unlink($tarPath);
        @unlink($gzipPath);
        return ['artifact_id' => $artifactId, 'size_bytes' => strlen($bytes), 'sha256' => $artifactId];
    }

    public function cancel(string $evaluationId): array
    {
        return $this->request('post', "/v1/executions/{$evaluationId}/cancel");
    }
}
