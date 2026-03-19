#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
from html import escape
from datetime import datetime

AUDIO_EXTS = ("opus", "ogg", "mp3", "wav", "m4a")
IMAGE_EXTS = ("jpg", "jpeg", "png", "gif", "webp")

_LANG_NAMES = {
    "pt": "Portuguese", "en": "English", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian",
}

SUPPORTED_LANGS = set(_LANG_NAMES.keys())

# E.g.: "20/06/2025, 23:29 - John: Message"
MESSAGE_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2}(?:\s?[APMapm]{2})?)\s+-\s+(.*?):\s+(.*)"
)

# E.g.: "20/06/2025, 23:29 - Messages and calls are end-to-end encrypted."
SYSTEM_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2}(?:\s?[APMapm]{2})?)\s+-\s+(.*)"
)

# Media/file extensions we handle
MEDIA_EXTS = (
    "jpg", "jpeg", "png", "gif",
    "mp4", "mov", "mkv", "webm",
    "opus", "ogg", "mp3", "wav", "m4a",
    "webp",
    "pdf",
    "was",
)


def parse_chat(chat_path):
    messages = []
    current = None

    with open(chat_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            m = MESSAGE_RE.match(line)
            if m:
                date_str, time_str, sender, text = m.groups()
                current = {
                    "date": date_str.strip(),
                    "time": time_str.strip(),
                    "sender": sender.strip(),
                    "text": text,
                }
                messages.append(current)
            else:
                s = SYSTEM_RE.match(line)
                if s:
                    date_str, time_str, text = s.groups()
                    current = {
                        "date": date_str.strip(),
                        "time": time_str.strip(),
                        "sender": "",
                        "text": text,
                    }
                    messages.append(current)
                elif current is not None:
                    current["text"] += "\n" + line
                else:
                    current = {
                        "date": "",
                        "time": "",
                        "sender": "",
                        "text": line,
                    }
                    messages.append(current)

    return messages


def classify_media(filename):
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in ("jpg", "jpeg", "png", "gif", "webp"):
        return "image"
    if ext in ("mp4", "mov", "mkv", "webm"):
        return "video"
    if ext in ("opus", "ogg", "mp3", "wav", "m4a"):
        return "audio"
    if ext == "pdf":
        return "pdf"
    return "file"


def build_media_index(media_dir, output_html_path):
    """
    Build a map: lowercase_filename -> path_relative_to_output_HTML
    """
    index = {}
    output_dir = os.path.dirname(os.path.abspath(output_html_path)) or "."

    for root, _, files in os.walk(media_dir):
        for name in files:
            if "." not in name:
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            if ext not in MEDIA_EXTS:
                continue
            key = name.lower()
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, output_dir).replace("\\", "/")
            index[key] = rel_path

    return index


def build_sender_classes(messages, me_name=None):
    """
    Assign 'sent' (right) or 'received' (left) to each sender.
    """
    sender_classes = {}

    if me_name:
        for msg in messages:
            s = msg["sender"]
            if not s:
                continue
            if s == me_name:
                sender_classes[s] = "sent"
            elif s not in sender_classes:
                sender_classes[s] = "received"
        return sender_classes

    first = None
    second = None
    for msg in messages:
        s = msg["sender"]
        if not s:
            continue
        if first is None:
            first = s
            sender_classes[s] = "received"
        elif second is None and s != first:
            second = s
            sender_classes[s] = "sent"
        elif s not in sender_classes:
            sender_classes[s] = "received"

    return sender_classes


def detect_language_from_text(text, fallback="pt"):
    from langdetect import detect

    if not text:
        return fallback

    sample = " ".join(
        chunk.strip()
        for chunk in re.split(r"\s+", text)
        if chunk.strip()
    )
    if len(sample) < 20:
        return fallback

    try:
        detected = detect(sample)
    except Exception:
        return fallback

    return detected if detected in SUPPORTED_LANGS else fallback


