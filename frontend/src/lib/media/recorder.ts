/*
 * Запись ответа и последовательная загрузка кусков.
 *
 * Куски MediaRecorder (timeslice) не самодостаточны — только конкатенация даёт
 * валидный файл, поэтому загрузка идёт строго по порядку с одним активным
 * запросом; потерянный ответ сервера повторяется, а 409 с фактическим смещением
 * синхронизирует очередь. До завершения загрузки ничего не теряется: куски
 * держатся в памяти до подтверждения.
 */

import { roomApi, uploadChunk } from "@/lib/api/room";

// Порядок важен: Safari поддерживает только mp4/H.264, Chromium — webm с VP9.
export const MIME_CANDIDATES = [
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
  "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
  "video/mp4",
];

export function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
}

export type UploadProgress = {
  bytesTotal: number;
  bytesUploaded: number;
  pending: number;
  failed: boolean;
};

export type AnswerRecorderOptions = {
  token: string;
  questionIndex: number;
  stream: MediaStream;
  timesliceMs?: number;
  onProgress?: (progress: UploadProgress) => void;
  onError?: (error: Error) => void;
};

export class AnswerRecorder {
  private recorder: MediaRecorder | null = null;
  private queue: Blob[] = [];
  private uploading = false;
  private offset = 0;
  private bytesTotal = 0;
  private stopped = false;
  private failed = false;
  private answerId: string | null = null;
  private startedAt = 0;
  private drainResolvers: Array<() => void> = [];
  readonly mimeType: string;

  constructor(private readonly options: AnswerRecorderOptions) {
    this.mimeType = pickMimeType() ?? "video/webm";
  }

  get id(): string | null {
    return this.answerId;
  }

  async start(): Promise<void> {
    const created = await roomApi.createAnswer(this.options.token, this.options.questionIndex, this.mimeType);
    this.answerId = created.answer.id;
    const recorder = new MediaRecorder(this.options.stream, {
      mimeType: this.mimeType,
      videoBitsPerSecond: 800_000,
      audioBitsPerSecond: 64_000,
    });
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        this.queue.push(event.data);
        this.bytesTotal += event.data.size;
        this.report();
        void this.drain();
      }
    };
    recorder.onerror = () => {
      this.failed = true;
      this.options.onError?.(new Error("Ошибка записи: браузер остановил MediaRecorder"));
      this.report();
    };
    this.recorder = recorder;
    this.startedAt = performance.now();
    recorder.start(this.options.timesliceMs ?? 2000);
  }

  /** Остановить запись, дождаться загрузки всех кусков и подтвердить ответ. */
  async finish(): Promise<{ answerId: string; size: number; durationMs: number }> {
    const recorder = this.recorder;
    if (!recorder || !this.answerId) throw new Error("Запись не начата");
    const durationMs = Math.round(performance.now() - this.startedAt);
    if (recorder.state !== "inactive") {
      await new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
        recorder.stop();
      });
    }
    this.stopped = true;
    await this.waitForDrain();
    if (this.failed) throw new Error("Не удалось загрузить запись");
    await roomApi.completeAnswer(this.options.token, this.answerId, {
      size: this.offset,
      client_duration_ms: durationMs,
      mime_type: this.mimeType,
    });
    return { answerId: this.answerId, size: this.offset, durationMs };
  }

  private report(): void {
    this.options.onProgress?.({
      bytesTotal: this.bytesTotal,
      bytesUploaded: this.offset,
      pending: this.queue.length,
      failed: this.failed,
    });
  }

  private waitForDrain(): Promise<void> {
    if (this.queue.length === 0 && !this.uploading) return Promise.resolve();
    return new Promise((resolve) => this.drainResolvers.push(resolve));
  }

  private async drain(): Promise<void> {
    if (this.uploading || !this.answerId) return;
    this.uploading = true;
    try {
      while (this.queue.length > 0) {
        const chunk = this.queue[0];
        const sent = await this.sendWithRetry(chunk);
        if (!sent) {
          this.failed = true;
          this.report();
          break;
        }
        this.queue.shift();
        this.report();
      }
    } finally {
      this.uploading = false;
      if (this.queue.length === 0 || this.failed) {
        const resolvers = this.drainResolvers;
        this.drainResolvers = [];
        resolvers.forEach((resolve) => resolve());
      }
    }
  }

  private async sendWithRetry(chunk: Blob): Promise<boolean> {
    let attempt = 0;
    while (attempt < 6) {
      attempt += 1;
      try {
        const result = await uploadChunk(this.options.token, this.answerId!, this.offset, chunk);
        if (result.ok) {
          this.offset = result.offset;
          return true;
        }
        // Сервер уже принял этот кусок раньше (ответ потерялся) — сдвигаемся.
        if (result.actualOffset >= this.offset + chunk.size) {
          this.offset = result.actualOffset;
          return true;
        }
        this.offset = result.actualOffset;
      } catch (error) {
        if (attempt >= 6) {
          this.options.onError?.(error instanceof Error ? error : new Error("Сбой загрузки"));
          return false;
        }
        await new Promise((resolve) => setTimeout(resolve, Math.min(8000, 500 * 2 ** attempt)));
      }
    }
    return false;
  }
}
