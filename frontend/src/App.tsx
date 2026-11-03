import {
  BarChart3,
  Dumbbell,
  MessageSquare,
  Moon,
  PersonStanding,
  Sun,
  UserRound,
} from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { UploadPanel } from "@/components/documents/UploadPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { QuickLogForm } from "@/components/workout/QuickLogForm";

// Three.js 包体较大，只有切到「人体图」时才加载
const PlanStudio = lazy(() =>
  import("@/components/plan/PlanStudio").then((module) => ({
    default: module.PlanStudio,
  })),
);

const USER_ID_KEY = "fitness.userId";

type Theme = "dark" | "light";

function useTheme() {
  // index.html 里预设了 data-theme="dark"，所以初值直接从 DOM 读，不会闪一下白屏
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.dataset.theme as Theme | undefined) ?? "dark",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}

export default function App() {
  const [userId, setUserId] = useState(
    () => localStorage.getItem(USER_ID_KEY) ?? "default-user",
  );
  const { theme, toggle } = useTheme();
  const [tab, setTab] = useState("chat");

  useEffect(() => {
    localStorage.setItem(USER_ID_KEY, userId);
  }, [userId]);

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-4">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-brand to-brand-strong text-brand-ink shadow-lg">
          <Dumbbell className="size-6" />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-bold text-ink">健身 AI 教练</h1>
          <p className="text-xs text-ink-2">练得对，才练得动 —— 计划、记录、复盘</p>
        </div>

        <label className="flex items-center gap-2">
          <UserRound className="size-4 text-ink-muted" aria-hidden="true" />
          <span className="sr-only">用户 ID</span>
          <Input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="w-36"
            placeholder="用户 ID"
          />
        </label>

        <Button
          variant="outline"
          size="icon"
          className="size-9"
          onClick={toggle}
          aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </header>

      <div className="grid flex-1 items-start gap-4 lg:grid-cols-[1fr_20rem]">
        <Tabs value={tab} onValueChange={setTab} className="min-w-0">
          <TabsList className="mb-3">
            <TabsTrigger value="chat">
              <MessageSquare />
              对话
            </TabsTrigger>
            <TabsTrigger value="plan">
              <PersonStanding />
              人体图
            </TabsTrigger>
            <TabsTrigger value="dashboard">
              <BarChart3 />
              训练看板
            </TabsTrigger>
          </TabsList>

          {/* forceMount：聊天记录存在 ChatPanel 内部 state 里，切标签时标签页
              默认会卸载内容导致记录丢失，这里保持挂载（未激活时 Radix 自动
              hidden），切回对话时记录和进行中的流式回复都还在。 */}
          <TabsContent value="chat" forceMount>
            <Card className="h-[calc(100vh-12rem)] px-4 py-1">
              <ChatPanel
                userId={userId}
                onOpenPlan={() => setTab("plan")}
              />
            </Card>
          </TabsContent>

          <TabsContent value="plan">
            <div className="min-h-[42rem]">
              <Suspense
                fallback={
                  <div className="rounded-xl border border-hairline bg-card px-4 py-6 text-sm text-ink-2">
                    正在加载人体图与动作库…
                  </div>
                }
              >
                <PlanStudio userId={userId} />
              </Suspense>
            </div>
          </TabsContent>

          <TabsContent value="dashboard">
            <Dashboard userId={userId} />
          </TabsContent>
        </Tabs>

        <aside className="space-y-4">
          <QuickLogForm userId={userId} />
          <UploadPanel />
        </aside>
      </div>
    </div>
  );
}