def detect_language(messages):
    texts = []
    for msg in messages:
        t = (msg["text"] or "").strip()
        if len(t) >= 20:
            texts.append(t)
        if len(" ".join(texts)) >= 4000:
            break

    if not texts:
        return "pt"

    return detect_language_from_text("\n".join(texts), fallback="pt")


def transcribe(audio_path, model, language, client):
    # WhatsApp .opus files are OGG-wrapped; send with .ogg extension for API compatibility
    filename = os.path.basename(audio_path)
    if filename.lower().endswith(".opus"):
        filename = filename[:-5] + ".ogg"
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=model,
            file=(filename, f),
            language=language,
        )
    return result.text


def transcribe_audios(messages, media_dir, media_index, stt_model, language, limit):
    from openai import OpenAI
    client = OpenAI()
    output_dir = os.path.dirname(os.path.abspath(
        os.path.join(media_dir, "output.html")
    )) or "."
    count = 0
    transcribed = 0
    for msg in messages:
        if limit is not None and count >= limit:
            break
        text = (msg["text"] or "").lower()
        for fname_lower, rel_path in media_index.items():
            if fname_lower not in text:
                continue
            ext = fname_lower.rsplit(".", 1)[-1]
            if ext not in AUDIO_EXTS:
                continue
            full_path = os.path.normpath(os.path.join(output_dir, rel_path))
            if not os.path.isfile(full_path):
                continue
            count += 1
            if limit is not None and count > limit:
                break
            txt_path = full_path + ".original.txt"
            if os.path.exists(txt_path):
                continue
            print(f"  Transcribing ({count}): {os.path.basename(full_path)}...")
            try:
                raw = transcribe(full_path, stt_model, language, client)
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(raw)
                transcribed += 1
            except Exception as e:
                print(f"    ERROR transcribing {os.path.basename(full_path)}: {e}")
    print(f"{transcribed} audios transcribed ({count} considered).")


def correct_transcription(raw_text, context, model, client):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a transcription corrector. You receive an automatic "
                    "speech-to-text transcription and the surrounding conversation "
                    "context. Your ONLY job is to fix words that the speech-to-text "
                    "model clearly misheard — for example, a word that sounds similar "
                    "but makes no sense in the conversation context. "
                    "NEVER change grammar, number agreement, verb conjugation, word "
                    "order, punctuation, slang, or informal language. NEVER remove "
                    "or add words. NEVER improve text quality. The speaker may speak "
                    "with grammatical errors — preserve them exactly. "
                    "If the transcription seems correct, return it unchanged. "
                    "Output ONLY the transcription, nothing else."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Conversation context (recent messages before this audio):\n"
                    f"---\n{context}\n---\n\n"
                    f"Transcription to correct:\n{raw_text}"
                ),
            },
        ],
    )
    return response.choices[0].message.content.strip()


def _highlight_diffs(original, corrected):
    import difflib
    orig_words = original.split()
    corr_words = corrected.split()
    sm = difflib.SequenceMatcher(None, orig_words, corr_words)
    orig_parts = []
    corr_parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            orig_parts.append(" ".join(orig_words[i1:i2]))
            corr_parts.append(" ".join(corr_words[j1:j2]))
        else:
            old = " ".join(orig_words[i1:i2])
            new = " ".join(corr_words[j1:j2])
            if old:
                orig_parts.append(f"\033[1m{old}\033[0m")
            if new:
                corr_parts.append(f"\033[1m{new}\033[0m")
    return " ".join(orig_parts), " ".join(corr_parts)


