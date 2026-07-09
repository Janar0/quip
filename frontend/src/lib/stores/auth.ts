import { derived, writable } from 'svelte/store';

export interface UserInfo {
  id: string;
  email: string;
  username: string;
  name: string;
  role: string;
  profile_image_url: string | null;
}

export const currentUser = writable<UserInfo | null>(null);
export const isAuthenticated = derived(currentUser, (user) => user !== null);

// The browser session is an HttpOnly cookie, so it must always be resolved via /me.
export const authLoading = writable<boolean>(true);
