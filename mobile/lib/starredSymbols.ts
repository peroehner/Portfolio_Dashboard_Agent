import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY = "pda.starredSymbols";

export async function loadStarredSymbols(): Promise<Set<string>> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.map((s) => String(s).trim().toUpperCase()).filter(Boolean));
  } catch {
    return new Set();
  }
}

export async function saveStarredSymbols(symbols: Set<string>): Promise<void> {
  const list = [...symbols].sort();
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}
