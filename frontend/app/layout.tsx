import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DohaLM — Korean language model lab",
  description: "DohaLM FastAPI와 연결되는 개발용 채팅 인터페이스",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko"><body>{children}</body></html>;
}
