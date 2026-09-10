"""Render Hourglass's original five-note sad-trombone cue; standard library only."""
import array
import math
from pathlib import Path
import sys
import wave


RATE = 44100


def render():
    samples = []
    # Two long boos, followed by three progressively lower, wah-shaped womps.
    notes = [(196, 165, .52, .10), (175, 147, .58, .22),
             (165, 123, .35, .09), (147, 98, .38, .09), (131, 65, .74, .16)]
    for index, (high, low, duration, gap) in enumerate(notes):
        phase = 0.0
        for frame in range(round(duration * RATE)):
            t = frame / RATE
            progress = t / duration
            pitch = high + (low - high) * progress ** .65
            pitch *= 1 + .008 * math.sin(2 * math.pi * 5.5 * t)
            phase += 2 * math.pi * pitch / RATE
            wah = math.sin(math.pi * progress) ** .75
            cutoff = 300 + (1000 if index < 2 else 1600) * wah * (1 - .65 * progress)
            tone = sum(math.sin(h * phase) / (h * (1 + (h * pitch / cutoff) ** 4))
                       for h in range(1, 19))
            attack = min(1, t / .025)
            release = min(1, (duration - t) / .08)
            envelope = math.sin(attack * math.pi / 2) ** 2 * math.sin(release * math.pi / 2) ** 2
            flutter = 1 - (.15 * progress * (1 + math.sin(2 * math.pi * 7 * t)) if index == 4 else 0)
            samples.append(tone * envelope * flutter)
        samples.extend([0.0] * round(gap * RATE))
    peak = max(abs(value) for value in samples)
    pcm = array.array('h', (round(value / peak * .60 * 32767) for value in samples))
    if sys.byteorder != 'little':
        pcm.byteswap()
    target = Path(__file__).with_name('run-failed.wav')
    with wave.open(str(target), 'wb') as output:
        output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm.tobytes())
    print(f'{target.name}: {len(samples) / RATE:.2f}s, mono 16-bit PCM, {RATE} Hz')


if __name__ == '__main__':
    render()
