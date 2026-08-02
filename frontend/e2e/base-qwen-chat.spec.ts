import { expect, test } from "@playwright/test";

test("Base Qwen chat, streaming, cancellation, retry, reset, and mobile layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "DohaLM" })).toBeVisible();
  await expect(page.locator(".model-status")).toContainText(/API online|base-qwen/);

  await page.getByText("생성 설정").click();
  await page.getByLabel("최대 토큰").fill("16");
  await page.getByLabel("Temperature").fill("0");
  await page.getByLabel("메시지 입력").fill("한국어로 짧게 인사해 주세요.");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  const firstAnswer = page.getByLabel("DohaLM 메시지").last();
  await expect(firstAnswer.locator("p")).not.toHaveText("");
  await expect(page.getByText("base-qwen")).toBeVisible();
  await expect(page.getByText("Qwen/Qwen2.5-1.5B-Instruct")).toBeVisible();
  await expect(page.getByLabel("메시지 입력")).toBeEnabled();

  await page.getByLabel("최대 토큰").fill("256");
  await page.getByLabel("메시지 입력").fill("한국어로 자세히 설명해 주세요.");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  const stop = page.getByRole("button", { name: "답변 생성 중단" });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(page.getByText("사용자가 생성을 중단했습니다.")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "새 대화" }).click();
  await expect(page.getByText("작은 언어 모델.")).toBeVisible();

  let injected = false;
  await page.route("**/api/v1/chat/stream", async (route) => {
    if (!injected) {
      injected = true;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'event: error\ndata: {"code":"STREAM_FAILED","message":"temporary","request_id":"req_e2etest"}\n\n',
      });
      return;
    }
    await route.continue();
  });
  await page.getByLabel("메시지 입력").fill("재시도 확인 질문입니다.");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.getByRole("button", { name: "재시도" })).toBeVisible();
  await page.getByRole("button", { name: "재시도" }).click();
  await expect(page.getByLabel("DohaLM 메시지").last().locator("p")).not.toHaveText("");
  await expect(page.getByLabel("메시지 입력")).toBeEnabled();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("메시지 입력")).toBeVisible();
  await expect(page.getByRole("button", { name: "API 상태 새로고침" })).toBeVisible();
});
