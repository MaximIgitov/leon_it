import {
  Link as RouterLink,
  defaultParseSearch,
  useLocation,
  useNavigate,
  useParams as useRouteParams,
} from "@tanstack/react-router";
import { forwardRef, useMemo, type AnchorHTMLAttributes } from "react";

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { href: string };

const Link = forwardRef<HTMLAnchorElement, LinkProps>(({ href, ...props }, ref) => {
  if (!href.startsWith("/") || href.startsWith("//")) return <a ref={ref} href={href} {...props} />;
  const url = new URL(href, "http://leon.local");
  return <RouterLink ref={ref} to={url.pathname} search={defaultParseSearch(url.search)} hash={url.hash.slice(1)} {...props} />;
});
Link.displayName = "Link";
export default Link;

export function usePathname() {
  return useLocation({ select: (location) => location.pathname });
}

export function useParams<T extends Record<string, string>>() {
  const params = useRouteParams({ strict: false });
  return params as T;
}

export function useSearchParams() {
  const search = useLocation({ select: (location) => location.searchStr });
  return useMemo(() => new URLSearchParams(search), [search]);
}

export function useRouter() {
  const navigate = useNavigate();
  return useMemo(() => ({
    push: (href: string) => navigate({ href }),
    replace: (href: string) => navigate({ href, replace: true }),
  }), [navigate]);
}
