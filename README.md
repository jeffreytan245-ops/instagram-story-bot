# Instagram Daily Story Bot

Posts one Instagram Story every day at 13:00, fully in the cloud on GitHub Actions. Your computer does not need to be on. Free, no third-party scheduler, uses the official Instagram Graph API.

## How it works

- Your story images/videos live in the `media/` folder of a public GitHub repo.
- A GitHub Actions cron runs `post_story.py` every hour. The script posts only once per day, inside the 13:00–15:00 window in your timezone (the extra hours cover GitHub cron delays and retries).
- After posting, the workflow commits `state.json` back so the next day picks the next item.
- The 60-day access token is refreshed automatically after 45 days.

## Setup (about 20 minutes, one time)

### 1. Instagram API credentials

1. Your Instagram account must be **professional** (Business or Creator). Switch in Instagram: Settings → Account type and tools → Switch to professional account.
2. Go to https://developers.facebook.com/apps → **Create app** → use case "Other" → type **Business**.
3. In the app dashboard add the **Instagram** product → **Instagram API with Instagram Login**.
4. App roles → Roles → **Add people** → Instagram Testers → your IG username.
   In the Instagram app: Settings → Website permissions → Apps and websites → Tester invites → accept.
5. Instagram → API setup with Instagram login → **Generate token** for your account.
   Grant `instagram_business_basic` and `instagram_business_content_publish`. Copy the token (it is already long-lived).
6. Get your account ID: open in a browser
   `https://graph.instagram.com/me?fields=user_id,username&access_token=YOUR_TOKEN`
   and copy the `user_id` value.

The app can stay in Development mode. It only needs to post to your own (tester) account, so no App Review.

### 2. Create the GitHub repo

1. Create a new **public** repository on GitHub (public is required so the raw media links work; see "Private repo" below if you need otherwise).
2. Upload everything in this folder to it, including the hidden `.github` folder. Easiest from this folder:

```bash
git init && git add -A && git commit -m "Instagram story bot" && git branch -M main
```

```bash
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git && git push -u origin main
```

3. In the repo: Settings → Secrets and variables → Actions → **New repository secret**:
   - `IG_USER_ID` = the user_id from step 1.6
   - `IG_ACCESS_TOKEN` = the token from step 1.5
4. Optional but recommended, so the token refresh can save itself: create a fine-grained personal access token at https://github.com/settings/personal-access-tokens → only this repo → Repository permissions → **Secrets: Read and write**. Save it as a third secret named `GH_PAT`. Without it the bot still works, but every ~50 days you must paste a new `IG_ACCESS_TOKEN` yourself (the workflow log will warn you).
5. Settings → Actions → General → Workflow permissions → **Read and write permissions** (needed to commit `state.json`).

### 3. Timezone and hour

Edit `.github/workflows/post-story.yml` if needed:

```yaml
TIMEZONE: Asia/Bangkok   # IANA name, e.g. Asia/Singapore, Europe/London, America/New_York
POST_HOUR: "13"
```

Default is Asia/Bangkok (UTC+7), the timezone of the PC this was built on.

### 4. Add stories and test

1. Drop files into `media/` (JPEG 1080×1920 for images, MP4 3–60 s for video) and list them in `queue.json`:

```json
{
  "mode": "sequential",
  "items": [
    { "file": "media/2026-10-21.jpg" },
    { "file": "media/2026-10-22.mp4" },
    { "url": "https://cdn.example.com/hosted-elsewhere.jpg" }
  ]
}
```

   `"mode": "loop"` restarts from the top when the list ends; `"sequential"` stops and logs "queue exhausted".

2. Commit and push.
3. Test immediately: repo → **Actions** → "Daily Instagram Story" → **Run workflow** → tick **force** → Run. Check the log, then your Instagram story.

From then on it posts by itself every day at 13:00.

## Media specs

| Type  | Format            | Max size | Ratio            | Other         |
|-------|-------------------|----------|------------------|---------------|
| Image | JPEG (not PNG)    | 8 MB     | 9:16, 1080×1920  |               |
| Video | MP4, H.264 + AAC  | 100 MB   | 9:16             | 3–60 seconds  |

## Managing the queue

- Add more items any time; commit and push. Items are posted in order, one per day.
- `state.json` holds `next_index` and a history of what was posted. Edit `next_index` and push to skip ahead or replay.
- Each run is visible under the repo's **Actions** tab with full logs.

## Private repo

raw.githubusercontent.com links to a private repo require auth, so Instagram cannot fetch them. Either keep the repo public (the media is public on Instagram anyway) or host files on Cloudinary, S3, Cloudflare R2, Imgur, or Dropbox (`?dl=1`) and use `{ "url": "..." }` items.

## Running locally instead (optional)

The same script works on this PC: copy `.env.example` to `.env`, fill it in, then

```bash
python post_story.py --dry-run
```

and `install_task.ps1` registers a Windows Task Scheduler job at 13:00 (requires the PC to be on).

## Troubleshooting

- **"outside the 13:00-15:00 window"**: expected on 22 of the 24 hourly runs. Use Run workflow → force to post now.
- **"Already posted today"**: expected on the second run inside the window.
- **HTTP 400 image format / media unsupported**: use JPEG, 9:16; open the raw link in an incognito window to confirm it downloads the file.
- **OAuthException / code 190**: token expired or revoked. Generate a new one (step 1.5) and update the `IG_ACCESS_TOKEN` secret.
- **Workflow stopped running**: GitHub pauses scheduled workflows in repos with no activity for 60 days. Daily `state.json` commits keep it active; if the queue is exhausted for 60+ days, re-enable it under Actions.
- GitHub cron can run several minutes late at busy times; the 2-hour window absorbs that.
