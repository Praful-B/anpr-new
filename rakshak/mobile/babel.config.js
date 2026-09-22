/**
 * @module babel.config
 * Babel configuration for the RAKSHAK Expo mobile app.
 *
 * Uses the Expo preset with module resolution alias support.
 */

module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
  };
};
