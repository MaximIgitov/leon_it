/*
 * Доступ к камере и микрофону: проверка окружения, запрос разрешений и
 * подсказки по браузерам. Всё, что можно узнать до getUserMedia, узнаём заранее,
 * чтобы объяснить кандидату проблему словами, а не «NotAllowedError».
 */

export type Browser = "chrome" | "safari" | "firefox" | "edge" | "yandex" | "samsung" | "other";
export type Platform = "ios" | "android" | "macos" | "windows" | "linux" | "other";

export type Environment = {
  browser: Browser;
  platform: Platform;
  mobile: boolean;
  secureContext: boolean;
  mediaDevicesSupported: boolean;
  mediaRecorderSupported: boolean;
  userAgent: string;
};

export function detectEnvironment(): Environment {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  const lower = ua.toLowerCase();
  let browser: Browser = "other";
  if (lower.includes("yabrowser")) browser = "yandex";
  else if (lower.includes("samsungbrowser")) browser = "samsung";
  else if (lower.includes("edg/")) browser = "edge";
  else if (lower.includes("firefox") || lower.includes("fxios")) browser = "firefox";
  else if (lower.includes("crios") || (lower.includes("chrome") && !lower.includes("edg/"))) browser = "chrome";
  else if (lower.includes("safari")) browser = "safari";

  let platform: Platform = "other";
  const iPadOs = lower.includes("macintosh") && typeof navigator !== "undefined" && navigator.maxTouchPoints > 1;
  if (/iphone|ipad|ipod/.test(lower) || iPadOs) platform = "ios";
  else if (lower.includes("android")) platform = "android";
  else if (lower.includes("mac os")) platform = "macos";
  else if (lower.includes("windows")) platform = "windows";
  else if (lower.includes("linux")) platform = "linux";

  return {
    browser,
    platform,
    mobile: platform === "ios" || platform === "android",
    secureContext: typeof window !== "undefined" ? window.isSecureContext : false,
    mediaDevicesSupported:
      typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia),
    mediaRecorderSupported: typeof window !== "undefined" && "MediaRecorder" in window,
    userAgent: ua,
  };
}

export type PermissionFailure = {
  kind: "denied" | "not_found" | "in_use" | "insecure" | "unsupported" | "unknown";
  title: string;
  steps: string[];
};

const BROWSER_NAMES: Record<Browser, string> = {
  chrome: "Chrome",
  safari: "Safari",
  firefox: "Firefox",
  edge: "Edge",
  yandex: "Яндекс Браузер",
  samsung: "Samsung Internet",
  other: "браузер",
};

/** Инструкции, как вернуть доступ к камере и микрофону после отказа. */
export function deniedSteps(env: Environment): string[] {
  if (env.platform === "ios") {
    return [
      "Откройте «Настройки» iPhone → прокрутите до Safari (или вашего браузера).",
      "В разделе «Камера» и «Микрофон» выберите «Разрешить» или «Спрашивать».",
      "Вернитесь на эту страницу и нажмите «Проверить снова».",
    ];
  }
  if (env.platform === "android") {
    return [
      "Нажмите на значок замка слева от адреса сайта.",
      "Откройте «Разрешения» и включите камеру и микрофон.",
      "Если пунктов нет — «Настройки» Android → «Приложения» → браузер → «Разрешения».",
    ];
  }
  if (env.browser === "safari") {
    return [
      "В меню Safari выберите «Настройки для этого сайта…» (или Safari → Настройки → Веб-сайты).",
      "Для камеры и микрофона выберите «Разрешить».",
      "Перезагрузите страницу.",
    ];
  }
  if (env.browser === "firefox") {
    return [
      "Нажмите на значок камеры/замка в адресной строке.",
      "Уберите блокировку для камеры и микрофона (крестик рядом с «Заблокировано»).",
      "Нажмите «Проверить снова» — Firefox спросит разрешение ещё раз.",
    ];
  }
  const name = BROWSER_NAMES[env.browser];
  const steps = [
    `Нажмите на значок замка (или настроек сайта) слева от адреса в ${name}.`,
    "Установите «Камера» и «Микрофон» в «Разрешить».",
    "Перезагрузите страницу или нажмите «Проверить снова».",
  ];
  if (env.platform === "macos") {
    steps.push(
      "Если браузер не показывает камеру вовсе: Системные настройки → Конфиденциальность и безопасность → Камера/Микрофон → включите браузер.",
    );
  }
  if (env.platform === "windows") {
    steps.push(
      "Если камеры нет в списке: Параметры Windows → Конфиденциальность → Камера/Микрофон → разрешите доступ приложениям и браузеру.",
    );
  }
  return steps;
}

