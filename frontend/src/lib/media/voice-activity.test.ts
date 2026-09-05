import { describe, expect, it } from "vitest";

import { DEFAULT_SILENCE_OPTIONS, SilenceDetector, rmsLevel } from "@/lib/media/voice-activity";

const options = { ...DEFAULT_SILENCE_OPTIONS, calibrationMs: 200, minSpeechMs: 1000, silenceMs: 500, shortAnswerSilenceMs: 1500, noSpeechTimeoutMs: 3000 };

/** Прогнать детектор по сценарию уровней с шагом 100 мс, вернуть события с временем. */
function run(levels: number[], detector = new SilenceDetector(options)): Array<[number, string]> {
  const events: Array<[number, string]> = [];
  levels.forEach((level, i) => {
    const event = detector.tick(level, i * 100);
    if (event) events.push([i * 100, event]);
  });
  return events;
}

const quiet = (n: number) => Array<number>(n).fill(0.003);
const loud = (n: number) => Array<number>(n).fill(0.2);

describe("детектор конца ответа", () => {
  it("после содержательной речи пауза завершает ответ, начало паузы — событием", () => {
    const events = run([...quiet(3), ...loud(12), ...quiet(8)]);
    expect(events).toEqual([
      [300, "speech_started"],
      [1500, "silence_started"],
      [2000, "end_of_speech"],
    ]);
  });

  it("короткая реплика ждёт длинную паузу, а возобновление речи отменяет отсчёт", () => {
    const detector = new SilenceDetector(options);
    const events = run([...quiet(3), ...loud(4), ...quiet(6), ...loud(9), ...quiet(6)], detector);
    expect(events).toEqual([
      [300, "speech_started"],
      [700, "silence_started"],
      [1300, "silence_cancelled"],
      [2200, "silence_started"],
      [2700, "end_of_speech"],
    ]);
    expect(detector.done).toBe(true);
    // После завершения детектор молчит.
    expect(detector.tick(0.3, 5000)).toBeNull();
  });

  it("пока кандидат не заговорил, тишина не завершает ответ, но по таймауту приходит «не слышу»", () => {
    const events = run(quiet(40));
    expect(events).toEqual([[3000, "no_speech"]]);
  });

  it("порог подстраивается под шум комнаты, но не ниже пола", () => {
    const noisy = new SilenceDetector(options);
    run(Array<number>(3).fill(0.02), noisy);
    expect(noisy.threshold).toBeCloseTo(0.06, 5);
    const silent = new SilenceDetector(options);
    run(quiet(3), silent);
    expect(silent.threshold).toBe(options.thresholdFloor);
  });

  it("обратный отсчёт паузы считается от её начала", () => {
    const detector = new SilenceDetector(options);
    run([...quiet(3), ...loud(12), ...quiet(2)], detector);
    // Пауза началась на 1500 мс: первый тихий замер после речи.
    expect(detector.silenceRemaining(1500)).toBe(500);
    expect(detector.silenceRemaining(1700)).toBe(300);
    expect(detector.silenceRemaining(2100)).toBe(0);
  });

  it("rms по осциллограмме: тишина — ноль, полный размах — единица", () => {
    expect(rmsLevel(new Uint8Array([128, 128, 128]))).toBe(0);
    expect(rmsLevel(new Uint8Array([0, 256 - 1]))).toBeGreaterThan(0.99);
    expect(rmsLevel(new Uint8Array([]))).toBe(0);
  });
});
