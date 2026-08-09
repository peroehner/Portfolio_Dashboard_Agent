import { useCallback, useEffect, useState } from "react";
import { Alert, Pressable, StyleSheet, Text } from "react-native";

import { api, getApiBaseUrl, getApiHostLabel } from "@/lib/api";
import { colors } from "@/lib/theme";
import type { ApiConfig } from "@/lib/types";

export type AboutSessionDetails = {
  email?: string | null;
  pricesAsOf?: string | null;
  refreshedAt?: string | null;
};

function formatAboutMessage(
  config: ApiConfig | null,
  session: AboutSessionDetails | undefined,
  error?: string | null,
): string {
  if (error) {
    const bits = [`Could not load API config.`, error, `Client → ${getApiHostLabel()}`];
    if (session?.email) bits.push(`Signed in: ${session.email}`);
    return bits.join("\n\n");
  }
  const deploy = config?.deploy;
  const lines: string[] = [];
  if (session?.email) lines.push(`Signed in: ${session.email}`);
  if (session?.pricesAsOf) lines.push(`Data session: ${session.pricesAsOf}`);
  if (session?.refreshedAt) lines.push(`Refreshed: ${session.refreshedAt}`);
  if (lines.length) lines.push("");

  lines.push(
    `App v${config?.appVersion || deploy?.appVersion || "1.0"}`,
    `Environment: ${config?.environment || deploy?.environment || "—"}`,
    `Build (git): ${config?.build || deploy?.build || "—"}`,
    `Git commit: ${config?.gitCommit || deploy?.gitCommit || "—"}`,
    `Branch: ${config?.gitBranch || deploy?.gitBranch || "—"}`,
    `API host: ${config?.host || deploy?.host || getApiHostLabel()}`,
    `Client → ${getApiHostLabel()}`,
    `Base URL: ${getApiBaseUrl()}`,
  );
  const serviceId = config?.serviceId || deploy?.serviceId;
  const serviceName = config?.serviceName || deploy?.serviceName;
  if (serviceName || serviceId) {
    lines.push(`Render service: ${[serviceName, serviceId].filter(Boolean).join(" · ")}`);
  }
  if (config?.assessmentProvider) {
    const model = config.geminiModel?.trim();
    lines.push(
      model
        ? `Assessment: ${config.assessmentProvider} + ${model}`
        : `Assessment: ${config.assessmentProvider}`,
    );
  }
  return lines.join("\n");
}

/** Compact “i” control (web-style) — account + API deploy fingerprint. */
export function AboutApiButton({ session }: { session?: AboutSessionDetails }) {
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.config();
      setConfig(next);
      setLoadError(null);
      return next;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load /config";
      setLoadError(message);
      return null;
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function openAbout() {
    const latest = (await refresh()) ?? config;
    Alert.alert(
      "About",
      formatAboutMessage(latest, session, loadError && !latest ? loadError : null),
    );
  }

  return (
    <Pressable
      style={styles.btn}
      onPress={() => void openAbout()}
      accessibilityRole="button"
      accessibilityLabel="About account and API build"
      hitSlop={10}
    >
      <Text style={styles.btnMark}>i</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  btnMark: {
    color: colors.link,
    fontSize: 13,
    fontWeight: "800",
    lineHeight: 16,
  },
});
