# Push notifications: one-time setup

The app can send you notifications (breaking stories, weather alerts, village alerts). There is no public sign-up endpoint: you copy your phone's subscription into AWS once, by hand. Everything below runs on your own machine and phone. No secret value is ever pasted into chat or committed to the repo.

## What goes where

| Item | Secret? | Where it lives |
|---|---|---|
| VAPID private key | yes | SSM SecureString `/news/push/vapid-private-key` |
| VAPID public key | no | the `VAPID_PUBLIC_KEY` constant in `frontend/src/push.ts` |
| Phone registration (subscription + preferences) | yes (anyone holding it could send you pushes) | SSM SecureString `/news/push/registration` |

## Steps

1. **Make the key pair** on your machine (nothing is printed into this repo):

   ```sh
   cd "$(mktemp -d)" && npx --yes web-push generate-vapid-keys --json > vapid.json
   ```

   Alternative with Python: `pip install py-vapid && vapid --gen` (writes `private_key.pem` and `public_key.pem`; the public key is then printed with `vapid --applicationServerKey`).

2. **Store the private key** in SSM (use the value from `vapid.json`, then delete the file):

   ```sh
   aws ssm put-parameter --name /news/push/vapid-private-key --type SecureString \
     --value "$(python3 -c 'import json;print(json.load(open("vapid.json"))["privateKey"])')" --overwrite
   ```

3. **Put the public key in the app.** The public key is not a secret and is the `VAPID_PUBLIC_KEY` constant in `frontend/src/push.ts` (URL-safe base64, 87 characters). It is already set for the current key pair. If you ever make a new pair, replace the constant with the new `publicKey` from `vapid.json` and commit that in a PR; the Turn on button is disabled while the value is not a valid key.

4. **Install the app on your iPhone** (iOS 16.4 or later): open the site in Safari, Share, Add to Home Screen, then open it from the new icon. Notifications only work for an app opened from the Home Screen.

5. **Turn them on:** Settings, Notifications, Turn on notifications, and allow the iOS prompt. Choose the topics, weather alerts and quiet hours you want.

6. **Copy the registration:** tap Copy registration. If the copy fails, a box with the text appears: select it and copy it.

7. **Store the registration** in SSM (paste it between the single quotes):

   ```sh
   aws ssm put-parameter --name /news/push/registration --type SecureString --overwrite --value '<paste here>'
   ```

   The registration is JSON: `{"v":1,"site":"https://<the app's address>","subscription":{...},"prefs":{"topics":[...],"weather":true,"alerts":true,"quiet":{"start":"22:00","end":"07:00"},"tz":"America/Chicago"}}`.

8. **Delete `vapid.json`** from the folder it was created in.

VAPID claims use the site's own address as the subject, not an email address.

## Village alerts

Village alerts are pushed from the alert feeds you list under `"alerts"` in the optional SSM parameter `/news/local-feeds` (a plain `String`; see the README for its shape). Every item from those feeds that is under two days old and not yet sent is pushed once, newest first, ahead of breaking stories.

- They go through quiet hours (an official alert feed is rare), but share the other limits: at most 2 pushes per run and 5 per local day.
- They are on by default. The "Village alerts" switch in Settings (Notifications) turns them off; copy the registration again afterwards (steps 6 and 7). A registration made before this switch existed keeps getting them.
- The first run that sees an alert feed (and has village alerts switched on) marks whatever the feed already holds as sent, without pushing it. Only items that appear after that are pushed, so adding a feed never sends a backlog, least of all at night.
- The sent ids start with `alert:` in the private push state file, so they never collide with story ids.

## Changing preferences

Change topics, weather alerts, village alerts or quiet hours in Settings, then do steps 6 and 7 again. The server reads the parameter, so there is nothing to deploy.

The registration you copy replaces the one stored in SSM, including the preferences. Preferences are kept on the phone, so if the app's stored data is ever cleared they return to the defaults: check the toggles before copying again.

If you ever generate a new key pair, first tap Turn off in Settings, then Turn on again (an old subscription is tied to the old key), and redo steps 6 and 7.

## Turning notifications off

- On the phone: Settings, Notifications, Turn off.
- On the server: delete the parameter, which stops all sending at once:

  ```sh
  aws ssm delete-parameter --name /news/push/registration
  ```

## What a notification looks like

The sender sends `{"title", "body", "url", "tag"}`. Tapping it opens the app on the story: `/#/story/<cluster id>` (a story with several outlets) or `/#/read/<item id>` (a single article). The `tag` replaces an older notification about the same story instead of stacking a second one.

## Sending a test notification

To check the whole path (even in quiet hours), invoke the ingest Lambda by hand with the event `{"only": "push-test"}`. It sends one "Test notification" and ignores quiet hours, the caps and the dedupe state. The response says `"push": "sent"`, `"off"` (no valid registration), `"expired"` or `"failed"` (see the Lambda log).
