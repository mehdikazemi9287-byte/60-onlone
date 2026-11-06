import { Suspense } from "react";
import { VambiSearch } from "@/components/vambi/VambiSearch";

export default function VambiHome() {
  return (
    <Suspense fallback={null}>
      <VambiSearch />
    </Suspense>
  );
}
