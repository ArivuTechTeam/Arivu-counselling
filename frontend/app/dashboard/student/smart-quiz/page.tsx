import { redirect } from "next/navigation";

export default async function SmartQuizRedirect({
  searchParams,
}: {
  searchParams?: Promise<{ institution?: string | string[] }>;
}) {
  const resolvedSearchParams = await searchParams;
  const params = new URLSearchParams({ mode: "topic" });
  if (typeof resolvedSearchParams?.institution === "string") {
    params.set("institution", resolvedSearchParams.institution);
  }
  redirect(`/dashboard/student/practice?${params.toString()}`);
}
