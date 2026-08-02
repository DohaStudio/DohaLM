"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="fatal-error">
      <span className="eyebrow">UI ERROR</span>
      <h1>화면을 불러오지 못했습니다.</h1>
      <p>개인 정보나 내부 오류 세부정보는 표시하지 않습니다.</p>
      <Button onClick={reset}>다시 시도</Button>
    </main>
  );
}
