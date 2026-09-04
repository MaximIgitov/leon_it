"use client";

import { useEffect, useRef } from "react";

/*
 * Сколько лиц видно в кадре во время записи. Считаем встроенным детектором
 * браузера (FaceDetector, Chromium): он работает локально, кадры никуда не
 * уходят, наружу отправляется только число. Если детектора нет — молчим, а не
 * подсовываем догадки: в отчёте лучше пустое место, чем выдуманный сигнал.
 *
 * Это не распознавание личности: детектор возвращает только рамки лиц, мы
 * храним их количество. Первый снимок делается через FIRST_SAMPLE_MS после
 * старта записи, дальше — раз в SAMPLE_INTERVAL_MS.
 */

const FIRST_SAMPLE_MS = 4_000;
const SAMPLE_INTERVAL_MS = 15_000;
const FRAME_WIDTH = 320;

type FaceDetectorLike = { detect(source: CanvasImageSource): Promise<unknown[]> };

function createDetector(): FaceDetectorLike | null {
  const ctor = (globalThis as { FaceDetector?: new (options?: unknown) => FaceDetectorLike })
    .FaceDetector;
  if (!ctor) return null;
  try {
    return new ctor({ fastMode: true, maxDetectedFaces: 4 });
  } catch {
    return null;
  }
}

export function useFaceWatch(
  video: HTMLVideoElement | null,
  active: boolean,
  onSample: (count: number) => void,
) {
  const callback = useRef(onSample);
  callback.current = onSample;

  useEffect(() => {
    if (!active || !video) return;
    const detector = createDetector();
    if (!detector) return;

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    let stopped = false;

    const sample = async () => {
      if (stopped || video.readyState < 2 || video.videoWidth === 0) return;
      const scale = FRAME_WIDTH / video.videoWidth;
      canvas.width = FRAME_WIDTH;
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      try {
        const faces = await detector.detect(canvas);
        if (!stopped) callback.current(faces.length);
      } catch {
        // Детектор может отказать на конкретном кадре — пропускаем снимок.
      }
    };

    const first = setTimeout(() => void sample(), FIRST_SAMPLE_MS);
    const timer = setInterval(() => void sample(), SAMPLE_INTERVAL_MS);
    return () => {
      stopped = true;
      clearTimeout(first);
      clearInterval(timer);
      canvas.width = 0;
      canvas.height = 0;
    };
  }, [video, active]);
}
