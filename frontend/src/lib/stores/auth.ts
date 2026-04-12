import { writable } from 'svelte/store';

export interface UserInfo {
  id: string;
  email: string;
  username: string;
  name: string;
  role: string;
  profile_image_url: string | null;
}

const storedToken = typeof localStorage !== 'undefined' ? localStorage.getItem('access_token') : null;

export const authToken = writable<string | null>(storedToken);
export const currentUser = writable<UserInfo | null>(null);
export const isAuthenticated = writable<boolean>(!!storedToken);

authToken.subscribe((token) => {
  isAuthenticated.set(!!token);
});
