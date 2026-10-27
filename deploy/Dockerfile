# A scheduled, unattended Customer Pulse run for one profile (see setup/schedule.md).
# Build from the repository root: docker build -f deploy/Dockerfile --build-arg PROFILE=<key> .
# The image copies only what a run needs: the engine, the run skill and that one profile. setup/, .env and every other
# profile are never copied, so no layer holds them and the agent has no instructions for changing its own reach.
# Tools are auto-approved (--yolo) because nobody is there to approve them; the boundary is this container (not root,
# read only except runs/), the job's least-privilege identity, and the send gate, which runs after the agent finishes.
FROM node:20-bookworm-slim
ARG PROFILE
RUN test -n "$PROFILE" && apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/* \
    && npm install -g @google/gemini-cli
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements.txt
COPY engine engine
COPY pulse pulse
COPY profiles/${PROFILE} profiles/${PROFILE}
RUN mkdir runs && chown node runs
ENV PULSE_UNATTENDED=1 PROFILE=$PROFILE
USER node
CMD gemini --yolo -p "Run the Customer Pulse for profile ${PROFILE}, following pulse/SKILL.md. This is a scheduled run: do step 3 including the verifier, then stop; the job sends it." \
    && .venv/bin/python3 engine/steps/send.py "${PROFILE}"
