# Test fixtures

`speech_probe.webm` — 11.8 s of synthetic speech, Opus at 48 kHz in WebM (the
format browsers' MediaRecorder produces). Generated 2026-09-11 with gTTS and
PyAV in a throwaway environment; neither is a project dependency. It says:

> We agreed to move the warehouse to Denver in March. Dana owns the lease
> review and will send a draft by Friday. The open question is whether the
> second shift stays.

Used only by the opt-in live test `tests/test_stt_live.py` (`RUN_STT_LIVE=1`).
