# Changelog

## 1.0.0 — 2025-06-21

Initial public release.

### Features
- Generate WhatsApp-style HTML from exported chat text files
- Support for images, videos, audio, PDFs, and stickers
- Exclusive audio playback (playing one pauses the others)
- Optional audio transcription via OpenAI STT API (`--transcribe`)
- Transcriptions displayed inline below audio players
- Transcription caching as `.original.txt` files for idempotent re-runs
- Limit transcription to first N audios (`--transcribe-only-x-audios`)
- Automatic language detection from chat text for improved transcription accuracy
- Context-aware transcription correction via LLM (`--correct`)
- Interactive correction review mode (`--correct-interactive`) with diff highlighting
- Configurable STT and LLM models (`--stt-model`, `--llm-model`)
- Right-align your own messages with `--me`
- Base directory shortcut with `--dir`
