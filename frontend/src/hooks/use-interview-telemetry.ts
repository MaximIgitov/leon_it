"use client";

import { useCallback, useEffect, useRef } from "react";

import { roomApi, type ClientEvent } from "@/lib/api/room";

/*
 * Телеметрия комнаты: уход с вкладки, потеря фокуса, полноэкранный режим,
 * вставка текста, смена устройств и хартбит раз в 5 с. События копятся и
 * уходят батчами; ничего не блокирует интервью — это только факты для отчёта.
 */
export function useInterviewTelemetry(
  token: string | null,
  getContext: () => { questionIndex?: number; answerId?: string },
  enabled: boolean,
) {
  const buffer = useRef<ClientEvent[]>([]);
  const flushing = useRef(false);

  const push = useCallback(
    (kind: string, payload?: Record<string, unknown>) => {
      const context = getContext();
      buffer.current.push({
        kind,
        at_client_ms: Math.round(performance.now()),
        question_index: context.questionIndex,
        answer_id: context.answerId,
        payload,
      });
    },
    [getContext],
  );

  const flush = useCallback(async () => {
    if (!token || flushing.current || buffer.current.length === 0) return;
    flushing.current = true;
    const batch = buffer.current.splice(0, 200);
    try {
      await roomApi.events(token, batch);
    } catch {
      // Вернём в буфер, отправим со следующим батчем.
      buffer.current.unshift(...batch);
    } finally {
      flushing.current = false;
    }
  }, [token]);

  useEffect(() => {
    if (!enabled || !token) return;
    const mobile = /iphone|ipad|android/i.test(navigator.userAgent);
    const onVisibility = () => {
      if (document.visibilityState === "hidden") push(mobile ? "mobile_pause" : "visibility_hidden");
      else push(mobile ? "mobile_resume" : "visibility_visible");
    };
    const onBlur = () => push("window_blur");
    const onFocus = () => push("window_focus");
    const onFullscreen = () => push(document.fullscreenElement ? "fullscreen_enter" : "fullscreen_exit");
    const onPaste = (event: ClipboardEvent) =>
      push("paste", { length: event.clipboardData?.getData("text")?.length ?? 0 });
    const onCopy = () => push("copy");
    const onDeviceChange = () => push("device_change");

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    document.addEventListener("fullscreenchange", onFullscreen);
    document.addEventListener("paste", onPaste);
    document.addEventListener("copy", onCopy);
    navigator.mediaDevices?.addEventListener?.("devicechange", onDeviceChange);

    const heartbeat = setInterval(() => {
      push("heartbeat");
      void flush();
    }, 5000);
    const flusher = setInterval(() => void flush(), 3000);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("fullscreenchange", onFullscreen);
      document.removeEventListener("paste", onPaste);
      document.removeEventListener("copy", onCopy);
      navigator.mediaDevices?.removeEventListener?.("devicechange", onDeviceChange);
      clearInterval(heartbeat);
      clearInterval(flusher);
      void flush();
    };
  }, [enabled, token, push, flush]);

  return { push, flush };
}
