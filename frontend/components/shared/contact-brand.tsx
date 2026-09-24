import Image from "next/image";

import { Building2 } from "@/components/ui/icons";

export function ContactBrand({
  destination,
  institution,
}: {
  destination: "platform" | "institution";
  institution: { name: string; logo_url: string | null } | null;
}) {
  if (destination === "platform") {
    return (
      <div className="flex min-h-12 items-center gap-3 rounded-xl border bg-white px-3 py-2 text-[#2E8857]">
        <Image src="/arivu-logo.png" alt="ArivuPro Academy" width={134} height={26} className="h-[26px] w-auto" />
        <span className="text-xs font-semibold">ArivuPro support</span>
      </div>
    );
  }

  return (
    <div className="flex min-h-12 items-center gap-3 rounded-xl border bg-card px-3 py-2">
      {institution?.logo_url ? (
        // The institution logo is a short-lived signed URL from the private bucket.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={institution.logo_url} alt={`${institution.name} logo`} className="h-8 max-w-28 object-contain" />
      ) : (
        <Building2 size={25} className="text-primary" />
      )}
      <span className="text-xs font-semibold text-foreground">
        {institution?.name ?? "Your institution"} support
      </span>
    </div>
  );
}
