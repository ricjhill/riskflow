# How to: Process Large Files Asynchronously

## Goal

Upload a large bordereaux file without waiting for the result. Get a job ID, then poll for the result when it's ready.

## When to use this

Use async upload when:
- The file has thousands of rows and processing takes more than a few seconds
- You want to submit multiple files and collect results later
- Your client has a short HTTP timeout

## Steps

### 1. Submit the file

```bash
curl -F "file=@large_bordereaux.csv" http://localhost:8000/upload/async
```

Response (immediate — no waiting):

```json
{"job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}
```

### 2. Poll for status

```bash
curl http://localhost:8000/jobs/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Response while processing:

```json
{
  "job_id": "a1b2c3d4-...",
  "status": "PROCESSING",
  "result": null,
  "error": null
}
```

### 3. Get the result

When status is "COMPLETE":

```json
{
  "job_id": "a1b2c3d4-...",
  "status": "COMPLETE",
  "result": {
    "mapping": { ... },
    "valid_records": [ ... ],
    "invalid_records": [ ... ],
    "errors": [ ... ],
    "confidence_report": { ... }
  },
  "error": null
}
```

The `result` object has the same shape as the synchronous `/upload` response.

## Job statuses

| Status | Meaning |
|--------|---------|
| PENDING | Job created, not yet started |
| PROCESSING | File is being mapped and validated |
| COMPLETE | Results ready in the `result` field |
| FAILED | Processing failed — check the `error` field |

## What if the job ID doesn't exist?

```json
{"detail": "Job not found"}
```

Status code: 404.
