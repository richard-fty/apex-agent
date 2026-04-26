import { TopBar } from "../components/TopBar";

export function TermsPage() {
  return (
    <div className="min-h-screen bg-background">
      <TopBar />
      <div className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">Terms</h1>
        <div className="mt-6 space-y-4 text-sm leading-7 text-muted-foreground">
          <p>
            Leverin.ai provides educational scenario comparison and planning support. It does not provide
            personalized investment advice, portfolio management, or trade execution.
          </p>
          <p>
            You are responsible for your own financial decisions. Any examples of asset categories or
            planning paths are educational only.
          </p>
          <p>
            The product is intended to reduce decision friction and explain tradeoffs. It is not a
            substitute for licensed financial, tax, or legal advice when your situation requires it.
          </p>
        </div>
      </div>
    </div>
  );
}
