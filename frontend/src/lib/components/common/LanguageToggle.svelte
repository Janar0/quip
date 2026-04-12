<script lang="ts">
  import { locale } from 'svelte-i18n';

  function setLocale(lang: string) {
    $locale = lang;
    localStorage.setItem('locale', lang);
  }
</script>

<div class="flex gap-1">
  <button
    class="btn btn-sm {$locale?.startsWith('en') ? 'preset-filled' : 'preset-outlined'}"
    onclick={() => setLocale('en')}
  >EN</button>
  <button
    class="btn btn-sm {$locale?.startsWith('ru') ? 'preset-filled' : 'preset-outlined'}"
    onclick={() => setLocale('ru')}
  >RU</button>
</div>
