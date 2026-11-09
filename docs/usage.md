# Install, run, and review

## Requirements

The supported target is **Linux, Python 3.10+**. The task lock uses `fcntl`. Windows is not currently supported. GPU inference requires a compatible PyTorch installation; ASR and punctuation can also use CPU, with substantially higher latency. Model inference in a fresh GPU environment is not covered by the automated tests.

External dependencies: FFmpeg/ffprobe, Tesseract with English and Simplified Chinese language data, and TrueType fonts covering the output languages. On Debian/Ubuntu:

```bash
sudo apt-get install ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim fonts-droid-fallback fonts-dejavu-core
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

For local model inference, install a hardware-appropriate PyTorch build and the optional dependencies:

```bash
python -m pip install -e '.[local-ai]'
```

Download compatible Hugging Face-format model weights **before** processing a private job. Whisper large-v3-turbo and Qwen3-1.7B are example local models, not bundled dependencies. Their licenses apply separately. Runtime model loading uses offline mode and `local_files_only=True`; it will not silently fall back to a cloud inference service.

If fonts or tools are in other locations, configure `TALKWEAVER_CJK_FONT`, `TALKWEAVER_LATIN_FONT`, `TESSDATA_PREFIX` or `TALKWEAVER_TOOLS_PYTHON`. See [SKILL.md](../SKILL.md) for details. The initial artifact filenames and reader controls are Chinese; this is not a fully localized English UI.

## Quick start

```bash
talkweaver doctor
talkweaver init \
  --root /path/to/private-jobs/example \
  --media /path/to/talk.mp4 \
  --title 'Example talk' --speaker 'Example speaker' \
  --language en \
  --asr-model /path/to/local-whisper-model
talkweaver run --root /path/to/private-jobs/example
```

`talkweaver` is also installed as a console command. Use `--text-model` for optional Chinese punctuation restoration, or have the agent proofread the prepared transcript directly. Model paths must point to complete local directories; `doctor` reports dependency presence but does not download models or guarantee their compatibility.

The agent follows these states:

| State | Agent action |
| --- | --- |
| `needs_report_review` | Inspect transcript and original frames; write report boundaries and pixel ROI to `plan.json`. |
| `needs_slide_review` | Compare actual candidate images and OCR; account for every candidate in a review decision file. |
| `text_prepared` / `needs_text_review` | Review every paragraph against slides; preserve raw text, source IDs and timestamps; record edits. |
| `verify_finished` | Read `delivery.json`, disclose gaps and deliver the requested files. |

Run again after each review step. Review is performed by the agent, not a requirement to ask the user to confirm every routine operation. Full command examples, schemas and quality requirements are in [SKILL.md](../SKILL.md).

Use a separate job for each report. Do not place private jobs in this repository or expose their directory through a static file server.

## Privacy and data boundaries

- No example videos, transcripts, screenshots, personal configurations, credentials or model weights are included.
- The processing code has no cloud AI or messaging integration. Installing packages and obtaining model weights are separate network operations.
- Local processing does not make a hosted AI agent local. If an agent reads a transcript or views an image through a hosted model, that content may be sent to its provider. For confidential material, use a suitably local agent or explicitly authorize that data flow.
- Job files can contain absolute input paths and correction records. Keep them private, outside version control.
- The repository uses an explicit file allowlist in `.gitignore` to reduce accidental inclusion of job artifacts. This does not replace reviewing staged files before publishing.
- An HTML reader stores edits in that browser's local storage. It does not sync them back into the transcript or PDF. Keep its companion audio beside the HTML for local playback.

## Known limitations

Fixed slide regions require review; dynamic layouts, short-lived pages, animation and embedded video may cause missed or duplicate candidates. OCR cannot restore content clipped or blurred in the source. ASR can hallucinate over music or silence and misrecognize names or technical terms. Quality flags are heuristics, not a completeness guarantee.

Audio anchors are segment-level, not word-level alignment. Punctuation restoration preserves the approved word sequence and does not certify semantic correctness. Unpaired speech stays in the full transcript. Source media and original recognition receipts remain the evidence for corrections.

Existing output is not overwritten by the CLI. Use a new job directory for revisions. Browser capture, automatic multi-report orchestration and fully unattended semantic proofreading remain future work.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests generate synthetic video and audio at runtime. They exercise odd-size cropping, cache conflicts, review gates, non-widescreen slide exports, transcript coverage and input integrity without downloading models or using private media. They do not measure ASR accuracy.

## License

AGPL-3.0-or-later. See [LICENSE](../LICENSE). This choice is consistent with the current PyMuPDF dependency; PyMuPDF also offers a commercial license. Model weights, fonts, FFmpeg and other dependencies retain their own licenses. No model weights, fonts or third-party library source are redistributed here.

## Development layout

Code lives in `src/talkweaver/`, regression tests in `tests/`, and user documentation in `docs/`. The root `SKILL.md` remains easy for agents to discover. Install with `python -m pip install -e .` before running tests. The package supports both the `talkweaver` command and `python -m talkweaver`.

For a release smoke test, build a wheel, install it into a clean environment, then invoke the CLI from outside the checkout. Automated tests use synthetic media and do not validate fresh-model GPU inference.
