import { Alert } from "react-native";

export function promptToggleStar(
  symbol: string,
  isStarred: boolean,
  toggle: () => void,
): void {
  const sym = String(symbol || "").trim().toUpperCase();
  if (!sym) return;
  Alert.alert(
    isStarred ? `Unstar ${sym}?` : `Star ${sym}?`,
    isStarred
      ? "Remove from starred filter (*)."
      : "Include in starred filter (*). Filter with * or +* (AND).",
    [
      { text: "Cancel", style: "cancel" },
      { text: isStarred ? "Unstar" : "Star", onPress: toggle },
    ],
  );
}
