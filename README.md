# News

A personal, iPhone-first news app (PWA) on serverless AWS: a scheduled Lambda ingests free news feeds into JSON on S3, and CloudFront serves the Preact app and the JSON. No accounts, no API.

Status: scaffold plus deploy foundation (hello-world page, stub ingest handler, CDK stack, OIDC deploy job). Plan: [PLAN.md](PLAN.md).

## Development

```sh
make install   # Python (uv if installed) + Node tools
make check     # everything CI runs: privacy, lint, tests, frontend, audit, synth
```

## Deploying

Deploys run from CI on every push to `main`, through GitHub OIDC (no stored keys). One-time setup, in this order:

1. **Location config.** The home town and local feeds are not in the repo. Create the parameter by hand (region us-east-2); the ingest Lambda reads it at runtime:

   ```sh
   aws ssm put-parameter --region us-east-2 --name /news/location --type String --value \
     '{"town": "...", "lat": 0.0, "lon": 0.0, "nearby": ["..."], "feeds": ["https://..."]}'
   ```

   Optional: a private Markets watchlist. Add `"watch_key": "<16 to 64 random lowercase letters and digits>"`. Enter the same key once in the app's Settings, then add symbols there ("Edit watchlist symbols"). The symbols are stored in a private S3 object and the quotes in `data/watch-<sha256 of the key>.json` (so the key itself never appears in a URL); nothing about them is in a public file. The one endpoint (`POST /api/watchlist`, a Lambda Function URL behind CloudFront) refuses any request without the key. Without a key there is no watchlist.

2. **Deploy role (once, by hand).** This is the one exception to "no deploys from a laptop": CI has no role until this stack exists, and later changes to it need the same manual step. `NewsDeployRole` trusts this repository's `main` branch and can only assume the CDK bootstrap roles. It reuses the account's existing GitHub OIDC provider.

   ```sh
   npx --no-install cdk deploy NewsDeployRole
   ```

3. **Tell CI about it.** Set the repository variable `AWS_ROLE_ARN` to the role ARN from the stack output. Until it is set the deploy job is skipped.
