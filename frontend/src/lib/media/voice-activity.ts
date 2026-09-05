/*
 * Конец ответа в живом диалоге: по уровню микрофона решаем, говорит кандидат
 * или замолчал. Чистая машина состояний (проверяется без браузера) плюс хук,
 * который снимает уровень через AnalyserNode и гонит его в детектор.
 *
 * Правила: первые сотни миллисекунд — калибровка шума комнаты, порог = шум × k,
 * но не ниже пола. Пока кандидат ни разу не заговорил, тишина ничего не
 * значит (до таймаута «не слышу»). После речи пауза заданной длины завершает
 * ответ; если наговорили совсем мало («не знаю»), пауза нужна длиннее, чтобы
 * не оборвать человека, который просто собирается с мыслями.
 */

import { useEffect, useRef, useState } from "react";

export type SilenceDetectorOptions = {
  /** Речь короче этого порога считается «почти ничего»: пауза для завершения длиннее. */
  minSpeechMs: number;
  /** Пауза после содержательной речи, завершающая ответ. */
  silenceMs: number;
  /** Пауза после очень короткой речи. */
  shortAnswerSilenceMs: number;
  /** Кандидат так и не заговорил: событие «не слышу» (ответ не завершается). */
  noSpeechTimeoutMs: number;
  /** Сбор шума комнаты в начале. */
  calibrationMs: number;
  /** Порог не опускается ниже этого уровня RMS. */
  thresholdFloor: number;
  /** Порог = шум × коэффициент. */
  thresholdGain: number;
};

export const DEFAULT_SILENCE_OPTIONS: SilenceDetectorOptions = {
  minSpeechMs: 5000,
  silenceMs: 2500,
  shortAnswerSilenceMs: 7000,
  noSpeechTimeoutMs: 30000,
  calibrationMs: 600,
  thresholdFloor: 0.015,
  thresholdGain: 3,
};

export type SilenceEvent =
  | "speech_started"
  | "silence_started"
  | "silence_cancelled"
  | "end_of_speech"
  | "no_speech";

export class SilenceDetector {
  private startedAt: number | null = null;
  private lastTick: number | null = null;
  private noise = 0;
  private noiseSamples = 0;
  private speechMs = 0;
  private speaking = false;
  private everSpoke = false;
  private silenceSince: number | null = null;
  private noSpeechReported = false;
  private finished = false;

  constructor(private readonly options: SilenceDetectorOptions = DEFAULT_SILENCE_OPTIONS) {}

  get threshold(): number {
    return Math.max(this.options.thresholdFloor, this.noise * this.options.thresholdGain);
  }

  get done(): boolean {
    return this.finished;
  }

  get spoke(): boolean {
    return this.everSpoke;
  }

  /** Сколько тишины нужно, чтобы завершить ответ, с учётом того, сколько наговорили. */
  private silenceNeeded(): number {
    return this.speechMs >= this.options.minSpeechMs
      ? this.options.silenceMs
      : this.options.shortAnswerSilenceMs;
  }

  /** Миллисекунды до завершения ответа; null — пауза сейчас не идёт. */
  silenceRemaining(now: number): number | null {
    if (this.finished || this.silenceSince === null) return null;
    return Math.max(0, this.silenceNeeded() - (now - this.silenceSince));
  }

  tick(level: number, now: number): SilenceEvent | null {
    if (this.finished) return null;
    if (this.startedAt === null || this.lastTick === null) {
      this.startedAt = now;
      this.lastTick = now;
    }
    const elapsed = now - this.lastTick;
    this.lastTick = now;
    if (now - this.startedAt < this.options.calibrationMs) {
      // Шум комнаты: среднее по первым замерам, с потолком — вдруг уже говорят.
      const sample = Math.min(level, 0.05);
      this.noise = (this.noise * this.noiseSamples + sample) / (this.noiseSamples + 1);
      this.noiseSamples += 1;
      return null;
    }
    if (level > this.threshold) {
      this.speechMs += elapsed;
      const wasPausing = this.silenceSince !== null;
      this.silenceSince = null;
      if (!this.speaking) {
        this.speaking = true;
        const first = !this.everSpoke;
        this.everSpoke = true;
        if (wasPausing) return "silence_cancelled";
        return first ? "speech_started" : null;
      }
      return null;
    }
    if (!this.everSpoke) {
      if (!this.noSpeechReported && now - this.startedAt >= this.options.noSpeechTimeoutMs) {
        this.noSpeechReported = true;
        return "no_speech";
      }
      return null;
    }
    if (this.speaking) {
      this.speaking = false;
      this.silenceSince = now;
      return "silence_started";
    }
    if (this.silenceSince !== null && now - this.silenceSince >= this.silenceNeeded()) {
      this.finished = true;
      return "end_of_speech";
    }
    return null;
  }
}

/** Среднеквадратичный уровень сигнала по байтам осциллограммы AnalyserNode (0…1). */
export function rmsLevel(samples: Uint8Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const value = (samples[i] - 128) / 128;
    sum += value * value;
  }
  return Math.sqrt(sum / samples.length);
}

export type VoiceActivity = {
  /** Текущий уровень микрофона 0…1 — для индикатора. */
  level: number;
  /** Секунды до завершения ответа, пока идёт пауза; null — кандидат говорит или ещё не начал. */
  countdown: number | null;
};

const TICK_MS = 100;

/**
 * Слушать микрофон, пока ``active``: события детектора уходят в ``onEvent``,
 * уровень и обратный отсчёт паузы — в состояние для интерфейса.
 */
export function useVoiceActivity(
  stream: MediaStream | null,
  active: boolean,
  onEvent: (event: SilenceEvent) => void,
  options: SilenceDetectorOptions = DEFAULT_SILENCE_OPTIONS,
): VoiceActivity {
  const [level, setLevel] = useState(0);
  const [countdown, setCountdown] = useState<number | null>(null);
  const callback = useRef(onEvent);
  callback.current = onEvent;

  useEffect(() => {
    if (!active || !stream || stream.getAudioTracks().length === 0) {
      setLevel(0);
      setCountdown(null);
      return;
    }
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    const context = new Ctor();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    void context.resume().catch(() => undefined);
    const samples = new Uint8Array(analyser.fftSize);
    const detector = new SilenceDetector(options);
    const timer = window.setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      const current = rmsLevel(samples);
      const now = performance.now();
      const event = detector.tick(current, now);
      setLevel(current);
      const remaining = detector.silenceRemaining(now);
      setCountdown(remaining === null ? null : Math.ceil(remaining / 1000));
      if (event) callback.current(event);
    }, TICK_MS);
    return () => {
      window.clearInterval(timer);
      source.disconnect();
      void context.close().catch(() => undefined);
    };
  }, [active, stream, options]);

  return { level, countdown };
}
