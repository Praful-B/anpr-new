/**
 * Jest configuration for the RAKSHAK mobile app.
 *
 * Only the dependency-free pure logic modules (src/ai, src/components helpers)
 * are tested here. React Native screens and Expo modules are exercised on a
 * device or emulator, where the native runtime exists.
 */

/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/src"],
  testMatch: ["**/__tests__/**/*.test.ts"],
  moduleFileExtensions: ["ts", "tsx", "js", "json"],
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        tsconfig: {
          strict: true,
          noUncheckedIndexedAccess: true,
          esModuleInterop: true,
          types: ["jest", "node"],
        },
        diagnostics: false,
      },
    ],
  },
};
