export type LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
