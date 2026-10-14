"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useOrganization } from "@/components/organization/Dashboard";
import PaymentPolicyAdmin from "./PaymentPolicyAdmin";
import { Empty, cx } from "./ui";
import s from "./proc.module.css";

export function OrgPaymentPolicy() {
  const o = useOrganization(true);
  if (!o.selected) return <div className={s.skeleton} style={{ height: 240 }} />;
  return <div className={s.root}><PaymentPolicyAdmin orgId={o.selected} /></div>;
}

export function AdminPaymentPolicy() {
  const org = useSearchParams().get("org");
  if (!org) return <Empty title="سازمان انتخاب نشده است" action={<Link className={cx(s.btn, s.primary)} href="/admin/access">بازگشت به دسترسی‌ها</Link>} />;
  return <div className={s.root}><PaymentPolicyAdmin orgId={org} /></div>;
}
