import { Breadcrumb } from "@/components/shared/Breadcrumb";
import { StrategyEditor } from "@/components/editor/StrategyEditor";

export default function NewStrategyPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[
        { label: "Strategies", href: "/strategies" },
        { label: "New" },
      ]} />
      <h1 className="text-2xl font-bold">New Strategy</h1>
      <StrategyEditor />
    </div>
  );
}
