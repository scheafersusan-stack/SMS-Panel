import { ROUTES } from "@/routes";
import { Card } from "@/ui/Card";
import { EmptyState } from "@/ui/Feedback";

/** Stand-in for every screen that a later task builds; shows the screen title. */
export function Placeholder({ route }: { route: string }) {
  const title = ROUTES[route]?.title ?? route;
  return (
    <>
      <div className="ph">
        <div className="ph-text">
          <h1>{title}</h1>
        </div>
      </div>
      <Card>
        <EmptyState title="این صفحه در مرحله‌های بعدی ساخته می‌شود">محتوای «{title}» به‌زودی اینجا نمایش داده می‌شود.</EmptyState>
      </Card>
    </>
  );
}
