import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY = "pda.symbolFilter.last";

/** Last non-empty symbol filter sequence (comma-separated prefixes, *, +*). */
export async function loadLastSymbolFilter(): Promise<string> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    return typeof raw === "string" ? raw.trim() : "";
  } catch {
    return "";
  }
}

export async function saveLastSymbolFilter(filter: string): Promise<void> {
  const trimmed = filter.trim();
  if (!trimmed) return;
  try {
    await AsyncStorage.setItem(STORAGE_KEY, trimmed);
  } catch {
    // quota / private mode
  }
}
