import "@testing-library/jest-dom/vitest";

/**
 * jsdom implements no layout, so `scrollIntoView` does not exist on it. A
 * click handler that calls it throws an unhandled error that Vitest attributes
 * to whichever test file was running — noise that would sooner or later hide a
 * real one. A no-op is the right stand-in: there is nothing to scroll.
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
