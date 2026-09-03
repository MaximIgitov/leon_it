import { ImageResponse } from "next/og";

export const runtime = "edge";
export const size = { width: 64, height: 64 };
export const contentType = "image/png";

// Фавиконка генерируется из знака логотипа, чтобы не хранить бинарник в репозитории.
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#140AF0",
          borderRadius: 14,
        }}
      >
        <svg viewBox="0 0 256 256" width="64" height="64">
          <path d="M66 50h34v122h90v34H66V50z" fill="#ffffff" />
        </svg>
      </div>
    ),
    size,
  );
}
