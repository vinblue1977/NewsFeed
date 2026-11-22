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

   Optional, in a second parameter (the location one is near its size limit): the village's or school's own feeds. Create `/news/local-feeds` by hand (the ingest reads it when it exists, and runs fine without it):

   ```sh
   aws ssm put-parameter --region us-east-2 --name /news/local-feeds --type String --value \
     '{"official": ["https://village.example/news.xml"], "alerts": ["https://village.example/alerts.xml"]}'
   ```

   Both lists are optional. `"official"` feeds (or a Google News `site:` search of a website) go to Local without the nearby-place check, so list only feeds that are about the place; a broad or regional feed belongs in `"feeds"` of the location parameter. (An `"official"` list in the location parameter still works; the two are merged, each URL once.) `"alerts"` feeds are treated the same way, and every new item in them, under two days old, is also pushed to your phone once (see `docs/PUSH.md`).

   Optional: a private Markets watchlist. Add `"watch_key": "<16 to 64 random lowercase letters and digits>"`. Enter the same key once in the app's Settings, then add symbols there ("Edit watchlist symbols"). The symbols are stored in a private S3 object and the quotes in `data/watch-<sha256 of the key>.json` (so the key itself never appears in a URL); nothing about them is in a public file. The one endpoint (`POST /api/watchlist`, a Lambda Function URL behind CloudFront) refuses any request without the key. Without a key there is no watchlist.

2. **Deploy role (once, by hand).** This is the one exception to "no deploys from a laptop": CI has no role until this stack exists, and later changes to it need the same manual step. `NewsDeployRole` trusts this repository's `main` branch and can only assume the CDK bootstrap roles. It reuses the account's existing GitHub OIDC provider.

   ```sh
   npx --no-install cdk deploy NewsDeployRole
   ```

3. **Tell CI about it.** Set the repository variable `AWS_ROLE_ARN` to the role ARN from the stack output. Until it is set the deploy job is skipped.

## Push notifications (backend)

After each ingest run the Lambda can push a breaking story to your phone (Web Push through Apple's push service: free). It is off until two SecureString parameters exist (region us-east-2); with either missing, the step does nothing and logs one line.

- `/news/push/vapid-private-key`: the VAPID private key as a PEM. The accepted format is the SEC1 PEM that `openssl ecparam -name prime256v1 -genkey -noout` prints (`-----BEGIN EC PRIVATE KEY-----`); PKCS#8 or a 32-byte URL-safe base64 scalar also work. Store it from a file (`--value file://key.pem`), never in the repo or on a command line you share.
- `/news/push/registration`: written once the app can subscribe your phone (the app shows the JSON to copy). Shape: `{"v": 1, "site": "https://<the app's origin>", "subscription": {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}, "prefs": {"topics": ["us", "world", "india", "sports", "local"], "weather": true, "quiet": {"start": "22:00", "end": "07:00"}, "tz": "America/Chicago"}}`. `site` is the VAPID `sub` claim (a URL, never an email); it is a field of the registration because the stack cannot reference the site's domain from the Lambda without a circular dependency.

What qualifies: a story covered by 6 or more outlets in the last 2 hours, or a BREAKING / Developing / LIVE headline from a trusted outlet, in a topic you switched on. At most 2 pushes per run and 5 per local day, nothing during quiet hours, each story once (the sent ids are in a private, hashed-name file under `data/`, pruned after 3 days). If the push service answers 404 or 410 the subscription is gone: the Lambda logs it and stops, and you register the phone again. Weather alerts (when `weather` is on in the registration): each active National Weather Service alert of Severe or Extreme severity that has not ended is pushed once, through quiet hours and without using the daily cap (the per-run cap still applies). Moderate and Minor alerts stay on the weather card only.

The Lambda bundles `cryptography` at deploy time (`requirements-lambda.in`, locked with `make lock`; `infra/bundle.py` installs the Linux ARM64 wheels from the hashed lockfile, no Docker).
