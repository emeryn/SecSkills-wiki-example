# Ask the wiki (language model)

**Settings > Language model** connects an inference server speaking the Ollama API. The bundled
option is `deploy/compose.llm.yml`: Ollama on an internal network, port never published.

1. `docker compose -f docker-compose.yml -f deploy/compose.llm.yml up -d`
2. Install models (next section).
3. **Security > Allowed private networks**: add `172.31.250.0/24`.
4. **Language model**: URL `http://ollama:11434`, chat and embedding models, then save.
5. **Test connection**. The worker indexes every page in the background.

## Models

- With internet access for a moment: add `-f deploy/compose.llm-pull.yml` to the `up` command,
  run `docker compose -f docker-compose.yml -f deploy/compose.llm.yml exec ollama ollama pull <model>`,
  then start again without that file.
- Air-gapped: copy a GGUF file and a `Modelfile` (`FROM ./model.gguf`) into the container with
  `docker compose cp`, verify its SHA-256 against your internal repository, then
  `ollama create <name> -f Modelfile`.
- Saving the settings approves the chosen models: their digest is pinned. If a model changes on
  the server, questions are refused until an administrator saves the settings again.
- Only GGUF and safetensors models are accepted.

## Security

- `https` everywhere, or `http` only to an allowlisted private network. Internal CA, bearer
  token and HTTPS proxy are supported; certificates are always verified.
- Answers use only the pages the asker can read: the permission filter is part of the search.
- Page content is passed to the model as quoted data, never as instructions; the model is given
  no tools and cannot act. Answers are shown through the same sanitizer as pages: no HTML, no
  remote images.
- **Questions per minute** and **daily tokens** limit each user. Questions and answers are not
  logged unless **Log questions and answers** is on.
- **System prompt** (below the settings): each save is a version; **Reset to default** restores
  the factory text and keeps the history.
- Changing the embedding model re-indexes every page. Backups do not contain embeddings: they
  are rebuilt after a restore.
