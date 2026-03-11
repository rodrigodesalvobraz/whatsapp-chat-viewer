# Changelog

## 1.1.0 — 2026-03-10

### Features
- PDF descriptions: generate a one-paragraph summary of each PDF file using OpenAI API (`--describe-pdfs`)
- Image descriptions: generate a one-paragraph summary of each image using OpenAI vision API (`--describe-images`), useful for photos of documents
- Descriptions are displayed inline below the media (PDF link or image), matching the style of audio transcriptions
- Context-aware: the last 20 conversation messages are passed to the model so it can focus on the most relevant information
- Handles both text-based PDFs (text extraction) and scanned/image PDFs (vision API with page rendering)
- Descriptions are cached as `.txt` files next to each file — re-running skips already-described files
- Configurable models via `--pdf-model` and `--image-model` (both default to `gpt-4o`)

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
