/**
 * @module crypto
 * AES-256-GCM decryption helpers for the encrypted hotlist payload.
 *
 * The backend encrypts the plate list with a per-device key derived via
 * HKDF-SHA256 and delivered as base64 at device registration. Decryption
 * happens in memory only; the plaintext plate list is never persisted.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** AES key length in bytes (AES-256). */
export const AES_KEY_LENGTH_BYTES = 32;

/** GCM IV length in bytes as produced by the backend. */
export const AES_GCM_IV_LENGTH_BYTES = 12;

/** Web Crypto algorithm descriptor for AES-256-GCM. */
const AES_GCM_ALGORITHM = "AES-GCM";

// ---------------------------------------------------------------------------
// Base64 helpers
// ---------------------------------------------------------------------------

/**
 * Decode a base64 string into a byte array.
 *
 * @param base64 - The base64-encoded input.
 * @returns The decoded bytes.
 */
export function base64ToUint8Array(base64: string): Uint8Array {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let index = 0; index < binaryString.length; index += 1) {
    bytes[index] = binaryString.charCodeAt(index);
  }
  return bytes;
}

// ---------------------------------------------------------------------------
// Decryption
// ---------------------------------------------------------------------------

/**
 * Decrypt an AES-256-GCM ciphertext into its UTF-8 plaintext string.
 *
 * @param ivBase64 - Base64-encoded 12-byte initialisation vector.
 * @param ciphertextBase64 - Base64-encoded ciphertext (tag appended).
 * @param keyBase64 - Base64-encoded 32-byte AES-256 key.
 * @returns The decrypted UTF-8 plaintext.
 * @throws Error when the key length is wrong or authentication fails.
 */
export async function decryptAesGcm(
  ivBase64: string,
  ciphertextBase64: string,
  keyBase64: string
): Promise<string> {
  const keyBytes = base64ToUint8Array(keyBase64);
  if (keyBytes.length !== AES_KEY_LENGTH_BYTES) {
    throw new Error(
      `Device key must be ${AES_KEY_LENGTH_BYTES} bytes, got ${keyBytes.length}`
    );
  }

  const iv = base64ToUint8Array(ivBase64);
  if (iv.length !== AES_GCM_IV_LENGTH_BYTES) {
    throw new Error(
      `IV must be ${AES_GCM_IV_LENGTH_BYTES} bytes, got ${iv.length}`
    );
  }

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: AES_GCM_ALGORITHM, length: AES_KEY_LENGTH_BYTES * 8 },
    false,
    ["decrypt"]
  );

  const plaintextBuffer = await crypto.subtle.decrypt(
    { name: AES_GCM_ALGORITHM, iv },
    cryptoKey,
    base64ToUint8Array(ciphertextBase64)
  );

  return new TextDecoder().decode(plaintextBuffer);
}
