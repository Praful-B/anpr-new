/**
 * @module leaflet-heat
 * Type declarations for the leaflet.heat plugin which augments
 * the Leaflet namespace with `heatLayer()` at runtime.
 */

import * as L from "leaflet";

declare module "leaflet" {
  /**
   * Options for the heat layer.
   */
  interface HeatLayerOptions {
    /** Maximum intensity of a single point. Default: undefined (auto). */
    max?: number;
    /** Minimum opacity. Default: 0.05. */
    minOpacity?: number;
    /** Maximum zoom level where the radius is applied. Default: undefined. */
    maxZoom?: number;
    /** Heat radius in pixels. Default: 25. */
    radius?: number;
    /** Heat blur factor in pixels. Default: 15. */
    blur?: number;
    /** Gradient colour stops. Default: Jet-like gradient. */
    gradient?: Record<number, string>;
  }

  /**
   * Creates a new heat map layer from an array of [lat, lng, intensity] points.
   *
   * @param latlngs - Array of coordinate triples with optional intensity.
   * @param options - Heat layer configuration.
   * @returns A new Leaflet heat layer.
   */
  function heatLayer(
    latlngs: Array<[number, number, number?]>,
    options?: HeatLayerOptions,
  ): HeatLayer;

  /**
   * A Leaflet layer that renders a heatmap from point data.
   */
  class HeatLayer extends Layer {
    /** Replace the underlying point data. */
    setLatLngs(latlngs: Array<[number, number, number?]>): this;
    /** Add a single point to the existing data. */
    addLatLng(latlng: [number, number, number?]): this;
  }
}
