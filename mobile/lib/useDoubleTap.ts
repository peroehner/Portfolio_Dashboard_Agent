import { useRef } from "react";

export function useDoubleTap(onDoubleTap: () => void, delayMs = 320) {
  const lastTap = useRef(0);

  return () => {
    const now = Date.now();
    if (now - lastTap.current < delayMs) {
      onDoubleTap();
      lastTap.current = 0;
      return;
    }
    lastTap.current = now;
  };
}