def correct_transcriptions(messages, media_dir, media_index, llm_model, limit,
                           interactive=False):
    from openai import OpenAI
    client = OpenAI()
    output_dir = os.path.dirname(os.path.abspath(
        os.path.join(media_dir, "output.html")
    )) or "."
    context_lines = []
    count = 0
    corrected = 0
    for msg in messages:
        if limit is not None and count >= limit:
            break
        text = (msg["text"] or "").lower()
        sender = msg["sender"] or ""
        found_audio = False
        for fname_lower, rel_path in media_index.items():
            if fname_lower not in text:
                continue
            ext = fname_lower.rsplit(".", 1)[-1]
            if ext not in AUDIO_EXTS:
                continue
            full_path = os.path.normpath(os.path.join(output_dir, rel_path))
            if not os.path.isfile(full_path):
                continue
            count += 1
            if limit is not None and count > limit:
                break
            found_audio = True
            corrected_path = full_path + ".txt"
            if os.path.isfile(corrected_path):
                continue
            original_path = full_path + ".original.txt"
            if not os.path.isfile(original_path):
                continue
            with open(original_path, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
            if not raw_text:
                continue
            context = "\n".join(context_lines[-20:])
            print(f"  Correcting ({count}): {os.path.basename(full_path)}...")
            try:
                fixed = correct_transcription(raw_text, context, llm_model, client)
                if interactive and fixed != raw_text:
                    orig_hl, corr_hl = _highlight_diffs(raw_text, fixed)
                    print(f"    Original:  {orig_hl}")
                    print(f"    Corrected: {corr_hl}")
                    choice = input("    Accept? [y]es / [N]o / [e]dit: ").strip().lower()
                    if choice == "y":
                        pass
                    elif choice == "e":
                        try:
                            from prompt_toolkit import prompt as pt_prompt
                            fixed = pt_prompt("    Edit: ", default=fixed).strip()
                        except ImportError:
                            fixed = input("    Edit: ").strip() or fixed
                    else:
                        print("    Skipped.")
                        context_lines.append(f"{sender}: [audio] {raw_text}")
                        continue
                with open(corrected_path, "w", encoding="utf-8") as f:
                    f.write(fixed)
                corrected += 1
            except Exception as e:
                print(f"    ERROR correcting {os.path.basename(full_path)}: {e}")
            # Add the transcription to context so subsequent audios benefit
            context_lines.append(f"{sender}: [audio] {raw_text}")
        if not found_audio:
            # Regular text message — add to context
            msg_text = msg["text"] or ""
            if msg_text.strip():
                context_lines.append(f"{sender}: {msg_text}")
    print(f"{corrected} transcriptions corrected ({count} considered).")


def describe_pdf(pdf_path, context, pdf_model, client, language="en"):
    """Generate a one-paragraph description of a PDF using LLM.

    Tries text extraction first (fast, cheap). Falls back to vision (page
    images) for scanned or image-only PDFs.
    """
    import fitz  # pymupdf
    import base64

    doc = fitz.open(pdf_path)

    full_text = ""
    for page in doc:
        full_text += page.get_text()

    if len(full_text.strip()) > 100:
        detected_language = detect_language_from_text(full_text, fallback=language)
        lang_name = _LANG_NAMES.get(detected_language, detected_language)
        system_prompt = (
            "You are a document analyst. You receive a document and recent conversation "
            "context. Write a single paragraph (3-5 sentences) summarizing the document's "
            "key information, focusing on what is most relevant given the conversation "
            f"context. Be factual and concise. Always write in {lang_name}. "
            "Output only the paragraph, nothing else."
        )
        # Text-based PDF: send extracted text
        response = client.chat.completions.create(
            model=pdf_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Recent conversation context:\n---\n{context}\n---\n\n"
                        f"Document content:\n{full_text[:4000]}"
                    ),
                },
            ],
        )
    else:
        fallback_lang_name = _LANG_NAMES.get(language, language)
        system_prompt = (
            "You are a document analyst. You receive a document and recent conversation "
            "context. First infer the predominant language of the document from any visible "
            "text. If the document language is unclear, fall back to the conversation language. "
            "Write a single paragraph (3-5 sentences) summarizing the document's key "
            "information, focusing on what is most relevant given the conversation context. "
            f"If fallback is needed, use {fallback_lang_name}. Be factual and concise. "
            "Output only the paragraph, nothing else."
        )
        # Scanned/image PDF: render pages and use vision
        content = []
        for page_num in range(min(len(doc), 4)):
            page = doc[page_num]
            # Scale so the longest dimension is at most 1500px to stay within API limits
            rect = page.rect
            max_dim = max(rect.width, rect.height)
            scale = min(2.0, 1500 / max_dim) if max_dim > 0 else 1.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img_b64 = base64.b64encode(pix.tobytes("png")).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
            })
        content.append({
            "type": "text",
            "text": (
                f"Recent conversation context:\n---\n{context}\n---\n\n"
                "Describe this document in one paragraph."
            ),
        })
        response = client.chat.completions.create(
            model=pdf_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        )

    doc.close()
    return response.choices[0].message.content.strip()