export function describeFailure(error: unknown, env: Environment): PermissionFailure {
  if (!env.secureContext) {
    return {
      kind: "insecure",
      title: "Страница открыта не по HTTPS",
      steps: ["Браузер даёт доступ к камере только на защищённых страницах. Откройте ссылку из письма ещё раз — она начинается с https://."],
    };
  }
  if (!env.mediaDevicesSupported || !env.mediaRecorderSupported) {
    return {
      kind: "unsupported",
      title: "Браузер не поддерживает запись видео",
      steps: [
        "Откройте ссылку в актуальном Chrome, Firefox, Edge или Safari.",
        env.platform === "ios"
          ? "На iPhone и iPad запись работает в Safari — в других браузерах iOS могут быть ограничения."
          : "Обновите браузер до последней версии.",
      ],
    };
  }
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") {
    return { kind: "denied", title: "Доступ к камере или микрофону запрещён", steps: deniedSteps(env) };
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
    return {
      kind: "not_found",
      title: "Камера или микрофон не найдены",
      steps: [
        "Подключите камеру и микрофон (или гарнитуру) и нажмите «Проверить снова».",
        "На ноутбуке убедитесь, что камера не выключена аппаратно (шторка, клавиша Fn).",
      ],
    };
  }
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") {
    return {
      kind: "in_use",
      title: "Устройство занято другой программой",
      steps: [
        "Закройте Zoom, Teams, Telegram и другие приложения с видеозвонками.",
        "Закройте другие вкладки, где используется камера, и нажмите «Проверить снова».",
      ],
    };
  }
  return {
    kind: "unknown",
    title: "Не удалось включить камеру",
    steps: ["Перезагрузите страницу.", "Если не помогло — попробуйте другой браузер или устройство."],
  };
}

export type DeviceInfo = { deviceId: string; label: string; kind: MediaDeviceKind };

export async function listDevices(): Promise<DeviceInfo[]> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.map((d) => ({ deviceId: d.deviceId, label: d.label, kind: d.kind }));
}

/** Метки виртуальных камер — интересны integrity-анализу, не блокируют интервью. */
export const VIRTUAL_CAMERA_MARKERS = ["obs", "virtual", "manycam", "xsplit", "snap camera", "droidcam"];

export function isVirtualCamera(label: string): boolean {
  const lower = label.toLowerCase();
  return VIRTUAL_CAMERA_MARKERS.some((marker) => lower.includes(marker));
}

export const VIDEO_CONSTRAINTS: MediaTrackConstraints = {
  width: { ideal: 854 },
  height: { ideal: 480 },
  frameRate: { ideal: 24, max: 30 },
  facingMode: "user",
};

export const AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

export async function requestMedia(deviceIds?: { video?: string; audio?: string }): Promise<MediaStream> {
  const video: MediaTrackConstraints = { ...VIDEO_CONSTRAINTS };
  const audio: MediaTrackConstraints = { ...AUDIO_CONSTRAINTS };
  if (deviceIds?.video) video.deviceId = { exact: deviceIds.video };
  if (deviceIds?.audio) audio.deviceId = { exact: deviceIds.audio };
  return navigator.mediaDevices.getUserMedia({ video, audio });
}

export function stopStream(stream: MediaStream | null | undefined): void {
  stream?.getTracks().forEach((track) => track.stop());
}
