# KitJarvis

A local-first Windows AI voice assistant fork of [isair/jarvis](https://github.com/isair/jarvis), focused on low-latency local operation, deterministic tool routing, privacy, and expanding Jarvis into a full personal assistant.

> **Current development branch:** `kitniji/fast-pipeline`
>
> KitJarvis is actively customized for Windows and local Ollama models. It is not an official release of the upstream Jarvis project.

## What This Fork Changes

- **GPT-OSS 20B** as the primary reasoning/chat model.
- **Gemma 4 e2b** as the fast intent judge and tool router.
- Faster explicit wake-word handling while preserving hot-window follow-up behavior.
- Deterministic no-tool routing for literal-response and stable-knowledge requests.
- Deterministic weather routing and single-weather planner bypass.
- Native **Windows screenshot capture + OCR** support.
- Deterministic screenshot routing, planner bypass, and direct execution.
- Failed-tool retry protection and screenshot carryover guards.
- Reduced optional orchestration passes for lower local latency.
- Upstream automatic updates disabled so a custom build cannot overwrite itself with an official `isair/jarvis` build.
- Tested packaged Windows desktop/tray build using the existing Jarvis UI.

## Current Local Stack

- **Chat:** `gpt-oss:20b`
- **Fast router / intent:** `gemma4:e2b`
- **Embeddings:** `nomic-embed-text`
- **Speech-to-text:** Faster-Whisper `tiny` on CUDA
- **Text-to-speech:** Piper
- **Runtime:** Ollama + local Windows desktop app

## Roadmap

Planned work includes deterministic time/date tools, reminders and task automation, Obsidian integration, browser/computer control, email/calendar integration, system tools, gaming mode, and a dedicated screenshot-to-vision-model pipeline.

## Privacy / Security

The goal of this fork is to keep core assistant behavior local wherever practical. Optional tools such as web search, MCP servers, browser automation, email, calendar, or other external services may communicate outside the machine when explicitly configured.

Automatic upstream application updates are intentionally disabled in the custom build. See [`SECURITY.md`](SECURITY.md) for the project security policy.

### Protect credentials before contributing

Install Gitleaks 8.30.1, then run
`./scripts/install_secret_hooks.ps1 -GitleaksPath C:/path/to/gitleaks.exe` once
per clone. Pre-commit checks staged content; pre-push checks every proposed ref
before the existing test hook. `SKIP_TESTS=1` never skips secret protection.
Use `.env.example` for placeholders and keep real configuration outside Git.
See [credential protection setup and incident response](SECURITY.md#repository-credential-protection).


## Upstream Project

KitJarvis is based on the open-source [isair/jarvis](https://github.com/isair/jarvis) project. Original architecture, UI, and substantial portions of the codebase come from that project; this fork adds Windows-focused local optimizations and custom assistant behavior.

For the original project documentation, features, setup instructions, and upstream development history, visit [isair/jarvis](https://github.com/isair/jarvis).
