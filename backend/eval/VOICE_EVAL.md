# Voice authenticity evaluation

Run this offline using consented or public test audio. Keep clips and downloaded
checkpoints outside Git and outside the transaction database.

## Prepare the input

Put 16 kHz mono PCM16 WAV files and a `labels.csv` file in one directory.
Columns are `id,split,label,language,path_or_text,condition`. Use `0` for
genuine speech and `1` for synthetic or manipulated speech. Use `dev` to
choose thresholds and reserve `test` for the final comparison. Keep a speaker,
generator family, and all versions of a recording in the same split when
testing generalization. Match the spoken wording across classes where possible.

Include app recordings and uploads in representative languages and accents,
including coughs or congestion, short speech, noisy rooms and phone audio.
Report clean, noisy and degraded conditions independently. Use ASVspoof 5
as a complementary benchmark after checking for training and test overlap.

## Compare models

Give each candidate a separate directory containing a `manifest.json` with a
`spoof` entry and verified local weights. The manifest records the model
revision, SHA-256, score label, window length and thresholds. Confirm preprocessing
and labels against the checkpoint before interpreting its score. The comparison
uses the application's Wav2Vec2 or AASIST-L audio classification adapter.
A checkpoint with a different preprocessing contract needs its own adapter.

For the AASIST-L trial, copy `aasist-l-manifest.json` to the candidate
directory as `manifest.json`, install `onnxruntime` in the evaluation
environment, and download `aasist-l.onnx` from the revision listed in the
manifest. The manifest loader checks the downloaded file's SHA-256.

From `backend`:

```bash
HF_HUB_OFFLINE=1 python eval/run_eval.py classify --signal spoof \
  --data /path/to/labeled-clips --split test \
  --model-dir models --model-dir /path/to/candidate
```

Set `clear_below` and `threshold` in the candidate manifest using development
data. A score below `clear_below` means no spoof detected, a score at or above
`threshold` flags the clip, and scores between them are inconclusive. Freeze
the thresholds before evaluating the test split. When labels are unverified,
the diagnostic report shows what the raw score would do at the cutoff without
assigning those predictions to the app.

Compare genuine flag rate, synthetic flag and miss rates, abstentions for
each class, and warm p95 inference time. A model could have few false alarms
by abstaining on nearly every clip. Include class counts and uncertainty
intervals and account for repeated variants from the same speaker when drawing
conclusions. A small smoke test can expose failures but does not qualify a model.

## Review pilot

After choosing a licensed candidate that passes the held-out comparison, start
with `enforce: false`. Verify microphone and upload both reach screening, a
slow or missing model still leaves incoming requests reviewable, and the analyst
sees the model, outcome and reason before approving. Compare the same metrics
on consented recordings from target users, and keep independent verification
for risky money requests. Roll back to the previous manifest if false alarms
or latency exceed the pilot limits.

## Local smoke result

The test split held out eight LibriSpeech speakers from the development split.
Each speaker contributed one real reading and an eSpeak reading of the same
text, each in clean and band-limited forms. This produced 16 genuine and
16 synthetic test clips. Both splits used eSpeak, so this does not measure
generalization to other generators.

| Detector | Genuine flagged | Synthetic flagged | Warm p95 |
| --- | ---: | ---: | ---: |
| Previous Bgeorge checkpoint, raw diagnostic cutoff | 14/16 | 13/16 | 687 ms |
| AASIST-L, trial cutoffs | 0/16 | 16/16 | 116 ms |

The previous runtime returned inconclusive on all clips because its label
mapping is unverified. AASIST-L resolved all 32 clips, but this small test
does not qualify it for activation. DF Arena 1B was not scored because its
weight download failed in this environment.

An isolated sandbox run also checked the candidate's analyst evidence for a
genuine clip, a synthetic clip and a simulated detector timeout. All three
incoming test requests remained reviewable. The browser upload flow was
checked in Firefox, from selecting a file before consent to submitting the
request after screening.

The broader evaluation found that AASIST-L flagged 9 of 11 genuine clips in
the Behavioral Signals multilingual demo and 10 of 16 genuine Coswara clips
from participants reporting cough or cold. The app therefore runs AASIST-L
in diagnostic mode. It records a raw score and returns inconclusive for
voice authenticity. The separate trial manifest retains the thresholds for
offline comparisons.

### Cutoff review

The AASIST-L score is the two-class softmax output for spoofing, reported on
a 0–1 scale for the model's first 4.04-second input window. Broad testing showed
that a high score, including a displayed 1.0000, can occur on genuine speech.
It is uncalibrated and cannot be interpreted as a probability of fraud.

On the 15 genuine recordings and 31 commercial or CD-ADD clones that passed
the audio quality check, trial cutoffs produced the following results:

| Trial cutoff | Genuine clips flagged | Clones flagged |
| --- | ---: | ---: |
| 0.50 | 11/15 | 22/31 |
| 0.95 | 8/15 | 11/31 |
| 0.99 | 6/15 | 10/31 |
| 1.00 (rounded stored scores) | 3/15 | 1/31 |

