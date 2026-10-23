/**
 * closetCache — one shared, short-lived copy of the user's wardrobe.
 *
 * The closet screen, the outfit card's "swap a piece" sheet and the add-item flow all need
 * the same list. Without this each would refetch it (and each fetch can wake a sleeping
 * database). Entries live for a minute.
 *
 * Writers (add / delete / sign-out) bump `gen`, which makes any fetch that started earlier
 * unable to write its (now stale) snapshot back into the cache.
 */
import { getWardrobeItems, WardrobeItem } from '@/src/api/ai';

const TTL_MS = 60_000;

let cache: { userId: string; at: number; items: WardrobeItem[] } | null = null;
let inflight: { userId: string; promise: Promise<WardrobeItem[]> } | null = null;
let gen = 0;

/** Whatever is cached for this user right now (possibly stale), or null. */
export function peekCloset(userId: string): WardrobeItem[] | null {
  return cache && cache.userId === userId ? cache.items : null;
}

export async function getClosetItems(userId: string, opts: { force?: boolean } = {}): Promise<WardrobeItem[]> {
  const fresh = cache && cache.userId === userId && Date.now() - cache.at < TTL_MS;
  if (fresh && !opts.force) return cache!.items;

  // Joining a running fetch is safe: invalidateCloset() drops it if the closet changed since.
  if (inflight && inflight.userId === userId) return inflight.promise;

  const startedAt = gen;
  const promise: Promise<WardrobeItem[]> = getWardrobeItems(userId)
    .then((items) => {
      if (startedAt === gen) cache = { userId, at: Date.now(), items };
      return items;
    })
    .finally(() => {
      if (inflight?.promise === promise) inflight = null;
    });
  inflight = { userId, promise };
  return promise;
}

/** The closet changed on the server (item added): forget everything, including running fetches. */
export function invalidateCloset(): void {
  gen += 1;
  cache = null;
  inflight = null;
}

/** An item was deleted: patch the cached list in place so the next read needn't hit the server. */
export function removeFromCloset(userId: string, itemId: string): void {
  gen += 1;
  inflight = null;
  if (cache && cache.userId === userId) {
    cache = { ...cache, items: cache.items.filter((i) => i.item_id !== itemId) };
  }
}

/** Sign-out: nothing of the previous user's wardrobe should linger in memory. */
export function clearCloset(): void {
  invalidateCloset();
}
