# News

A personal, iPhone-first news app (PWA) on serverless AWS: a scheduled Lambda ingests free news feeds into JSON on S3, and CloudFront serves the Preact app and the JSON. No accounts, no API.

Status: repo scaffold only (hello-world page, stub ingest handler, empty-ish CDK stack). Plan: [PLAN.md](PLAN.md).

## Development

```sh
make install   # Python (uv if installed) + Node tools
make check     # everything CI runs: privacy, lint, tests, frontend, audit, synth
```