def describe_pdfs(messages, media_dir, media_index, pdf_model, limit, language="en"):
    """Generate and cache one-paragraph descriptions for all PDF files in the chat."""
    from openai import OpenAI
    client = OpenAI()
    output_dir = os.path.dirname(os.path.abspath(
        os.path.join(media_dir, "output.html")
    )) or "."
    context_lines = []
    count = 0
    described = 0
    for msg in messages:
        if limit is not None and count >= limit:
            break
        text = (msg["text"] or "").lower()
        sender = msg["sender"] or ""
        found_pdf = False
        for fname_lower, rel_path in media_index.items():
            if fname_lower not in text:
                continue
            if fname_lower.rsplit(".", 1)[-1] != "pdf":
                continue
            full_path = os.path.normpath(os.path.join(output_dir, rel_path))
            if not os.path.isfile(full_path):
                continue
            count += 1
            if limit is not None and count > limit:
                break
            found_pdf = True
            desc_path = full_path + ".txt"
            if os.path.isfile(desc_path):
                continue
            context = "\n".join(context_lines[-20:])
            print(f"  Describing ({count}): {os.path.basename(full_path)}...")
            try:
                desc = describe_pdf(full_path, context, pdf_model, client, language)
                with open(desc_path, "w", encoding="utf-8") as f:
                    f.write(desc)
                described += 1
            except Exception as e:
                print(f"    ERROR describing {os.path.basename(full_path)}: {e}")
        if not found_pdf:
            msg_text = msg["text"] or ""
            if msg_text.strip():
                context_lines.append(f"{sender}: {msg_text}")
    print(f"{described} PDFs described ({count} considered).")


def describe_image(image_path, context, image_model, client, language="en"):
    """Generate a one-paragraph description of an image using vision LLM."""
    import base64

    ext = image_path.lower().rsplit(".", 1)[-1]
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    lang_name = _LANG_NAMES.get(language, language)
    response = client.chat.completions.create(
        model=image_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an image analyst. You receive an image and recent conversation "
                    "context. Write a single paragraph (3-5 sentences) describing the image's "
                    "key content, focusing on what is most relevant given the conversation "
                    "context. If the image contains a document, form, or text, first infer the "
                    "predominant language from the visible text and write in that language. If "
                    "the image language is unclear or there is no visible text, fall back to the "
                    f"conversation language, which is {lang_name}. Extract the most important "
                    "information from the image when relevant. Be factual and concise. "
                    "Output only the paragraph, nothing else."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Recent conversation context:\n---\n{context}\n---\n\n"
                            "Describe this image in one paragraph."
                        ),
                    },
                ],
            },
        ],
    )
    return response.choices[0].message.content.strip()


