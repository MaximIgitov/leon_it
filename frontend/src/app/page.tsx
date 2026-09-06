import { Faq } from "@/components/landing/faq";
import { ForRecruiters } from "@/components/landing/for-recruiters";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { SiteFooter } from "@/components/landing/site-footer";
import { SiteHeader } from "@/components/landing/site-header";
import { VideoDemo } from "@/components/landing/video-demo";
export default function HomePage() {
  return <div className="landing"><SiteHeader /><main id="main"><Hero /><HowItWorks /><VideoDemo /><ForRecruiters /><Faq /></main><SiteFooter /></div>;
}