The capture API and analyst evidence expose a review-only Real/Fake model
prediction at the 0.50 cutoff. The policy still treats this signal as
inconclusive. Gemini receives the inconclusive status without the raw voice score.

Sweeping every observed score on the same 46 scoreable clips gave a best
balanced accuracy of 56.7% at 0.0019. That cutoff detected all 31 clones
and also flagged 13 of 15 genuine clips. Both classes had recordings with
identical stored scores of 0.9999 and 1.0000, so no binary cutoff can
separate this sample. The sweep describes these clips and was not an
independent validation set.

The local evaluation set contains 64 clips (18 genuine and 46 synthetic)
from the [Behavioral Signals demo](https://huggingface.co/datasets/behavioralsignals/deepfake-detection-demo)
and [CD-ADD](https://huggingface.co/datasets/SpeechAntiSpoofingBenchmarks/CD-ADD).
On the development machine it is stored under
`backend/eval/data/voice-calibration` with its labels and trial report.
The audio stays outside Git and the app's transaction data.

### VoiceGuard comparison setup

`voiceguard-manifest.json` is an offline trial profile for the
[VoiceGuard XLS-R + AASIST checkpoint](https://huggingface.co/Hashim-Bhagad/voiceguard-xlsr-aasist-indic).
Download `model.onnx` at the manifest's revision into an ignored local
directory and copy the trial profile there as `manifest.json`. The runtime
checks its SHA-256. Prepare a separate AASIST-L trial directory using its
trial profile as described above.

```bash
HF_HUB_OFFLINE=1 python eval/run_eval.py classify --signal spoof \
  --data eval/data/voice-calibration --split test --include-scores \
  --model-dir /path/to/aasist-trial --model-dir /path/to/voiceguard-trial
```

VoiceGuard's trial uses its author's 0.05393 cutoff. If tuning for TRINETRA,
choose cutoffs on separate development audio and freeze them before opening
the held-out test set. Check false alarms on genuine speech and missed
clones by language, source and recording condition. The checkpoint has
a noncommercial license and the trial profile is separate from the live app.

The local comparison ran the AASIST-L baseline on all 64 recordings. At
its trial cutoff it flagged 22 of 31 scoreable clones and 11 of 15
scoreable genuine clips. The audio quality gate excluded 18 clips.
The VoiceGuard download did not complete due to connection timeouts,
so the local run recorded no accuracy or latency result for VoiceGuard.

### Local training pilot

`train_voice.py` freezes a local Wav2Vec2 checkpoint and fits a new
genuine/spoof classification head. It writes a checksum-pinned checkpoint the
existing TRINETRA screening adapter can load. The development split selects
both cutoffs. Scores between them are inconclusive. The test split is only
used by the evaluator after the checkpoint and cutoffs have been written.

The first local pilot used a balanced [ASVspoof 2019 LA subset](https://huggingface.co/datasets/Bisher/ASVspoof_2019_LA)
with 168 training, 80 development and 80 test clips. The three splits had
disjoint speakers and the test split used unseen attack systems. The existing
64-clip modern-clone set was also held out. SEA-Spoof returned an access error
from this workspace. The pilot therefore had no Hindi or Tamil training data.
Check the licenses of the base checkpoint and datasets before distributing any
derived weights.

From `backend`, with the base checkpoint and labels installed locally:

```bash
HF_HUB_OFFLINE=1 python eval/train_voice.py \
  --data eval/data/asvspoof2019-pilot \
  --base models/deepfake-audio-detector-wav2vec2 \
  --output eval/data/voice-head-validated

HF_HUB_OFFLINE=1 python eval/run_eval.py classify --signal spoof \
  --data eval/data/voice-calibration --split test \
  --model-dir eval/data/aasist-trial --model-dir eval/data/voice-head-validated
```

The recordings, trained weights and per-clip reports stay in the ignored
evaluation data directory. The sandbox integration exercised consent, audio
screening, payment submission, and the candidate model's analyst evidence.

Development selected a clear cutoff of 0.4791 and a flag cutoff of 0.6212.
The frozen thresholds produced these test results. Inconclusive counts include
clips rejected by the existing audio quality check.

| Test set | Model | Synthetic flagged | Genuine flagged | Inconclusive |
| --- | --- | ---: | ---: | ---: |
| ASVspoof 2019 subset | AASIST-L trial | 33/40 | 0/40 | 8/80 |
| ASVspoof 2019 subset | Local Wav2Vec2 pilot | 4/40 | 7/40 | 60/80 |
| Modern-clone set | AASIST-L trial | 22/46 | 11/18 | 18/64 |
| Modern-clone set | Local Wav2Vec2 pilot | 6/46 | 3/18 | 54/64 |

The pilot did not qualify for activation. Its lower false alarm count on the
modern set came with many more inconclusive results and fewer detected clones.
