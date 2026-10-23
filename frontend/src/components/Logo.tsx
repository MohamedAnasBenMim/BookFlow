import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 font-display text-xl font-semibold tracking-tight">
      <span aria-hidden className="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm text-accent-fg">
        B
      </span>
      BookFlow
    </Link>
  );
}
