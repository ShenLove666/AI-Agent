import "@testing-library/jest-dom/vitest";

// jsdom 缺少 ResizeObserver，图表类组件（Dashboard InsightSection 等）依赖它
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}
