import { getApps, initializeApp } from "firebase/app";
import { connectAuthEmulator, getAuth, inMemoryPersistence, setPersistence } from "firebase/auth";

export async function tutorAuth() {
  // Runtime public config contains no proxy/provider/admin credentials.
  const response = await fetch("/api/auth-config", { cache: "no-store" });
  if (!response.ok) throw new Error("Sign-in unavailable");
  const config: { apiKey: string; projectId: string; emulatorUrl: string | null } = await response.json();
  const existing = getApps()[0];
  const app = existing ?? initializeApp({ apiKey: config.apiKey, projectId: config.projectId });
  const auth = getAuth(app);
  if (!existing && config.emulatorUrl) connectAuthEmulator(auth, config.emulatorUrl, { disableWarnings: true });
  await setPersistence(auth, inMemoryPersistence);
  return auth;
}
