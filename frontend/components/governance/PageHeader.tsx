// Intentionally renders nothing: page titles are shown by the app shell.
// The props stay in the signature so existing call sites keep type-checking.
export function PageHeader(props: { title: string; subtitle: string }) {
  void props;
  return null;
}
