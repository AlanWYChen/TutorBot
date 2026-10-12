import { getApiHealth } from "../lib/health";
import { SignIn } from "../components/sign-in";
export const dynamic = "force-dynamic";
export default async function Home() {
  const health = await getApiHealth(process.env.API_INTERNAL_URL ?? "http://localhost:8000");
  return <main className="mx-auto max-w-5xl px-6 py-16">
    <p className="text-sm font-bold tracking-widest uppercase">TutorBot · Development</p>
    <h1 className="mt-12 text-5xl font-semibold tracking-tight">Understand your work.<br/>Build your next step.</h1>
    <p className="mt-6 max-w-xl text-lg leading-8">Mathematics tutoring grounded in your own work, clear evidence, and approved teaching methods.</p>
    <section className="mt-12 rounded-2xl border border-emerald-900/15 bg-white p-8" aria-labelledby="status-title">
      <h2 id="status-title" className="text-2xl font-semibold">Local services</h2>
      <p role="status" className="mt-4">{health.status === "ok" ? "Local services are ready." : "Local services are unavailable. Check the development stack."}</p>
      <p className="mt-4 text-sm leading-6 text-slate-600">Sign in to upload and view your mathematics work. Tutoring and the teaching studio arrive in later reviewed steps.</p>
    </section>
    <SignIn />
    <p className="mt-8 text-sm">Initial scope: Ontario Grade 11 mathematics · IB Math AA SL IA context</p>
  </main>;
}
