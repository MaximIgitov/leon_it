import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Дашборд" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Дашборд"
        description="Метрики по вакансиям и интервью появятся здесь после первых собеседований."
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {["Приглашений", "Пройдено интервью", "Средний балл", "Ждут решения"].map((label) => (
          <Card key={label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">—</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
