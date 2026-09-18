import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-6 py-16 text-foreground">
      <Link href="/login" className="text-sm font-medium text-primary hover:underline">
        ← Back to sign in
      </Link>
      <h1 className="mt-8 text-3xl font-bold">Privacy Policy</h1>
      <p className="mt-2 text-sm text-muted-foreground">Last updated: 18 September 2026</p>
      <div className="mt-8 space-y-6 leading-7 text-muted-foreground">
        <p>ArivuPro processes account details, course enrolments, quiz attempts, and institution-provided teaching material to deliver learning and assessment features.</p>
        <p>Access to institution data is restricted by role and institution. Students can access their own learning activity; teachers and administrators receive only the access needed for their duties.</p>
        <p>We use authorised service providers to host the application, authentication, database, and file storage. Do not upload sensitive personal information unless your institution has approved it.</p>
        <p>To request account support or deletion, contact your institution administrator. Students can also use the account-deletion option available from their dashboard.</p>
      </div>
    </main>
  );
}
