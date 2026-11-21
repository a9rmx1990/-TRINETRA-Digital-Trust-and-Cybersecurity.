export const PRODUCT = "TRINETRA Digital Trust and Cybersecurity";

export function Brand({ href = "/" }: { href?: string }) {
  return <a className="workspace-brand" href={href}>
    <img src="/favicon.svg" width="32" height="32" alt="" />
    <span>Trinetra</span>
  </a>;
}
