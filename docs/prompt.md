
Copy this prompt into an agent running on a machine with internet access:

Work in the TRINETRA repository. Install and integrate the three models currently enabled in backend/models/manifest.json:

1. asr — Systran/faster-whisper-base
2. spoof — Bgeorge/deepfake-audio-detector-wav2vec2
3. text_scam — bangta/Scam-detection

Use Python 3.12 or 3.13. Install backend/requirements.txt and backend/requirements-models.txt in a project virtual environment. Use backend/tools/fetch_models.py to download the checkpoints into backend/models, pin their resolved revisions, and record their SHA-256 checksums in the manifest. If a checkpoint's actual files or labels differ from what the adapter expects, make the smallest necessary code or manifest correction and explain it.

Test real inference through backend/app/inference.py using a suitable speech sample and text inputs. Confirm that:
- the manifest reports all three models as available;
- speech transcription, voice authenticity, and text classification return results without inference errors;
- the payment flow stores the resulting evidence and the SOC case displays it;
- the relevant backend tests pass;
- the models still load with HF_HUB_OFFLINE=1.

Do not use mock model outputs as proof that installation works. Do not enable text_nli or graph_gnn: text_nli is disabled, and graph_gnn has no selected checkpoint. Keep all model signals review-only (enforce: false); there is no labelled evaluation dataset to justify automatic enforcement. Report each model's exact revision, checksum, test result, and any remaining limitation. Check the voice detector's CC BY-NC 4.0 licence before suggesting commercial use.

The repository’s download path is fetch_models.py (backend/tools/fetch_models.py); its model list and current settings are in manifest.json (backend/models/manifest.json).
