import { Link } from "react-router-dom";
import { Button } from "../components/ui/button";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="font-semibold tracking-tight">Leverin.ai</div>
        <div className="flex items-center gap-3">
          <Link to="/login" className="text-sm text-muted-foreground hover:text-foreground">
            Sign in
          </Link>
          <Button asChild>
            <Link to="/register">Get started</Link>
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-16 pt-10">
        <section className="grid gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <div>
            <div className="inline-flex rounded-full border border-border bg-secondary/25 px-3 py-1 text-xs uppercase tracking-[0.16em] text-muted-foreground">
              AI wealth guide
            </div>
            <h1 className="mt-6 max-w-3xl text-5xl font-semibold tracking-tight text-balance">
              Advisor-grade clarity for people without advisor-grade access.
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-muted-foreground">
              Leverin.ai helps high earners turn cash, debt, RSUs, and goals into a short list of
              reasonable paths. Not stock tips. Not generic robo-allocation. A calm way to decide what
              to do with your money.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button size="lg" asChild>
                <Link to="/register">Get your free wealth snapshot</Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <Link to="/login">I already have an account</Link>
              </Button>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              For high earners with meaningful savings. Educational guidance, not personalized investment advice.
            </p>
          </div>

          <div className="rounded-[28px] border border-border bg-gradient-to-br from-secondary/35 via-background to-background p-6 shadow-sm">
            <div className="rounded-2xl border border-border bg-background/80 p-5">
              <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Example decision</div>
              <div className="mt-3 text-lg font-medium">I have $120k cash and might buy a home in 3 years.</div>
              <div className="mt-5 grid gap-3">
                <ScenarioCard title="T-bills" subtitle="Capital stays stable for a near-term goal" />
                <ScenarioCard title="Split" subtitle="Part safety, part long-term investing" />
                <ScenarioCard title="Index path" subtitle="Higher growth, but more volatility risk" />
              </div>
            </div>
          </div>
        </section>

        <section className="mt-16 grid gap-4 md:grid-cols-3">
          <FeatureCard
            title="Reduce the decision space"
            body="See 3 to 4 reasonable paths, not a wall of content and not a random list of tickers."
          />
          <FeatureCard
            title="Adaptive education"
            body="Learn only the concepts needed for your current decision: liquidity, time horizon, concentration, debt drag."
          />
          <FeatureCard
            title="Structured outputs"
            body="Get a snapshot, path comparison, and practical checklist instead of generic chatbot prose."
          />
        </section>
        <footer className="mt-16 border-t border-border pt-6 text-sm text-muted-foreground">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p>
              Educational scenario comparison only. Not personalized investment advice.
            </p>
            <div className="flex items-center gap-4">
              <Link to="/privacy" className="hover:text-foreground">Privacy</Link>
              <Link to="/terms" className="hover:text-foreground">Terms</Link>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}

function FeatureCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-border bg-secondary/15 p-5">
      <div className="text-base font-medium">{title}</div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
    </div>
  );
}

function ScenarioCard({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="rounded-xl border border-border bg-secondary/20 p-4">
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-1 text-sm leading-6 text-muted-foreground">{subtitle}</div>
    </div>
  );
}
