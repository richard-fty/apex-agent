import { TopBar } from "../components/TopBar";

export function PrivacyPage() {
  return (
    <div className="min-h-screen bg-background">
      <TopBar />
      <div className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">Privacy</h1>
        <div className="mt-6 space-y-4 text-sm leading-7 text-muted-foreground">
          <p>
            Leverin.ai stores the financial profile and checklist state you choose to provide so the
            product can continue your planning workflow across sessions.
          </p>
          <p>
            The MVP is an educational planning product. It is not a brokerage and it does not execute
            trades or connect to your financial accounts by default.
          </p>
          <p>
            Do not enter information you are not comfortable sharing at this stage. The product is
            designed to start with minimum inputs and ask for more detail only when it materially affects
            the path comparison.
          </p>
        </div>
      </div>
    </div>
  );
}
