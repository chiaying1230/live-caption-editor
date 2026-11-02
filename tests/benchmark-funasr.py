"""Optional CPU benchmark with an explicit local WAV; never opens a microphone."""
import argparse
import json
import time
from pathlib import Path

import soundfile as sf

from caption.funasr_engine import FunASREngine

parser = argparse.ArgumentParser()
parser.add_argument("audio", type=Path)
parser.add_argument("--chunk-ms", type=int, choices=[600, 1200, 1800], default=1800)
parser.add_argument("--output", type=Path, default=Path("work/funasr-benchmark.json"))
args = parser.parse_args()
audio, rate = sf.read(args.audio, dtype="float32")
if rate != 16000 or audio.ndim != 1:
    parser.error("Use a 16 kHz mono WAV.")
engine = FunASREngine(chunk_ms=args.chunk_ms)
start = time.perf_counter()
engine.load()
load_seconds = time.perf_counter() - start
recognizer = engine.new_session()
timings, text = [], ""
for end in range(recognizer.stride, len(audio)+1, recognizer.stride):
    start = time.perf_counter()
    text = recognizer.recognize("benchmark", audio[:end], False)
    timings.append(time.perf_counter()-start)
start = time.perf_counter()
final = recognizer.recognize("benchmark", audio, True)
result = {"audio":args.audio.name, "audio_seconds":len(audio)/rate, "chunk_ms":args.chunk_ms,
          "load_seconds":round(load_seconds,3), "stream_compute_seconds":round(sum(timings),3),
          "max_chunk_compute_seconds":round(max(timings,default=0),3),
          "final_compute_seconds":round(time.perf_counter()-start,3), "last_partial":text, "final":final}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=True))
