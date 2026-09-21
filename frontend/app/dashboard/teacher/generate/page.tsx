import { BlueprintGenerator } from "@/components/teacher/blueprint-generator";
import { FacultyTasks } from "@/components/teacher/faculty-tasks";

export default function GeneratePage() {
  return (
    <div className="mx-auto max-w-3xl">
      <FacultyTasks />
      <BlueprintGenerator />
    </div>
  );
}
