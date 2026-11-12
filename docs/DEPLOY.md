# Deploy SkellyMotion — website and Windows downloads

This repo has **two independent delivery paths**:

- **Private web editor:** Railway Docker service; FFmpeg and local Whisper run on the server; owner-only HTTP Basic login over HTTPS. No public sign-ups or separate user accounts.
- **Windows portable download:** GitHub Actions builds a Windows `SkellyMotion.exe` folder (including the runtime and bundled FFmpeg). Actions artifacts now contain the program directly for **one extraction**. Tagged releases separately publish a standalone `SkellyMotion-Windows-x64.zip`.

## 1. Repository and Windows builds

SkellyMotion already lives in [skellyruno/LYRICFORGE](https://github.com/skellyruno/LYRICFORGE). **Do not initialize a new repository or force-push over the existing history.** Use the `main` branch for the current tested source.

1. To work on the source locally, install [Git for Windows](https://git-scm.com/download/win), then clone the existing repository:

   ```powershell
   git clone https://github.com/skellyruno/LYRICFORGE.git
   cd LYRICFORGE
   ```

   For an existing clone, run `git pull --ff-only origin main` when your working tree is clean. To contribute changes, use a separate branch and a pull request so Windows and Python tests run before merging.

2. For a downloadable Windows build, open [GitHub Actions](https://github.com/skellyruno/LYRICFORGE/actions), select **Build SkellyMotion Windows app**, and choose **Run workflow** on `main`. Automatic pushes still compile and test, but deliberately do not upload large artifacts. After a successful manual run, download `SkellyMotion-Windows-x64` from **Artifacts** (currently retained for one day), then extract it **once** to keep `SkellyMotion.exe` and `_internal` together.

   **Artifact storage:** GitHub can refuse uploads after exceeding its Actions artifact quota even when the build passes. Clear obsolete artifacts through GitHub's Actions UI or wait for usage recalculation; do not remove runtime files from the application to work around quota issues.

3. For a versioned public release, run `RELEASE-WINDOWS.bat` from a local repository clone and enter a **new** version tag (for example `v1.0.0`). Alternatively, push a version tag:

   ```powershell
   git tag v1.0.0
   git push origin v1.0.0
   ```

   A passing tagged Windows build publishes `SkellyMotion-Windows-x64.zip` under [GitHub Releases](https://github.com/skellyruno/LYRICFORGE/releases). Use a fresh tag for each release. If release publishing fails, check repository **Settings → Actions → General → Workflow permissions**; the workflow requests `contents: write`.

## 2. Publish your private online studio (Railway)

A basic landing page could run on GitHub Pages, but **the functioning app cannot**: it needs Python, FFmpeg and a speech recognition model. Railway can run it from the repo's Dockerfile.

1. Sign up/log into <https://railway.com/new>, select **Deploy from GitHub repo**, authorize this repository and choose `skellyruno/LYRICFORGE`.
2. Railway detects `Dockerfile` at the repository root. Let it build (cloud inference needs CPU and RAM; the first run also downloads a Whisper model).
3. In your Railway service **Variables**, set:

   | Variable | Example / explanation |
   |---|---|
   | `LYRICFORGE_REQUIRE_AUTH` | `1` (enabled by default in Docker) |
   | `LYRICFORGE_AUTH_USER` | `owner` (choose your own) |
   | `LYRICFORGE_AUTH_PASSWORD` | **Generate a random password, 16+ characters**; never commit it |
   | `LYRICFORGE_DATA` | `/data/workspace` (already default in Docker) |
   | `HF_HOME` | `/data/model-cache` (already default in Docker) |
   | `WHISPER_MODEL` | `base` for lighter CPU use; `small` is default but uses more space and compute |

   Do NOT copy `.env.example` into the repository as `.env` with a real password. Without valid credentials, the website returns an error instead of exposing your songs.
4. Add a **persistent Railway volume** to the service and mount it at **`/data`** (important!). This saves songs, corrected lyrics, custom backgrounds, exports and cached speech models across redeploys. The container's root entrypoint makes the mounted volume writable and then starts the app as a non-root user. Choose enough space for several video renders **plus** the recognition model. The Railway free/trial volume quota may be too small for regular use; paid hosting can incur ongoing costs.
5. In service **Settings > Networking > Public Networking**, click **Generate Domain**. Open the generated `https://...up.railway.app` address and sign in with your owner credentials. Wait for the first AI model download when transcribing a song.
6. If you want `lyrics.skellyr.uno`, select **+ Custom Domain** in the same Networking section and enter `lyrics.skellyr.uno`. In your domain registrar's DNS settings, add the **exact CNAME and ownership TXT records Railway provides** (do not guess the values). Wait for verification and HTTPS provisioning.
7. Only **one server instance** should run for this MVP. It uses in-process job status, filesystem projects and no per-user isolation. Restrict access to yourself; it is **not yet safe for public multi-user accounts**.

**Cost / resources:** Hosting bills separately from GitHub. Video rendering is CPU intensive and uploads/downloads consume bandwidth. Railway Free/Trial persistent volumes are limited; compare current plan prices and quotas before launching. A small VPS (including your trial VPS) can also host this Dockerfile, but requires server setup, HTTPS reverse proxy and backups.

## 3. Using the Windows download

1. Download the Windows x64 ZIP from GitHub Actions or Releases.
2. From **GitHub Actions**, extract the artifact ZIP **once** into a new folder: `SkellyMotion.exe` and `_internal` should be next to each other. From a **GitHub Release**, extract its ZIP once and open the contained `SkellyMotion` folder. Do not move only the `.exe` out of the folder; it needs the adjacent `_internal` dependencies.
3. Double-click `SkellyMotion.exe` (Windows Defender/SmartScreen may warn about unsigned downloads).
4. The editor opens in its own SkellyMotion window using Microsoft Edge WebView2. It connects to a private localhost server. It reuses the original downloaded AI model located at `%LOCALAPPDATA%\LyricForge\models`.
5. Your projects save under `%LOCALAPPDATA%\LyricForge\workspace`. Exported MP4 files are accessible from the editor. Closing the SkellyMotion window shuts down the local server.

The GitHub-generated EXE is **not code-signed** and has not yet been verified on a real Windows machine. After the workflow completes, test import → transcription → correction → video export on your own PC. If you want a signed Windows installer and auto-updater, that is a future feature.

## 4. Local checks

From the project folder, with Python 3.11/3.12 and FFmpeg installed:

```bash
python -m pip install -r requirements.txt pytest httpx
python -m pytest tests -q
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

For Docker, after installing Docker:

```bash
docker build -t lyricforge .
docker run --rm -p 127.0.0.1:8000:8000 -v lyricforge_data:/data \
  -e LYRICFORGE_AUTH_USER=owner \
  -e LYRICFORGE_AUTH_PASSWORD=replace-with-a-long-password \
  lyricforge
```

Do not expose port 8000 directly without TLS; the owner credentials use HTTP Basic and must only travel over HTTPS on the internet.

## Troubleshooting

- **Windows release missing:** Actions run failed? Open the **Build Windows portable app** job and read the failed step. Check workflow permissions before retrying.
- **Export fails:** FFmpeg must have `ass` filter (libass) and `libx264` encoder; the Windows workflow validates the subtitle filter.
- **Website cannot save projects:** Check that the Railway volume is mounted at `/data` and the container has enough disk space.
- **Website asks for a password:** Intended. Use your Railway `LYRICFORGE_AUTH_USER` and `LYRICFORGE_AUTH_PASSWORD` values. A wrong or missing password is denied.
- **Cloud transcription slow:** A CPU server can take longer than your PC. Set `WHISPER_MODEL=base` for a smaller model, or use more CPU/RAM.
- **Browser says disconnected:** Look at the Railway deployment logs. Restarting the backend loses in-progress job status; saved project files remain on the volume.
