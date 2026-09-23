import type { CSSProperties } from "react";

export const DEFAULT_INSTITUTION_COLOR = "#2E8857";

type ThemeStyle = CSSProperties & Record<`--${string}`, string>;

export function normalizeInstitutionColor(value?: string | null): string {
  const normalized = value?.trim().toUpperCase() ?? "";
  return /^#[0-9A-F]{6}$/.test(normalized)
    ? normalized
    : DEFAULT_INSTITUTION_COLOR;
}

function rgb(hex: string): [number, number, number] {
  return [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16)) as [number, number, number];
}

function mix(hex: string, target: "#000000" | "#FFFFFF", weight: number): string {
  const source = rgb(hex);
  const destination = rgb(target);
  return `#${source.map((channel, index) =>
    Math.round(channel + (destination[index] - channel) * weight)
      .toString(16)
      .padStart(2, "0"),
  ).join("")}`.toUpperCase();
}

function hsl(hex: string): [number, number, number] {
  const [red, green, blue] = rgb(hex).map((channel) => channel / 255);
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  let hue = 0;
  if (delta) {
    if (max === red) hue = 60 * (((green - blue) / delta) % 6);
    else if (max === green) hue = 60 * ((blue - red) / delta + 2);
    else hue = 60 * ((red - green) / delta + 4);
  }
  if (hue < 0) hue += 360;
  const lightness = (max + min) / 2;
  const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * lightness - 1));
  return [Math.round(hue), Math.round(saturation * 100), Math.round(lightness * 100)];
}

function luminance(hex: string): number {
  const channels = rgb(hex).map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

export function institutionThemeStyle(
  value?: string | null,
  includeSemanticTokens = true,
): ThemeStyle {
  const base = normalizeInstitutionColor(value);
  const baseLuminance = luminance(base);
  const sidebar = baseLuminance > 0.36 ? mix(base, "#000000", 0.28) : base;
  const dark = mix(sidebar, "#000000", 0.3);
  const deep = mix(sidebar, "#000000", 0.5);
  const soft = mix(base, "#FFFFFF", 0.9);
  const softer = mix(base, "#FFFFFF", 0.95);
  const [hue, saturation, lightness] = hsl(base);
  const controlLightness = Math.min(lightness, 48);
  const useDarkForeground = baseLuminance > 0.48;
  const foreground = useDarkForeground ? "156 22% 9%" : "0 0% 100%";

  const shared: ThemeStyle = {
    "--tenant-primary": base,
    "--tenant-sidebar-start": sidebar,
    "--tenant-primary-dark": dark,
    "--tenant-primary-deep": deep,
    "--tenant-primary-soft": soft,
    "--tenant-on-primary": useDarkForeground ? "#13231A" : "#FFFFFF",
    "--g900": deep,
    "--g800": dark,
    "--g700": base,
    "--g600": mix(base, "#FFFFFF", 0.14),
    "--g400": mix(base, "#FFFFFF", 0.35),
    "--g100": mix(base, "#FFFFFF", 0.78),
    "--g50": softer,
    "--bg": softer,
    "--bdr": mix(base, "#FFFFFF", 0.72),
    "--login-green": base,
    "--login-green-dark": dark,
    "--login-green-deep": deep,
    "--login-mint": softer,
  };
  if (!includeSemanticTokens) return shared;
  return {
    ...shared,
    "--primary": `${hue} ${saturation}% ${controlLightness}%`,
    "--primary-foreground": foreground,
    "--ring": `${hue} ${Math.max(30, saturation)}% ${controlLightness}%`,
    "--secondary": `${hue} ${Math.min(45, saturation)}% 95%`,
    "--accent": `${hue} ${Math.min(60, saturation)}% 91%`,
    "--accent-foreground": `${hue} ${Math.max(28, saturation)}% 28%`,
    "--border": `${hue} ${Math.min(52, saturation)}% 90%`,
    "--input": `${hue} ${Math.min(52, saturation)}% 90%`,
    "--background": `${hue} ${Math.min(38, saturation)}% 96%`,
  };
}
