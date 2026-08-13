import { Alert, Pressable, StyleSheet, Text, type StyleProp, type TextStyle } from "react-native";

import { signalHint, signalTooltip, type SignalKey, SIGNAL_GLOSSARY } from "@/lib/signalGlossary";
import { colors } from "@/lib/theme";

interface GlossaryHintProps {
  signal: SignalKey;
  /** Override visible label (defaults to glossary label). */
  label?: string;
  style?: StyleProp<TextStyle>;
  numberOfLines?: number;
}

/** Label that shows formula/meaning on long-press (mobile stand-in for hover). */
export function GlossaryHint({ signal, label, style, numberOfLines = 1 }: GlossaryHintProps) {
  const def = SIGNAL_GLOSSARY[signal];
  const text = label ?? def.label;
  return (
    <Pressable
      onLongPress={() => Alert.alert(def.label, `${def.formula}\n\n${def.meaning}`)}
      delayLongPress={280}
      accessibilityRole="text"
      accessibilityLabel={text}
      accessibilityHint={signalHint(signal)}
      hitSlop={6}
    >
      <Text
        style={[styles.label, style]}
        numberOfLines={numberOfLines}
        // Web: native title tooltip when running in browser.
        {...({ title: signalTooltip(signal) } as object)}
      >
        {text}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  label: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
});
