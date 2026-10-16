# Optional local inference server for "Ask the wiki" (deploy/compose.llm.yml).
# Rootless: models live in a volume owned by the numeric user; no history, no telemetry.
ARG OLLAMA_IMAGE=ollama/ollama:0.34.4@sha256:8262851b2846b87c649eddf3e76beb270c52f4d1bc94559f47efde16b0841551
FROM ${OLLAMA_IMAGE}
RUN install -d -o 10001 -g 10001 -m 0750 /models
ENV OLLAMA_MODELS=/models \
    OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_NOHISTORY=1 \
    HOME=/tmp
USER 10001:10001
