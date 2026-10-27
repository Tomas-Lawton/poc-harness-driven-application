# Deploying a scheduled run

A scheduled run starts a headless harness that follows `pulse/SKILL.md` for the profile, then runs `send.py`. You deploy it, confirming each access change with the user. Trigger it once by hand and check the result with the user before leaving it on.

## On Google Cloud

1. **Project:** ask for the project and region (default the region of any warehouse connection). Enable Cloud Run, Cloud Scheduler, Secret Manager, Artifact Registry and Vertex AI.
2. **Identity:** create one service account for this profile, `pulse-<key>@<project>.iam.gserviceaccount.com`, with only:
   - Vertex AI User, to run the model
   - Secret Manager Secret Accessor on this profile's secrets

   Nothing else; never a broader role.
3. **Secrets:** put each value from `.env` that the profile uses (email password, service keys, a warehouse sign-in) in Secret Manager, one secret each. A warehouse connection then reads as the person who signed in; tell the user.
4. **Image and job:** from the repository root, build the image with `docker build -f deploy/Dockerfile --build-arg PROFILE=<key> .` (the root is the build context). It copies only the engine, the run skill and that profile (never `setup/`, `.env` or other profiles); the profile must not contain secrets. Push it to Artifact Registry. Create a Cloud Run job that runs as the service account, with the secrets as environment variables and Gemini CLI's settings for Vertex AI (`GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`).
5. **Runs:** create a Cloud Storage bucket for this profile's runs (never public), give the service account Storage Object Admin on that bucket only, and mount it on the job at `/app/runs`. Every run stays there as an audit trail.
6. **Scheduler:** create a Cloud Scheduler job in the user's timezone that runs the Cloud Run job on the schedule.
7. **Test:** run the job once by hand and read its logs with the user; every step and the send gate should pass. Only then enable the scheduler. To pause, disable the scheduler job and set `schedule` back to `null`.

## Elsewhere

Any scheduler that can start a headless harness on a machine with the project (cron, another cloud's job runner) works, with the same rules: the run skill only, a read-only project except `runs/`, a least-privilege identity, and secrets outside the project.
