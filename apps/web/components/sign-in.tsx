"use client";
import { useState, type FormEvent } from "react";
import { signInWithEmailAndPassword, signOut } from "firebase/auth";
import { AnnotationStudio } from "./annotation-studio";
import { AssessmentWorkspace } from "./assessment-workspace";
import { tutorAuth } from "../lib/firebase";

type Activity = { id: string; actor_role: string | null; target: string; outcome: string; created_at: string };
const activityLabels: Record<string, string> = { "/v1/auth/me": "Sign-in check", "/v1/student/account": "Student account", "/v1/student/accounts/{account_id}": "Student account", "/v1/admin/access": "Maintainer access", "/v1/admin/audit": "Activity review" };
Object.assign(activityLabels, {
  "/v1/admin/knowledge/upload": "Maintainer source upload",
  "/v1/admin/knowledge/{resource_id}/file": "Maintainer source download",
  "/v1/admin/knowledge/{resource_id}/status": "Source processing status",
  "/v1/admin/studio/sources": "Source documents",
  "/v1/admin/studio/sources/{document_id}/render": "Prepare source pages",
  "/v1/admin/studio/sources/{document_id}/pages": "Source page review",
  "/v1/admin/studio/sources/{document_id}/pages/{number}/image": "Source page image",
  "/v1/admin/studio/sources/{document_id}/annotations": "Annotation review or save",
  "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}": "Annotation edit",
  "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/crop": "Annotation source crop",
  "/v1/student/assessments/upload": "Student PDF upload",
  "/v1/student/assessments/{assessment_id}/pages": "Student page review",
  "/v1/student/assessments/{assessment_id}/pages/{page_number}/image": "Student page image",
});
type Session = { role: "student" | "admin"; accountId?: string };
export function SignIn() {
  const [session, setSession] = useState<Session | null>(null);
  const [activity, setActivity] = useState<Activity[] | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const auth = await tutorAuth();
      const result = await signInWithEmailAndPassword(auth, String(data.get("email")), String(data.get("password")));
      const headers = { Authorization: `Bearer ${await result.user.getIdToken()}` };
      const identity = await fetch("/api/auth/me", { headers, cache: "no-store" });
      if (!identity.ok) throw new Error("Sign-in failed");
      const { role } = await identity.json();
      const access = await fetch(role === "admin" ? "/api/auth/maintainer" : "/api/auth/account", { headers, cache: "no-store" });
      if (!access.ok) throw new Error("Access failed");
      const account = await access.json();
      setSession({ role, accountId: account.id }); form.reset();
    } catch {
      try { await signOut(await tutorAuth()); } catch {}
      setSession(null); setMessage("Unable to sign in. Check your credentials or try again.");
    } finally { setBusy(false); }
  }
  async function logout() {
    setBusy(true);
    try { await signOut(await tutorAuth()); setSession(null); setActivity(null); setMessage(""); }
    catch { setMessage("Unable to sign out. Try again."); }
    finally { setBusy(false); }
  }
  async function loadActivity() {
    setBusy(true); setMessage("");
    try {
      const user = (await tutorAuth()).currentUser;
      if (!user) throw new Error("Sign-in required");
      const response = await fetch("/api/auth/audit", { headers: { Authorization: `Bearer ${await user.getIdToken()}` }, cache: "no-store" });
      if (!response.ok) throw new Error("Activity unavailable");
      setActivity(await response.json());
    } catch { setActivity(null); setMessage("Unable to load recent activity. Try again."); }
    finally { setBusy(false); }
  }
  return <section className="mt-8 rounded-2xl border border-emerald-900/15 bg-white p-8" aria-labelledby="signin-title">
    <h2 id="signin-title" className="text-2xl font-semibold">{session ? "Your workspace" : "Sign in"}</h2>
    {session ? <><p role="status" className="mt-4">{session.role === "admin" ? "Maintainer access verified." : "Student access verified. Your account is private to you."}</p>
      {session.role === "student" ? <AssessmentWorkspace /> : <AnnotationStudio />}
      {session.role === "admin" && <button disabled={busy} onClick={loadActivity} className="mt-6 mr-4 rounded-lg border border-emerald-900 px-5 py-3 disabled:opacity-50">View recent activity</button>}
      {activity && <div className="mt-6 overflow-x-auto"><h3 className="font-semibold">Recent activity</h3><table className="mt-3 w-full text-left text-sm"><thead><tr><th className="py-2">Role</th><th>Action</th><th>Result</th></tr></thead><tbody>{activity.slice(0, 10).map(event => <tr key={event.id} className="border-t border-slate-200"><td className="py-2">{event.actor_role ?? "Signed out"}</td><td>{activityLabels[event.target] ?? "Unknown route"}</td><td>{event.outcome === "success" ? "Allowed" : event.outcome === "denied" ? "Denied" : "Failed"}</td></tr>)}</tbody></table></div>}
      <button disabled={busy} onClick={logout} className="mt-6 rounded-lg bg-emerald-900 px-5 py-3 text-white disabled:opacity-50">Sign out</button></>
      : <form onSubmit={submit} className="mt-6 grid gap-4 max-w-md">
        <label className="grid gap-2">Email<input name="email" type="email" required autoComplete="username" className="rounded-lg border border-slate-300 px-3 py-2" /></label>
        <label className="grid gap-2">Password<input name="password" type="password" required autoComplete="current-password" className="rounded-lg border border-slate-300 px-3 py-2" /></label>
        <button disabled={busy} className="rounded-lg bg-emerald-900 px-5 py-3 text-white disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button>
        <p className="text-sm text-slate-600">Use an account provisioned by the maintainer.</p>
      </form>}
    {message && <p role="alert" className="mt-4 text-red-800">{message}</p>}
  </section>;
}
