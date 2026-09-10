# Run sounds

`run-failed.wav` is an original synthesized sad-trombone cue: two long “booo”
notes, then three descending “womp” notes. It contains no borrowed recording or
speech. It uses the repository's MIT license.

Regenerate it with `python3 sounds/make_failure_sound.py` (standard library only).
The PCM waveform has smooth attack/release envelopes and no embedded metadata.

Hourglass plays it once when a run exits with an error or reaches its consecutive
wrong-answer stop. An individual wrong answer or question timeout does not
trigger it. Manual stop/cancellation is silent; normal completion and the hour
boundary keep the existing macOS Glass chime. Sound uses `afplay` asynchronously
on the controller's Mac, so it works with the browser in the background or closed.
Audio availability never prevents saving the result or starting queued work.
