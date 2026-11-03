# Deploy SkellyMotion — website and Windows downloads

This repo has **two independent delivery paths**:

- **Private web editor:** Railway Docker service; FFmpeg and local Whisper run on the server; owner-only HTTP Basic login over HTTPS. No public sign-ups or separate user accounts.
- **Windows portable download:** GitHub Actions builds a Windows `SkellyMotion.exe` folder (including the runtime and bundled FFmpeg). Actions artifacts now contain the program directly for **one extraction**. Tagged releases separately publish a standalone `SkellyMotion-Windows-x64.zip`.

## 1. Create and push the GitHub repository

1. This project already exists in the private repository `skellyruno/LYRICFORGE`. Keep that repository path for existing integrations. For a completely new fork only, create an empty GitHub repository.
2. Extract this archive. **Easiest on Windows:** double-click `PUBLISH-TO-GITHUB.bat` inside the extracted `LYRICFORGE-GitHub` folder and follow its instructions. It requires [Git for Windows](https://git-scm.com/download/win). Alternatively, open PowerShell in that folder (containing `server.py`) and run:

   ```powershell
   git init
   git branch -M main
   git add .
   git commit -m "Initial SkellyMotion website and Windows build"
   git remote add origin https://github.com/skellyruno/LYRICFORGE.git
   git push -u origin main
   ```

   Sign in using Git Credential Manager if prompted. Do not paste a token into chat or commit it.

3. Visit `https://github.com/skellyruno/LYRICFORGE/actions`. **Test app** runs on pushes. To create a Windows download, select **Build SkellyMotion Windows app → Run workflow** on `main`. GitHub may ask you to enable Actions. After success, download `SkellyMotion-Windows-x64` under **Artifacts** (artifacts expire after 14 days). Extract **once** to find `SkellyMotion.exe` and `_internal` side by side.

4. For a permanent public download, double-click `RELEASE-WINDOWS.bat`, enter a new tag such as `v1.0.0`, and follow the prompts. Or create and push a version tag manually (PowerShell):

   ```powershell
   git tag v1.0.0
   git push origin v1.0.0
   ```

   After the tagged Windows build passes, download from `https://github.com/skellyruno/LYRICFORGE/releases`. The workflow creates the Release and attaches `SkellyMotion-Windows-x64.zip` automatically. On later updates use a new tag such as `v1.0.1`, not an already-used tag.

   If GitHub Actions cannot create a release, check **Repo Settings > Actions > General > Workflow permissions > Read and write permissions**. Changes to settings are controlled by the repo owner. The workflow itself requests `contents: write`.

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
