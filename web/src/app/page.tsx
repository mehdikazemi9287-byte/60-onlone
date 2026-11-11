import { Suspense } from "react";
import { VambiSearch } from "@/components/VambiSearch";

export default function Home() {
  return (
    <Suspense fallback={null}>
      <VambiSearch />
    </Suspense>
  );
}
