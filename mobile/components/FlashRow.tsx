import { useEffect, useRef, type ReactNode } from "react";
import {
  Animated,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

interface FlashRowProps {
  /** Change this (e.g. a data fingerprint) to trigger a one-shot flash. */
  flashKey: string;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** Highlight tint (defaults to the same blue as the web row-update flash). */
  color?: string;
  /** Fade duration in ms (matches the web ~1.6s held flash). */
  duration?: number;
}

/**
 * Wraps a table row and briefly flashes a background highlight that fades over
 * ~1.6s whenever ``flashKey`` changes — used to surface background/progressive
 * data updates (mobile parity with the web ``row-updated`` flash). The initial
 * mount never flashes; only subsequent value changes do.
 */
export function FlashRow({
  flashKey,
  children,
  style,
  color = "rgba(96, 165, 250, 0.16)",
  duration = 1500,
}: FlashRowProps) {
  const opacity = useRef(new Animated.Value(0)).current;
  const prevKey = useRef<string | null>(null);

  useEffect(() => {
    if (prevKey.current === null) {
      // First mount — record the baseline, don't flash.
      prevKey.current = flashKey;
      return;
    }
    if (prevKey.current === flashKey) return;
    prevKey.current = flashKey;
    opacity.setValue(1);
    const animation = Animated.timing(opacity, {
      toValue: 0,
      duration,
      useNativeDriver: true,
    });
    animation.start();
    return () => animation.stop();
  }, [flashKey, opacity, duration]);

  return (
    <View style={style}>
      <Animated.View
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, { backgroundColor: color, opacity }]}
      />
      {children}
    </View>
  );
}