def describe_images(messages, media_dir, media_index, image_model, limit, language="en"):
    """Generate and cache one-paragraph descriptions for all images in the chat."""
    from openai import OpenAI
    client = OpenAI()
    output_dir = os.path.dirname(os.path.abspath(
        os.path.join(media_dir, "output.html")
    )) or "."
    context_lines = []
    count = 0
    described = 0
    for msg in messages:
        if limit is not None and count >= limit:
            break
        text = (msg["text"] or "").lower()
        sender = msg["sender"] or ""
        found_image = False
        for fname_lower, rel_path in media_index.items():
            if fname_lower not in text:
                continue
            if fname_lower.rsplit(".", 1)[-1] not in IMAGE_EXTS:
                continue
            full_path = os.path.normpath(os.path.join(output_dir, rel_path))
            if not os.path.isfile(full_path):
                continue
            count += 1
            if limit is not None and count > limit:
                break
            found_image = True
            desc_path = full_path + ".txt"
            if os.path.isfile(desc_path):
                continue
            context = "\n".join(context_lines[-20:])
            print(f"  Describing ({count}): {os.path.basename(full_path)}...")
            try:
                desc = describe_image(full_path, context, image_model, client, language)
                with open(desc_path, "w", encoding="utf-8") as f:
                    f.write(desc)
                described += 1
            except Exception as e:
                print(f"    ERROR describing {os.path.basename(full_path)}: {e}")
        if not found_image:
            msg_text = msg["text"] or ""
            if msg_text.strip():
                context_lines.append(f"{sender}: {msg_text}")
    print(f"{described} images described ({count} considered).")


