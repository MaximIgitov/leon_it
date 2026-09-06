"use client";

import { Skeleton } from "@/components/ui/skeleton";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Camera, Check, Mic, Play, RefreshCw, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  describeFailure,
  detectEnvironment,
  isVirtualCamera,
  listDevices,
  requestMedia,
  stopStream,
  type DeviceInfo,
  type Environment,
  type PermissionFailure,
} from "@/lib/media/devices";
import { pickMimeType } from "@/lib/media/recorder";

export type DeviceCheckResult = {
  stream: MediaStream;
  environment: Environment;
  devices: DeviceInfo[];
  virtualCamera: boolean;
};

function useMicLevel(stream: MediaStream | null): number {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!stream || stream.getAudioTracks().length === 0) return;
    const AudioContextCtor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    const context = new AudioContextCtor();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i += 1) {
        const centered = (data[i] - 128) / 128;
        sum += centered * centered;
      }
      const rms = Math.sqrt(sum / data.length);
      setLevel(Math.min(1, rms * 4));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      void context.close();
    };
  }, [stream]);
  return level;
}

export function DeviceCheck({ onReady }: { onReady: (result: DeviceCheckResult) => void }) {
  const [environment] = useState<Environment>(() => detectEnvironment());
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [failure, setFailure] = useState<PermissionFailure | null>(null);
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [videoId, setVideoId] = useState<string>("");
  const [audioId, setAudioId] = useState<string>("");
  const [requesting, setRequesting] = useState(false);
  const [testState, setTestState] = useState<"idle" | "recording" | "playback">("idle");
  const [testUrl, setTestUrl] = useState<string | null>(null);
  const [heardOk, setHeardOk] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mounted = useRef(true);
  const handedOff = useRef(false);
  const testRecorder = useRef<MediaRecorder | null>(null);
  const level = useMicLevel(stream);

  const acquire = useCallback(
    async (ids?: { video?: string; audio?: string }) => {
      setRequesting(true);
      setFailure(null);
      try {
        const next = await requestMedia(ids);
        if (!mounted.current) { stopStream(next); return; }
        stopStream(streamRef.current);
        streamRef.current = next;
        setStream(next);
        const list = await listDevices();
        setDevices(list);
        const videoTrack = next.getVideoTracks()[0];
        const audioTrack = next.getAudioTracks()[0];
        setVideoId(videoTrack?.getSettings().deviceId ?? "");
        setAudioId(audioTrack?.getSettings().deviceId ?? "");
      } catch (error) {
        setFailure(describeFailure(error, environment));
      } finally {
        setRequesting(false);
      }
    },
    [environment],
  );

  useEffect(() => {
    if (!environment.secureContext || !environment.mediaDevicesSupported || !environment.mediaRecorderSupported) {
      setFailure(describeFailure(null, environment));
      return;
    }
    void acquire();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const recorder = testRecorder.current;
      if (recorder?.state === "recording") { recorder.onstop = null; recorder.stop(); }
      if (!handedOff.current) stopStream(streamRef.current);
    };
  }, []);
  useEffect(() => {
    const video = videoRef.current;
    if (video && stream) {
      video.srcObject = stream;
      void video.play().catch(() => undefined);
    }
  }, [stream]);

  useEffect(() => () => {
    if (testUrl) URL.revokeObjectURL(testUrl);
  }, [testUrl]);

  const startTest = () => {
    if (!stream) return;
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder.mimeType });
      setTestUrl(URL.createObjectURL(blob));
      setTestState("playback");
    };
    testRecorder.current = recorder;
    recorder.start();
    setTestState("recording");
    setTimeout(() => {
      if (recorder.state === "recording") recorder.stop();
    }, 5000);
  };

  const stopTest = () => {
    if (testRecorder.current?.state === "recording") testRecorder.current.stop();
  };

  const cameras = devices.filter((d) => d.kind === "videoinput");
  const mics = devices.filter((d) => d.kind === "audioinput");
  const virtualCamera = cameras.some((c) => c.deviceId === videoId && isVirtualCamera(c.label));

  if (failure) {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg border border-warning/50 bg-warning/10 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
          <div>
            <p className="font-semibold">{failure.title}</p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
              {failure.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        </div>
        {failure.kind !== "insecure" && failure.kind !== "unsupported" ? (
          <Button onClick={() => acquire()} disabled={requesting}>
            {requesting ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Проверить снова
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-[3fr_2fr]">
        <div className="relative overflow-hidden rounded-xl bg-black">
          <video ref={videoRef} muted playsInline autoPlay className="aspect-video w-full object-cover" />
          {!stream ? (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-white/80">
              <Skeleton className="mr-2 h-4 w-4 rounded-md" /> Запрашиваем доступ к камере…
            </div>
          ) : null}
        </div>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Camera className="h-3.5 w-3.5" /> Камера
            </Label>
            <Select value={videoId} onValueChange={(id) => void acquire({ video: id, audio: audioId || undefined })} disabled={!cameras.length}>
              <SelectTrigger>
                <SelectValue placeholder="Камера" />
              </SelectTrigger>
              <SelectContent>
                {cameras.map((c, i) => (
                  <SelectItem key={c.deviceId || i} value={c.deviceId || `camera-${i}`}>
                    {c.label || `Камера ${i + 1}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Mic className="h-3.5 w-3.5" /> Микрофон
            </Label>
            <Select value={audioId} onValueChange={(id) => void acquire({ video: videoId || undefined, audio: id })} disabled={!mics.length}>
              <SelectTrigger>
                <SelectValue placeholder="Микрофон" />
              </SelectTrigger>
              <SelectContent>
                {mics.map((m, i) => (
                  <SelectItem key={m.deviceId || i} value={m.deviceId || `mic-${i}`}>
                    {m.label || `Микрофон ${i + 1}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="h-2 overflow-hidden rounded-full bg-secondary" aria-label="Уровень микрофона">
              <div
                className={`h-full transition-[width] duration-75 ${level > 0.6 ? "bg-warning" : "bg-success"}`}
                style={{ width: `${Math.round(level * 100)}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {level < 0.03 ? "Скажите что-нибудь — полоска должна двигаться." : "Микрофон слышит вас."}
            </p>
          </div>
          {virtualCamera ? (
            <p className="rounded-md bg-warning/10 p-2 text-xs">
              Выбрана виртуальная камера. Интервью пройти можно, но рекрутер увидит пометку.
            </p>
          ) : null}
        </div>
      </div>

      <div className="rounded-lg border p-4">
        <p className="text-sm font-medium">Пробная запись</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Запишите 5 секунд и прослушайте — так вы убедитесь, что вас видно и слышно.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {testState === "recording" ? (
            <Button variant="outline" onClick={stopTest}>
              <Square className="mr-2 h-4 w-4" /> Остановить
            </Button>
          ) : (
            <Button variant="outline" onClick={startTest} disabled={!stream}>
              <Play className="mr-2 h-4 w-4" /> {testUrl ? "Записать ещё раз" : "Записать 5 секунд"}
            </Button>
          )}
          {testState === "recording" ? <span className="text-sm text-destructive">● Идёт запись…</span> : null}
        </div>
        {testUrl ? (
          <div className="mt-3 space-y-2">
            <video src={testUrl} controls playsInline className="w-full max-w-sm rounded-md bg-black" />
          </div>
        ) : null}
      </div>

      <Button
        size="lg"
        className="w-full"
        disabled={!stream || !heardOk}
        onClick={() => { if (stream) { handedOff.current = true; onReady({ stream, environment, devices, virtualCamera }); } }}
      >
        <Check className="mr-2 h-4 w-4" />
        Всё готово — к интервью
      </Button>
      <div className="flex justify-center py-1">
        <Checkbox checked={heardOk} onCheckedChange={setHeardOk} disabled={!testUrl}>
          Меня видно и слышно
        </Checkbox>
      </div>
      {!heardOk ? (
        <p className="text-center text-xs text-muted-foreground">
          Сделайте пробную запись и подтвердите, что вас видно и слышно.
        </p>
      ) : null}
    </div>
  );
}
