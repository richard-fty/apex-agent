import { useMemo, useState } from "react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import type { FinancialProfile } from "../../types";

const goalOptions = [
  "Invest my idle cash",
  "Save for a home",
  "Keep money safe but productive",
];

const defaultProfile: FinancialProfile = {
  income: 0,
  cash: 0,
  monthly_expenses: 0,
  retirement: 0,
  brokerage: 0,
  rsus: 0,
  home_equity: 0,
  student_loans: 0,
  student_loan_rate: 0,
  credit_card_debt: 0,
  other_debt: 0,
  goals: [],
  home_purchase_horizon: null,
};

export type FinancialProfileSection =
  | "minimum"
  | "goals"
  | "expenses"
  | "debt"
  | "accounts"
  | "home_timing";

export function FinancialProfileForm({
  initialValue,
  sections = ["minimum"],
  title = "Start with two numbers",
  description = "Share annual income and your deposit. Leverin will assume the rest and give a first-pass strategy.",
  submitLabel = "Show my strategy",
  submitting,
  onSubmit,
}: {
  initialValue?: Partial<FinancialProfile> | null;
  sections?: FinancialProfileSection[];
  title?: string;
  description?: string;
  submitLabel?: string;
  submitting?: boolean;
  onSubmit: (profile: FinancialProfile) => Promise<void> | void;
}) {
  const [profile, setProfile] = useState<FinancialProfile>({
    ...defaultProfile,
    ...initialValue,
    goals: initialValue?.goals ?? defaultProfile.goals,
  });

  const show = useMemo(
    () => ({
      minimum: sections.includes("minimum"),
      goals: sections.includes("goals"),
      expenses: sections.includes("expenses"),
      debt: sections.includes("debt"),
      accounts: sections.includes("accounts"),
      homeTiming: sections.includes("home_timing"),
    }),
    [sections]
  );

  const canSubmit = useMemo(
    () =>
      (!show.minimum || (profile.income > 0 && profile.cash > 0)),
    [profile, show.minimum]
  );

  function setNumber<K extends keyof FinancialProfile>(key: K, value: string) {
    const next = value === "" ? 0 : Number(value);
    setProfile((current) => ({ ...current, [key]: Number.isFinite(next) ? next : 0 }));
  }

  function toggleGoal(goal: string) {
    setProfile((current) => {
      const goals = current.goals.includes(goal)
        ? current.goals.filter((item) => item !== goal)
        : [...current.goals, goal];
      return {
        ...current,
        goals,
        home_purchase_horizon:
          goals.includes("Buy a home") ? current.home_purchase_horizon : null,
      };
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const minimumOnly =
      show.minimum && !show.goals && !show.expenses && !show.debt && !show.accounts && !show.homeTiming;
    await onSubmit({
      ...profile,
      goals: minimumOnly
        ? ["Invest my idle cash"]
        : profile.goals.length > 0
          ? profile.goals
          : ["Invest my idle cash"],
      home_purchase_horizon: minimumOnly ? null : profile.home_purchase_horizon,
    });
  }

  const minimumOnly = show.minimum && !show.goals && !show.expenses && !show.debt && !show.accounts && !show.homeTiming;

  if (minimumOnly) {
    return (
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <SectionHeading title={title} description={description} />
          <div className="hidden rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-100/90 sm:block">
            2 fields
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <MoneyField
            label="Annual income"
            value={profile.income}
            onChange={(value) => setNumber("income", value)}
            required
          />
          <MoneyField
            label="Deposit"
            value={profile.cash}
            onChange={(value) => setNumber("cash", value)}
            required
          />
          <Button
            type="submit"
            disabled={!canSubmit || submitting}
            className="h-11 rounded-lg px-5 sm:min-w-36"
          >
            {submitting ? "Saving..." : submitLabel}
          </Button>
        </div>
        {profileErrorHint(profile)}
      </form>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <section className="space-y-4">
        <SectionHeading title={title} description={description} />
        {show.minimum && (
          <>
            <NumberField
              label="Annual income"
              value={profile.income}
              onChange={(value) => setNumber("income", value)}
              required
            />
            <NumberField
              label="Deposit"
              value={profile.cash}
              onChange={(value) => setNumber("cash", value)}
              required
            />
          </>
        )}
        {show.expenses && (
          <NumberField
            label="Typical monthly living expenses"
            value={profile.monthly_expenses}
            onChange={(value) => setNumber("monthly_expenses", value)}
          />
        )}
      </section>

      {show.goals && (
        <section className="space-y-4">
          <SectionHeading
            title="What do you want help with?"
            description="Optional. Pick one if it matches your question."
          />
          <div className="grid gap-3">
            {goalOptions.map((goal) => {
              const checked = profile.goals.includes(goal);
              return (
                <label
                  key={goal}
                  className={`flex items-start gap-3 rounded-2xl border p-4 transition-colors ${
                    checked
                      ? "border-foreground/30 bg-secondary/30"
                      : "border-border bg-background/50"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={checked}
                    onChange={() => toggleGoal(goal)}
                  />
                  <span className="text-sm leading-6">{goal}</span>
                </label>
              );
            })}
          </div>
        </section>
      )}

      {(show.homeTiming || profile.goals.includes("Buy a home")) && (
        <section className="space-y-4">
          <SectionHeading
            title="Home timing"
            description="Only share this if home purchase timing matters to the decision."
          />
          <div className="space-y-2">
            <label className="text-sm font-medium">Home purchase horizon</label>
            <select
              value={profile.home_purchase_horizon ?? ""}
              onChange={(e) =>
                setProfile((current) => ({
                  ...current,
                  home_purchase_horizon: e.target.value || null,
                }))
              }
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="">Select a horizon</option>
              <option value="1-3 years">1-3 years</option>
              <option value="3-5 years">3-5 years</option>
              <option value="5+ years">5+ years</option>
            </select>
          </div>
        </section>
      )}

      {show.debt && (
        <section className="space-y-4">
          <SectionHeading
            title="Debt"
            description="A rough range is enough. Leave anything blank if it does not apply."
          />
          <div className="grid gap-4 md:grid-cols-2">
            <NumberField
              label="Student loans"
              value={profile.student_loans}
              onChange={(value) => setNumber("student_loans", value)}
            />
            <NumberField
              label="Student loan rate (%)"
              value={profile.student_loan_rate}
              onChange={(value) => setNumber("student_loan_rate", value)}
            />
            <NumberField
              label="Credit card debt"
              value={profile.credit_card_debt}
              onChange={(value) => setNumber("credit_card_debt", value)}
            />
            <NumberField
              label="Other debt"
              value={profile.other_debt}
              onChange={(value) => setNumber("other_debt", value)}
            />
          </div>
        </section>
      )}

      {show.accounts && (
        <section className="space-y-4">
          <SectionHeading
            title="Retirement and investment accounts"
            description="Approximate balances are fine. This is only to frame the recommendation."
          />
          <div className="grid gap-4 md:grid-cols-2">
            <NumberField
              label="401(k) / IRA / retirement accounts"
              value={profile.retirement}
              onChange={(value) => setNumber("retirement", value)}
            />
            <NumberField
              label="Brokerage account"
              value={profile.brokerage}
              onChange={(value) => setNumber("brokerage", value)}
            />
            <NumberField
              label="RSUs / employer stock"
              value={profile.rsus}
              onChange={(value) => setNumber("rsus", value)}
            />
            <NumberField
              label="Home equity"
              value={profile.home_equity}
              onChange={(value) => setNumber("home_equity", value)}
            />
          </div>
        </section>
      )}

      {show.minimum && !show.expenses && !show.debt && !show.accounts && (
        <section className="rounded-lg border border-border bg-secondary/15 p-4">
          <div className="text-sm font-medium">No full financial intake needed</div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Leverin will give a first-pass strategy with clear assumptions. You can refine it later
            with debt, expenses, or account details if you choose.
          </p>
        </section>
      )}

      <div className="flex items-center justify-end">
        <Button type="submit" disabled={!canSubmit || submitting}>
          {submitting ? "Saving..." : submitLabel}
        </Button>
      </div>
    </form>
  );
}

function SectionHeading({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function MoneyField({
  label,
  value,
  onChange,
  required = false,
}: {
  label: string;
  value: number;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</label>
      <div className="group relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground transition-colors group-focus-within:text-foreground">
          $
        </span>
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          step="any"
          required={required}
          value={value === 0 ? "" : Number.isFinite(value) ? String(value) : ""}
          onChange={(e) => onChange(e.target.value)}
          className="h-11 rounded-lg border-border bg-secondary/25 pl-7 text-base shadow-none focus-visible:ring-1"
          placeholder="0"
        />
      </div>
    </div>
  );
}

function profileErrorHint(profile: FinancialProfile) {
  if (profile.income > 0 || profile.cash > 0) return null;
  return (
    <p className="text-xs text-muted-foreground">
      Use rough numbers. Leverin will build the first pass from assumptions.
    </p>
  );
}

function NumberField({
  label,
  value,
  onChange,
  required = false,
}: {
  label: string;
  value: number;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">{label}</label>
      <Input
        type="number"
        inputMode="decimal"
        min={0}
        step="any"
        required={required}
        value={value === 0 ? "" : Number.isFinite(value) ? String(value) : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