def load_transcriptions(media_dir, media_index, output_html_path):
    output_dir = os.path.dirname(os.path.abspath(output_html_path)) or "."
    transcriptions = {}

    for fname_lower, rel_path in media_index.items():
        ext = fname_lower.rsplit(".", 1)[-1]

        if ext in AUDIO_EXTS:
            full_path = os.path.normpath(os.path.join(output_dir, rel_path))
            # Prefer corrected (.txt) over original (.original.txt)
            corrected = full_path + ".txt"
            original = full_path + ".original.txt"
            txt_path = corrected if os.path.isfile(corrected) else original
            if os.path.isfile(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    transcriptions[fname_lower] = f.read().strip()

        elif ext == "pdf" or ext in IMAGE_EXTS:
            full_path = os.path.normpath(os.path.join(output_dir, rel_path))
            desc_path = full_path + ".txt"
            if os.path.isfile(desc_path):
                with open(desc_path, "r", encoding="utf-8") as f:
                    transcriptions[fname_lower] = f.read().strip()

    return transcriptions


def build_message_ids(messages):
    """
    Build stable DOM ids for each message based on a content hash.

    Duplicate messages with the exact same canonical content get a numeric suffix
    to keep ids unique within the document.
    """
    ids = []
    seen = {}

    for msg in messages:
        canonical = "\n".join([
            msg.get("date", ""),
            msg.get("time", ""),
            msg.get("sender", ""),
            msg.get("text", ""),
        ])
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
        seen[digest] = seen.get(digest, 0) + 1

        message_id = f"msg-{digest}"
        if seen[digest] > 1:
            message_id = f"{message_id}-{seen[digest]}"

        ids.append(message_id)

    return ids


def render_message_html(msg, message_id, media_index, sender_classes, transcriptions=None):
    sender = msg["sender"]
    sender_class = sender_classes.get(sender, "received")
    text = msg["text"] or ""

    lower_text = text.lower()
    occurrences = []

    # Find all media filenames that appear in the message text
    for fname_lower in media_index.keys():
        start = 0
        while True:
            idx = lower_text.find(fname_lower, start)
            if idx == -1:
                break
            occurrences.append((idx, idx + len(fname_lower), fname_lower))
            start = idx + len(fname_lower)

    if not occurrences:
        # No media in this message
        content_html = f"<span>{escape(text)}</span>"
    else:
        occurrences.sort(key=lambda x: x[0])
        parts = []
        cur = 0
        for start, end, fname_lower in occurrences:
            if start > cur:
                before = text[cur:start]
                if before:
                    parts.append(f"<span>{escape(before)}</span>")

            filename = text[start:end]  # preserve original capitalization
            rel_path = media_index[fname_lower]
            media_type = classify_media(filename)
            src = escape(rel_path)

            if media_type == "image":
                desc_html = ""
                if transcriptions and fname_lower in transcriptions:
                    desc_html = f'<div class="transcription">{escape(transcriptions[fname_lower])}</div>'
                parts.append(
                    f'<div class="media">'
                    f'  <a href="{src}" target="_blank">'
                    f'    <img src="{src}" loading="lazy" />'
                    f'  </a>'
                    f'{desc_html}'
                    f'</div>'
                )
            elif media_type == "video":
                parts.append(
                    f'<div class="media"><video controls preload="metadata">'
                    f'<source src="{src}">'
                    f'Your browser does not support video.</video></div>'
                )
            elif media_type == "audio":
                transcription_html = ""
                if transcriptions and fname_lower in transcriptions:
                    transcription_html = f'<div class="transcription">{escape(transcriptions[fname_lower])}</div>'
                parts.append(
                    f'<div class="media audio-wrap"><audio controls preload="metadata">'
                    f'<source src="{src}">'
                    f'Your browser does not support audio.</audio>'
                    f'{transcription_html}</div>'
                )
            elif media_type == "pdf":
                desc_html = ""
                if transcriptions and fname_lower in transcriptions:
                    desc_html = f'<div class="transcription">{escape(transcriptions[fname_lower])}</div>'
                parts.append(
                    f'<div class="media pdf">'
                    f'<a href="{src}" target="_blank">'
                    f'  <div class="pdf-thumb">📄</div>'
                    f'  <div class="pdf-name">{escape(filename)}</div>'
                    f'</a>'
                    f'{desc_html}'
                    f'</div>'
                )
            else:
                parts.append(
                    f'<div class="media file">'
                    f'  <a href="{src}" download>'
                    f'    📦 {escape(filename)}'
                    f'  </a>'
                    f'</div>'
                )

            cur = end

        if cur < len(text):
            after = text[cur:]

            # Remove typical WhatsApp attachment phrases
            after = after.replace("(arquivo anexado)", "").strip()
            after = after.replace("(file attached)", "").strip()

            if after:
                parts.append(f"<span>{escape(after)}</span>")

        content_html = "".join(parts)

    timestamp = f"{escape(msg['date'])} {escape(msg['time'])}".strip()

    return f"""
    <div class="message {sender_class}" id="{message_id}">
        <div class="bubble">
            <div class="meta">
                <span class="sender">{escape(sender) if sender else "System"}</span>
                <span class="meta-right">
                    <span class="time">{timestamp}</span>
                    <a class="permalink" href="#{message_id}" title="Link to this message">#</a>
                </span>
            </div>
            <div class="text">
                {content_html}
            </div>
        </div>
    </div>
    """


def generate_html(messages, media_index, output_path, me_name=None, transcriptions=None):
    sender_classes = build_sender_classes(messages, me_name=me_name)
    message_ids = build_message_ids(messages)

    css = """
    body {
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #ece5dd;
    }
    .chat-container {
        max-width: 800px;
        margin: 0 auto;
        min-height: 100vh;
    }
    .chat-header {
        background: #075E54;
        color: white;
        padding: 12px 16px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 8px;
        position: sticky;
        top: 0;
        z-index: 10;
    }
    .chat-header .title {
        font-size: 16px;
    }
    .chat-body {
        padding: 10px;
        background: #ece5dd;
    }
    .message {
        display: flex;
        margin-bottom: 6px;
        scroll-margin-top: 72px;
    }
    .message.sent {
        justify-content: flex-end;
    }
    .message.received {
        justify-content: flex-start;
    }
    .bubble {
        max-width: 70%;
        padding: 6px 8px;
        border-radius: 8px;
        font-size: 14px;
        position: relative;
        box-shadow: 0 1px 0.5px rgba(0,0,0,0.13);
        background: #ffffff;
    }
    .message.sent .bubble {
        background: #dcf8c6;
    }
    .meta {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 11px;
        color: #667781;
        margin-bottom: 4px;
    }
    .meta-right {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .permalink {
        color: inherit;
        text-decoration: none;
        opacity: 0.45;
        font-weight: 600;
    }
    .message:hover .permalink,
    .message:target .permalink {
        opacity: 1;
    }
    .text span {
        white-space: pre-wrap;
        word-wrap: break-word;
    }
    .message:target .bubble {
        outline: 2px solid rgba(7, 94, 84, 0.35);
        box-shadow: 0 0 0 4px rgba(7, 94, 84, 0.12);
    }
    .media {
        margin-top: 4px;
        margin-bottom: 4px;
    }
    .media img {
        max-width: 260px;
        max-height: 260px;
        border-radius: 6px;
        display: block;
    }
    .media video,
    .media audio {
        width: 260px;
        max-width: 100%;
        outline: none;
    }
    .transcription {
        font-size: 13px;
        font-style: italic;
        color: #667781;
        margin-top: 4px;
        white-space: pre-wrap;
        word-wrap: break-word;
    }
    .media.pdf a {
        display: flex;
        align-items: center;
        gap: 8px;
        text-decoration: none;
        color: inherit;
    }
    .pdf-thumb {
        width: 32px;
        height: 40px;
        border-radius: 4px;
        background: #f44336;
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
    }
    .pdf-name {
        font-size: 13px;
        word-break: break-all;
    }
    """

    messages_html = [
        render_message_html(msg, message_id, media_index, sender_classes, transcriptions)
        for msg, message_id in zip(messages, message_ids)
    ]
    body_html = "\n".join(messages_html)

    title = f"WhatsApp chat - generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <title>{escape(title)}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
    {css}
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="title">WhatsApp chat</div>
        </div>
        <div class="chat-body">
            {body_html}
        </div>
    </div>
    <script>
    function scrollToHashTarget() {{
        if (!window.location.hash) {{
            return;
        }}
        var id = decodeURIComponent(window.location.hash.slice(1));
        if (!id) {{
            return;
        }}
        var target = document.getElementById(id);
        if (target) {{
            target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}
    }}

    window.addEventListener('DOMContentLoaded', function() {{
        setTimeout(scrollToHashTarget, 0);
    }});

    window.addEventListener('hashchange', scrollToHashTarget);

    document.addEventListener('play', function(e) {{
        var audios = document.querySelectorAll('audio, video');
        for (var i = 0; i < audios.length; i++) {{
            if (audios[i] !== e.target) {{
                audios[i].pause();
            }}
        }}
    }}, true);
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a WhatsApp-style HTML page from an exported chat.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use defaults (chat.txt, ., output.html) in the current directory
  %(prog)s

  # Specify a base directory
  %(prog)s --dir "path/to/chat/folder"

  # Custom chat file
  %(prog)s mychat.txt

  # Base directory with custom file
  %(prog)s mychat.txt --dir "path/to/folder" --me "YourName"
        """
    )
    parser.add_argument(
        "chat_txt",
        nargs="?",
        default="chat.txt",
        help="Exported WhatsApp chat text file (default: chat.txt)"
    )
    parser.add_argument(
        "media_dir",
        nargs="?",
        default=".",
        help="Media directory (default: current directory '.')"
    )
    parser.add_argument(
        "output_html",
        nargs="?",
        default="output.html",
        help="Output HTML file (default: output.html)"
    )
    parser.add_argument(
        "--dir",
        dest="base_dir",
        default=None,
        help="Base directory for all files (prefix for chat_txt, media_dir, and output_html)"
    )
    parser.add_argument(
        "--me",
        dest="me_name",
        default=None,
        help="Your name in the chat (right-aligns your messages)",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        default=False,
        help="Transcribe audio files using OpenAI API (requires OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--transcribe-only-x-audios",
        dest="transcribe_limit",
        type=int,
        default=None,
        help="Limit transcription to first N audios (default: all)",
    )
    parser.add_argument(
        "--stt-model",
        dest="stt_model",
        default="gpt-4o-mini-transcribe",
        help="Speech-to-text model (default: gpt-4o-mini-transcribe)",
    )
    parser.add_argument(
        "--correct",
        action="store_true",
        default=False,
        help="Correct existing transcriptions using LLM with conversation context",
    )
    parser.add_argument(
        "--correct-interactive",
        action="store_true",
        default=False,
        dest="correct_interactive",
        help="Interactively review each correction (accept/reject/edit)",
    )
    parser.add_argument(
        "--llm-model",
        dest="llm_model",
        default="gpt-4o-mini",
        help="LLM model for transcription correction (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--describe-pdfs",
        action="store_true",
        default=False,
        dest="describe_pdfs",
        help="Generate one-paragraph descriptions for PDF files using OpenAI API (requires OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--pdf-model",
        dest="pdf_model",
        default="gpt-4o",
        help="Model for PDF description (default: gpt-4o; supports vision for scanned PDFs)",
    )
    parser.add_argument(
        "--describe-images",
        action="store_true",
        default=False,
        dest="describe_images",
        help="Generate one-paragraph descriptions for image files using OpenAI vision API (requires OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--image-model",
        dest="image_model",
        default="gpt-4o",
        help="Model for image description (default: gpt-4o)",
    )
    args = parser.parse_args()

    # Apply base directory if specified
    if args.base_dir:
        args.chat_txt = os.path.join(args.base_dir, args.chat_txt)
        # If media_dir is ".", use base_dir directly
        if args.media_dir == ".":
            args.media_dir = args.base_dir
        else:
            args.media_dir = os.path.join(args.base_dir, args.media_dir)
        args.output_html = os.path.join(args.base_dir, args.output_html)

    if not os.path.isfile(args.chat_txt):
        print(f"ERROR: Chat file not found: {args.chat_txt}")
        return

    print("Reading chat...")
    messages = parse_chat(args.chat_txt)
    print(f"{len(messages)} messages read.")

    # Build media index early so transcription can use it
    if os.path.isdir(args.media_dir):
        media_index = build_media_index(args.media_dir, args.output_html)
        print(f"{len(media_index)} media files indexed.")
    else:
        media_index = {}
        print("WARNING: media directory not found; generating text only.")

    if args.transcribe or args.describe_pdfs or args.describe_images:
        print("Detecting language...")
        language = detect_language(messages)
        print(f"Detected language: {language}")
    else:
        language = "en"

    if args.transcribe:
        print(f"Transcribing audios (model: {args.stt_model})...")
        transcribe_audios(
            messages, args.media_dir, media_index,
            args.stt_model, language, args.transcribe_limit,
        )

    if args.correct or args.correct_interactive:
        print(f"Correcting transcriptions (model: {args.llm_model})...")
        correct_transcriptions(
            messages, args.media_dir, media_index,
            args.llm_model, args.transcribe_limit,
            interactive=args.correct_interactive,
        )

    if args.describe_pdfs:
        print(f"Describing PDFs (model: {args.pdf_model})...")
        describe_pdfs(
            messages, args.media_dir, media_index,
            args.pdf_model, args.transcribe_limit, language,
        )

    if args.describe_images:
        print(f"Describing images (model: {args.image_model})...")
        describe_images(
            messages, args.media_dir, media_index,
            args.image_model, args.transcribe_limit, language,
        )

    transcriptions = load_transcriptions(args.media_dir, media_index, args.output_html)
    if transcriptions:
        print(f"{len(transcriptions)} transcriptions/descriptions loaded.")

    print("Generating HTML...")
    generate_html(messages, media_index, args.output_html,
                  me_name=args.me_name, transcriptions=transcriptions)
    print(f"HTML file generated: {args.output_html}")


if __name__ == "__main__":
    main()
