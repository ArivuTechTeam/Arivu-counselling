import Link from "next/link";

export default function TermsPage() {
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-6 py-16 text-foreground">
      <Link href="/login" className="text-sm font-medium text-primary hover:underline">
        ← Back to sign in
      </Link>
      <h1 className="mt-8 text-3xl font-bold">Terms of Service</h1>
      <p className="mt-2 text-sm text-muted-foreground">Last updated: 18 September 2026</p>
      <div className="mt-8 space-y-6 leading-7 text-muted-foreground">
        <p>ArivuPro provides learning and assessment tools for participating institutions. Use the service only for lawful educational purposes and keep your account credentials private.</p>
        <p>Your institution controls access to its courses, quizzes, and teaching material. Quiz results are educational records and must not be copied, shared, or used to impersonate another user.</p>
        <p>AI-assisted content must be reviewed by a teacher before publication. The platform may change or suspend features to protect learners, institutions, or the service.</p>
        <p>For account, course, or assessment questions, contact your institution administrator.</p>
      </div>
    </main>
  );
}
