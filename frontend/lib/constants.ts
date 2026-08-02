export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_DOHALM_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

export const STREAMING_ENABLED =
  process.env.NEXT_PUBLIC_DOHALM_STREAMING_ENABLED !== "false";

const configuredMaxTokens = Number(
  process.env.NEXT_PUBLIC_DOHALM_DEFAULT_MAX_NEW_TOKENS ?? 256,
);

export const DEFAULT_MAX_NEW_TOKENS =
  Number.isInteger(configuredMaxTokens) && configuredMaxTokens >= 1 && configuredMaxTokens <= 1024
    ? configuredMaxTokens
    : 256;

export const MAX_MESSAGE_LENGTH = 8000;
export const MAX_TOTAL_MESSAGE_LENGTH = 32000;
