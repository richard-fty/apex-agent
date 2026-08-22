import { Link } from "react-router-dom";
import { BarChart3, Newspaper, ShieldCheck, TrendingUp } from "lucide-react";
import { Button } from "../components/ui/button";

const HERO_IMAGE = "/landing-hero.jpg";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-950 dark:bg-[#07101e] dark:text-slate-50">
      <section className="relative isolate min-h-[88vh] overflow-hidden bg-[#eef8ff] dark:bg-[#07101e]">
        <img
          src={HERO_IMAGE}
          alt="Bright trading desk with stock charts and market research"
          className="absolute inset-0 h-full w-full object-cover object-[62%_center]"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(255,255,255,0.96)_0%,rgba(245,251,255,0.88)_35%,rgba(235,247,255,0.46)_66%,rgba(235,247,255,0.12)_100%)] dark:bg-[linear-gradient(90deg,rgba(7,16,30,0.91)_0%,rgba(7,16,30,0.76)_38%,rgba(7,16,30,0.36)_70%,rgba(7,16,30,0.14)_100%)]" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-[linear-gradient(0deg,rgba(255,255,255,1)_0%,rgba(255,255,255,0)_100%)] dark:bg-[linear-gradient(0deg,rgba(7,16,30,1)_0%,rgba(7,16,30,0)_100%)]" />

        <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Link to="/" className="text-sm font-semibold tracking-tight text-slate-950 dark:text-slate-50">
            Apex
          </Link>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              asChild
              className="border-slate-300 bg-white/80 text-slate-950 shadow-sm shadow-sky-900/5 hover:bg-white hover:text-slate-950 dark:border-slate-600 dark:bg-slate-950/35 dark:text-slate-50 dark:hover:bg-slate-900 dark:hover:text-white"
            >
              <Link to="/login">Sign in</Link>
            </Button>
            <Button asChild className="bg-slate-950 text-white shadow-sm shadow-sky-900/10 hover:bg-slate-800 hover:text-white dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100 dark:hover:text-slate-950">
              <Link to="/register">Register</Link>
            </Button>
          </div>
        </header>

        <div className="relative z-10 mx-auto flex min-h-[calc(88vh-76px)] max-w-6xl items-center px-6 pb-16">
          <div className="max-w-3xl">
            <div className="inline-flex border border-sky-200 bg-white/80 px-3 py-1 text-xs uppercase text-sky-800 shadow-sm shadow-sky-900/5 backdrop-blur dark:border-sky-300/25 dark:bg-white/10 dark:text-sky-100">
              Creative co-creation assistant
            </div>
            <h1 className="mt-6 text-5xl font-semibold leading-tight tracking-tight text-slate-950 md:text-7xl dark:text-slate-50">
              你可以和它对话、迭代、发布，一个有生命感的创作搭档
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-700 dark:text-slate-200">
              Apex 持续学习你的审美与风格偏好，能接管脚本、分镜、生图、配乐和发布文案的协同链路。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button size="lg" asChild className="bg-slate-950 text-white shadow-lg shadow-sky-900/10 hover:bg-slate-800 hover:text-white dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100 dark:hover:text-slate-950">
                <Link to="/register">Register</Link>
              </Button>
              <Button
                size="lg"
                variant="outline"
                asChild
                className="border-slate-300 bg-white/70 text-slate-950 shadow-sm shadow-sky-900/5 hover:bg-white hover:text-slate-950 dark:border-slate-500 dark:bg-slate-950/25 dark:text-slate-50 dark:hover:bg-slate-900 dark:hover:text-white"
              >
                <Link to="/login">Sign in</Link>
              </Button>
            </div>
            <div className="mt-10 grid max-w-xl gap-4 text-sm text-slate-700 sm:grid-cols-3 dark:text-slate-300">
              <p><span className="block text-base font-semibold text-slate-950 dark:text-white">Current</span>news and market data</p>
              <p><span className="block text-base font-semibold text-slate-950 dark:text-white">Structured</span>technical context</p>
              <p><span className="block text-base font-semibold text-slate-950 dark:text-white">Clear</span>risk framing</p>
            </div>
          </div>
        </div>
      </section>

      <main>
        <section className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-[#07101e]">
          <div className="mx-auto grid max-w-6xl gap-10 px-6 py-20 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
            <div>
              <div className="inline-flex items-center gap-2 text-xs uppercase text-sky-700 dark:text-sky-200">
                <TrendingUp className="h-4 w-4 text-emerald-500 dark:text-emerald-300" />
                Product intro
              </div>
              <h2 className="mt-4 max-w-xl text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl dark:text-slate-50">
                用会话驱动的方式，让创作从灵感到产出更顺畅
              </h2>
              <p className="mt-5 max-w-xl text-sm leading-7 text-slate-600 dark:text-slate-300">
                Apex 会把每一轮消息转化为可追踪的工作流：脚本版本、分镜清单、素材参数、模型调用、发布清单连续打通。
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <FeatureCard
                icon={<Newspaper className="h-5 w-5" />}
                title="Latest news first"
                body="Starts with the company name and top current news, not broad finance queries."
              />
              <FeatureCard
                icon={<BarChart3 className="h-5 w-5" />}
                title="Market data"
                body="Pulls price, volume, recent range, and period change from real data tools."
              />
              <FeatureCard
                icon={<TrendingUp className="h-5 w-5" />}
                title="Technical context"
                body="Adds RSI and moving-average context so momentum and trend are visible."
              />
              <FeatureCard
                icon={<ShieldCheck className="h-5 w-5" />}
                title="Clear limits"
                body="Frames outputs as research and education, not personalized investment advice."
              />
            </div>
          </div>
        </section>

        <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-slate-500 dark:text-slate-400">
          <p>Educational market research only. Not personalized investment advice.</p>
          <div className="flex items-center gap-4">
            <Link to="/privacy" className="hover:text-slate-950 dark:hover:text-white">Privacy</Link>
            <Link to="/terms" className="hover:text-slate-950 dark:hover:text-white">Terms</Link>
          </div>
        </footer>
      </main>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="border border-slate-200 bg-slate-50/80 p-5 shadow-sm shadow-sky-950/5 dark:border-slate-800 dark:bg-slate-950/35">
      <div className="flex h-10 w-10 items-center justify-center border border-slate-200 bg-white text-emerald-600 dark:border-slate-700 dark:bg-slate-900 dark:text-emerald-300">
        {icon}
      </div>
      <div className="mt-5 text-base font-medium text-slate-950 dark:text-slate-50">{title}</div>
      <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{body}</p>
    </div>
  );
}
