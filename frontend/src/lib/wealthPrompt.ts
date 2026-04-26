import type { FinancialProfile } from "../types";

export function buildWealthPrompt(profile: FinancialProfile): string {
  const goals = profile.goals.length > 0 ? profile.goals : ["Invest my idle cash"];
  const goalLines = goals.map((goal) => `- ${goal}`);
  if (profile.home_purchase_horizon) {
    goalLines.push(`- Home purchase horizon: ${profile.home_purchase_horizon}`);
  }

  const detailLines: string[] = [];
  if (profile.monthly_expenses > 0) {
    detailLines.push(`- Monthly expenses: ${profile.monthly_expenses}`);
  }
  if (profile.retirement > 0) {
    detailLines.push(`- Retirement accounts: ${profile.retirement}`);
  }
  if (profile.brokerage > 0) {
    detailLines.push(`- Brokerage: ${profile.brokerage}`);
  }
  if (profile.rsus > 0) {
    detailLines.push(`- RSUs / company stock (vested): ${profile.rsus}`);
  }
  if (profile.home_equity > 0) {
    detailLines.push(`- Home equity: ${profile.home_equity}`);
  }
  if (profile.student_loans > 0) {
    detailLines.push(`- Student loans: ${profile.student_loans} at ${profile.student_loan_rate}%`);
  }
  if (profile.credit_card_debt > 0) {
    detailLines.push(`- Credit card debt: ${profile.credit_card_debt}`);
  }
  if (profile.other_debt > 0) {
    detailLines.push(`- Other debt: ${profile.other_debt}`);
  }

  return `Here is my financial situation:

What I am comfortable sharing right now:
- Annual income: ${profile.income}
- Deposit / cash available to invest or save: ${profile.cash}

Goals:
${goalLines.join("\n")}

${detailLines.length > 0 ? `Additional details I have already shared:\n${detailLines.join("\n")}\n\n` : ""}I do not want to front-load too much private detail.

Please:
1. Build a first-pass wealth snapshot using only what I shared.
2. Do not ask follow-up questions before the first strategy. Assume unknown details are zero or unknown.
3. Show me 3 reasonable investment paths with plain-English tradeoffs.
4. State any assumptions briefly, then help me choose a direction.
5. Identify the 2 or 3 concepts I should understand before deciding.`;
}
