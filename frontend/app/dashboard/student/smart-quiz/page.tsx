import { redirect } from "next/navigation";

export default function SmartQuizRedirect({
  searchParams,
}: {
  searchParams?: { institution?: string | string[] };
}) {
  const params = new URLSearchParams({ mode: "topic" });
  if (typeof searchParams?.institution === "string") {
    params.set("institution", searchParams.institution);
  }
  redirect(`/dashboard/student/practice?${params.toString()}`);
}
