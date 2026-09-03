import Link from "next/link";

export function UnavailablePage({ title, message }: { title: string; message: string }) {
  return (
    <div className="internal-page container-page py-16 md:py-24">
      <div className="card max-w-2xl mx-auto p-7 md:p-10 text-center border-t-4 border-t-amber-400">
        <h1 className="text-xl md:text-2xl font-black text-neutral-900">{title}</h1>
        <p className="text-sm text-neutral-500 leading-7 mt-3">{message}</p>
        <Link href="/" className="inline-flex mt-6 text-sm font-semibold text-brand-navy hover:text-amber-700">
          بازگشت به صفحه اصلی
        </Link>
      </div>
    </div>
  );
}
