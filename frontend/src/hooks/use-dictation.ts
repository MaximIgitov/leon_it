import { useEffect, useRef, useState } from "react";

type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean;
  onstart: (() => void) | null;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
};
type SpeechWindow = Window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };

export function useDictation(input: string, onChange: (value: string) => void) {
  const ref = useRef<Recognition | null>(null);
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const w = window as SpeechWindow;
    setSupported(Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition));
    return () => { if (ref.current) { ref.current.onend = null; ref.current.abort(); } };
  }, []);
  const stop = () => ref.current?.stop();
  const toggle = () => {
    if (listening) { stop(); return; }
    const w = window as SpeechWindow;
    const Constructor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Constructor) return;
    const recognition = new Constructor();
    const base = input.trimEnd();
    recognition.lang = "ru-RU";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onstart = () => { setListening(true); setError(null); };
    recognition.onresult = event => onChange((base + (base ? " " : "") + Array.from(event.results).map(result => result[0]?.transcript ?? "").join("")).slice(0, 8000));
    recognition.onerror = event => setError(event.error === "not-allowed" ? "Разрешите доступ к микрофону в браузере" : "Не удалось распознать речь");
    recognition.onend = () => { setListening(false); ref.current = null; };
    ref.current = recognition;
    try { recognition.start(); } catch { ref.current = null; setListening(false); setError("Не удалось запустить микрофон"); }
  };
  return { supported, listening, error, toggle, stop };
}
